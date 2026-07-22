from __future__ import annotations

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import ControlCommand, ControlFlag, Status


def control_header(
    transaction: int,
    fragment_index: int,
    fragment_count: int,
    *,
    command: ControlCommand = ControlCommand.CAPS_QUERY,
    flags: int = int(ControlFlag.REQUEST),
) -> int:
    fields = (
        (64, 0x1122334455667788),
        (64, transaction),
        (16, int(command)),
        (8, flags),
        (8, int(Status.OK)),
        (16, fragment_index),
        (16, fragment_count),
        (48, 0x020000000001),
        (48, 0x020000000002),
        (16, 1),
    )
    result = 0
    for width, value in fields:
        result = (result << width) | value
    return result


async def reset(dut) -> None:
    dut.rst_n.value = 0
    dut.s_start_valid.value = 0
    dut.s_byte_valid.value = 0
    dut.m_header_ready.value = 0
    dut.m_byte_ready.value = 0
    dut.error_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def send_fragment(
    dut,
    transaction: int,
    index: int,
    count: int,
    payload: bytes,
    *,
    command: ControlCommand = ControlCommand.CAPS_QUERY,
    flags: int = int(ControlFlag.REQUEST),
) -> None:
    dut.s_header.value = control_header(transaction, index, count, command=command, flags=flags)
    dut.s_payload_length.value = len(payload)
    dut.s_start_valid.value = 1
    while True:
        await Timer(1, unit="ps")
        if int(dut.s_start_ready.value):
            await RisingEdge(dut.clk)
            break
        await RisingEdge(dut.clk)
    dut.s_start_valid.value = 0
    for offset, value in enumerate(payload):
        dut.s_byte.value = value
        dut.s_byte_last.value = offset == len(payload) - 1
        dut.s_byte_valid.value = 1
        while True:
            await Timer(1, unit="ps")
            if int(dut.s_byte_ready.value):
                await RisingEdge(dut.clk)
                break
            await RisingEdge(dut.clk)
    dut.s_byte_valid.value = 0


async def receive_message(dut) -> tuple[int, bytes]:
    for _ in range(100):
        await Timer(1, unit="ps")
        if int(dut.m_header_valid.value):
            break
        await RisingEdge(dut.clk)
    else:
        raise AssertionError("reassembled header did not arrive")
    payload_length = int(dut.m_payload_length.value)
    dut.m_header_ready.value = 1
    await RisingEdge(dut.clk)
    dut.m_header_ready.value = 0

    random.seed(0xC017E0)
    payload = bytearray()
    held = None
    for _ in range(500):
        ready = random.randrange(4) != 0
        dut.m_byte_ready.value = ready
        await Timer(1, unit="ps")
        if int(dut.m_byte_valid.value):
            sample = (int(dut.m_byte.value), int(dut.m_byte_last.value))
            if not ready:
                if held is not None:
                    assert sample == held
                held = sample
            else:
                held = None
                payload.append(sample[0])
                if sample[1]:
                    await RisingEdge(dut.clk)
                    break
        await RisingEdge(dut.clk)
    dut.m_byte_ready.value = 0
    return payload_length, bytes(payload)


async def receive_error(dut) -> Status:
    for _ in range(100):
        await Timer(1, unit="ps")
        if int(dut.error_valid.value):
            status = Status(int(dut.error_status.value))
            dut.error_ready.value = 1
            await RisingEdge(dut.clk)
            dut.error_ready.value = 0
            return status
        await RisingEdge(dut.clk)
    raise AssertionError("expected reassembly error did not arrive")


@cocotb.test()
async def reverse_order_and_identical_duplicate_reassemble_once(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)
    await send_fragment(dut, 1, 1, 2, b"world")
    await send_fragment(dut, 1, 1, 2, b"world")
    await send_fragment(dut, 1, 0, 2, b"hello ")
    length, payload = await receive_message(dut)
    assert length == 11
    assert payload == b"hello world"


@cocotb.test()
async def malformed_conflicting_capacity_timeout_and_reset_paths_report_errors(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)

    await send_fragment(dut, 2, 0, 0, b"")
    assert await receive_error(dut) == Status.INVALID_REQUEST

    await send_fragment(dut, 3, 0, 2, b"abc")
    await send_fragment(dut, 3, 0, 2, b"abd")
    assert await receive_error(dut) == Status.TXN_CONFLICT

    await send_fragment(dut, 4, 0, 2, b"12345678")
    await send_fragment(dut, 4, 1, 2, b"abcde")
    assert await receive_error(dut) == Status.NO_OPERATION_SLOT

    await send_fragment(dut, 5, 0, 2, b"wait")
    assert await receive_error(dut) == Status.INVALID_STATE

    await send_fragment(dut, 6, 0, 2, b"discard")
    await reset(dut)
    await send_fragment(dut, 6, 1, 2, b"ok")
    await send_fragment(dut, 6, 0, 2, b"reset-")
    length, payload = await receive_message(dut)
    assert length == 8
    assert payload == b"reset-ok"
