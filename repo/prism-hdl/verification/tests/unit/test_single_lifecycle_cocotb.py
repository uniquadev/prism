"""One SINGLE context stages, activates, completes, and releases explicitly."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


def key(*, operation_generation: int = 1, job_id: int = 1) -> int:
    return (job_id << 80) | (1 << 64) | (0 << 48) | (1 << 32) | operation_generation


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_operation.value = key()
    dut.s_transaction_id.value = 0
    dut.s_command.value = 0
    dut.s_precheck_status.value = 0
    dut.s_context.value = 0
    dut.s_valid.value = 0
    dut.s_complete_operation.value = 0
    dut.s_complete_valid.value = 0
    dut.m_ack_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def command(
    dut: Any,
    opcode: int,
    transaction: int,
    *,
    operation: int | None = None,
    context: int = 0,
    precheck: int = 0,
) -> int:
    await FallingEdge(dut.clk)
    dut.s_operation.value = key() if operation is None else operation
    dut.s_transaction_id.value = transaction
    dut.s_command.value = opcode
    dut.s_context.value = context
    dut.s_precheck_status.value = precheck
    dut.s_valid.value = 1
    # A command is compared with the stored keys in its first cycle and
    # taken in its second.
    await ReadOnly()
    assert int(dut.s_ready.value) == 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    assert int(dut.m_ack_valid.value) == 1
    assert int(dut.m_ack_operation.value) == (key() if operation is None else operation)
    assert int(dut.m_ack_transaction_id.value) == transaction
    status = int(dut.m_ack_status.value)
    for _ in range(3):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_ack_valid.value) == 1
        assert int(dut.m_ack_status.value) == status
    await FallingEdge(dut.clk)
    dut.m_ack_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ack_ready.value = 0
    return status


async def complete(dut: Any, operation: int) -> None:
    await FallingEdge(dut.clk)
    dut.s_complete_operation.value = operation
    dut.s_complete_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_complete_valid.value = 0


@cocotb.test()
async def stage_commit_complete_release_and_higher_generation(dut: Any) -> None:
    await initialize(dut)
    assert await command(dut, 1, 10, context=0xAABBCCDD) == 0
    assert int(dut.m_context_installed.value) == 1
    assert int(dut.m_context_active.value) == 0
    assert int(dut.m_context.value) == 0xAABBCCDD
    assert await command(dut, 2, 11) == 0
    assert int(dut.m_context_active.value) == 1
    assert await command(dut, 4, 12) == 4
    await complete(dut, key())
    assert int(dut.m_context_complete.value) == 1
    assert await command(dut, 4, 13) == 0
    assert int(dut.m_context_installed.value) == 0
    assert await command(dut, 1, 14, context=7) == 5
    assert await command(dut, 1, 15, operation=key(operation_generation=2), context=7) == 0


@cocotb.test()
async def failed_precheck_and_single_slot_pressure_cannot_mutate_context(dut: Any) -> None:
    await initialize(dut)
    assert await command(dut, 1, 1, precheck=2, context=9) == 2
    assert int(dut.m_context_installed.value) == 0
    assert await command(dut, 1, 2, context=9) == 0
    assert await command(dut, 1, 3, operation=key(job_id=2), context=8) == 3
    assert int(dut.m_context.value) == 9
    assert await command(dut, 1, 4, context=8) == 4
    assert await command(dut, 6, 5) == 0
    assert int(dut.m_context_installed.value) == 0
    assert await command(dut, 1, 6, operation=key(job_id=2), context=8) == 0


@cocotb.test()
async def wrong_generation_completion_or_release_has_no_effect(dut: Any) -> None:
    await initialize(dut)
    assert await command(dut, 1, 1, context=3) == 0
    assert await command(dut, 2, 2) == 0
    await complete(dut, key(operation_generation=99))
    assert int(dut.m_context_active.value) == 1
    assert await command(dut, 4, 3, operation=key(operation_generation=99)) == 4
    assert int(dut.m_context_active.value) == 1


@cocotb.test()
async def command_behind_a_pending_answer_waits_and_meets_the_installed_keys(dut: Any) -> None:
    """A command waits while the answer to the one before it is pending.

    It is offered right behind the stage of its operation, is not taken
    while that answer is pending, and is then judged against the keys the
    stage has installed.
    """
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.s_operation.value = key()
    dut.s_transaction_id.value = 1
    dut.s_command.value = 1
    dut.s_context.value = 5
    dut.s_valid.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    # The commit of the same operation is on offer from the cycle after the
    # stage is taken, behind the pending answer.
    await FallingEdge(dut.clk)
    dut.s_transaction_id.value = 2
    dut.s_command.value = 2
    assert int(dut.m_ack_valid.value) == 1
    assert int(dut.m_ack_status.value) == 0
    for _ in range(4):
        await ReadOnly()
        assert int(dut.s_ready.value) == 0
        await FallingEdge(dut.clk)
    assert int(dut.m_context_active.value) == 0
    dut.m_ack_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ack_ready.value = 0
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    assert int(dut.m_ack_valid.value) == 1
    assert int(dut.m_ack_transaction_id.value) == 2
    assert int(dut.m_ack_status.value) == 0
    assert int(dut.m_context_active.value) == 1
