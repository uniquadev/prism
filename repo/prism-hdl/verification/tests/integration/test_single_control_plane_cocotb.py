"""Actual CONTROL frames drive one RTL SINGLE lifecycle and byte-exact ACKs."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import OperationKey
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
    decode_control_frame,
    encode_control_frame,
)

CONTEXT = bytes.fromhex(
    "01020200ffff0000000200080000200000000001011805dc80ff040802000000"
    "02000000000000010000000208000000"
    "000a000b000a000b"
    "000a00010002010102000000000100000000000108000000"
    "000b00010003010102000000000200010000000108000000"
)
NODE = bytes.fromhex("020000000003")
MANAGER = bytes.fromhex("020000000000")
KEY = OperationKey(1, 1, 0, 1, 1)


def key_bits(key: OperationKey) -> int:
    return (
        (key.job_id << 80)
        | (key.group_id << 64)
        | (key.group_generation << 48)
        | (key.operation_id << 32)
        | key.operation_generation
    )


def frame(
    command: ControlCommand,
    transaction: int,
    *,
    key: OperationKey = KEY,
    body: bytes = b"",
) -> bytes:
    packet = ControlPacket(key, transaction, 0xFFFE, 0xFFFE, command, body=body)
    return encode_control_frame(packet, destination_mac=NODE, source_mac=MANAGER, mtu=1500)


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_local_mac.value = int.from_bytes(NODE, "big")
    dut.s_manager_mac.value = int.from_bytes(MANAGER, "big")
    dut.s_manager_port.value = 1
    dut.s_control_endpoint.value = 0xFFFE
    dut.s_link_mtu.value = 1500
    dut.s_usable_port_mask.value = 0xE
    dut.s_shared_port_demux.value = 0
    dut.s_complete_operation.value = 0
    dut.s_complete_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(dut: Any, request: bytes) -> None:
    for offset in range(0, len(request), 64):
        beat = request[offset : offset + 64]
        for _ in range(5000):
            await FallingEdge(dut.clk)
            dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            dut.s_axis_tkeep.value = (1 << len(beat)) - 1
            dut.s_axis_tlast.value = int(offset + len(beat) == len(request))
            dut.s_axis_tvalid.value = 1
            await ReadOnly()
            if int(dut.s_axis_tready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError("CONTROL ingress did not return frame ownership")
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0


async def ack(dut: Any, transaction: int, status: int) -> None:
    for _ in range(5000):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_axis_tvalid.value):
            break
    else:
        raise AssertionError(f"no ACK for transaction {transaction}")
    assert int(dut.m_axis_tkeep.value) == (1 << 60) - 1
    assert int(dut.m_axis_tlast.value) == 1
    assert int(dut.m_frame_bytes.value) == 60
    encoded = int(dut.m_axis_tdata.value).to_bytes(64, "little")[:60]
    decoded = decode_control_frame(encoded, mtu=1500)
    assert decoded.command == ControlCommand.ACK
    assert decoded.transaction_id == transaction
    assert decoded.status == status
    assert encoded[:6] == MANAGER and encoded[6:12] == NODE
    for _ in range(3):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_axis_tvalid.value) == 1
        assert int(dut.m_axis_tdata.value).to_bytes(64, "little")[:60] == encoded
    await FallingEdge(dut.clk)
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_axis_tready.value = 0


@cocotb.test()
async def stage_commit_complete_release_and_generation(dut: Any) -> None:
    await initialize(dut)
    stage = frame(ControlCommand.STAGE, 10, body=CONTEXT)
    await send(dut, stage)
    await ack(dut, 10, 0)
    assert int(dut.m_context_installed.value) == 1
    assert int(dut.m_context_active.value) == 0
    commit = frame(ControlCommand.COMMIT, 11)
    await send(dut, commit)
    await ack(dut, 11, 0)
    assert int(dut.m_context_active.value) == 1
    await FallingEdge(dut.clk)
    dut.s_complete_operation.value = key_bits(KEY)
    dut.s_complete_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_complete_valid.value = 0
    assert int(dut.m_context_complete.value) == 1
    await send(dut, frame(ControlCommand.RELEASE, 12))
    await ack(dut, 12, 0)
    assert int(dut.m_context_installed.value) == 0
    await send(dut, frame(ControlCommand.STAGE, 13, body=CONTEXT))
    await ack(dut, 13, 5)
    next_key = OperationKey(1, 1, 0, 1, 2)
    await send(dut, frame(ControlCommand.STAGE, 14, key=next_key, body=CONTEXT))
    await ack(dut, 14, 0)


@cocotb.test()
async def invalid_context_is_rejected_without_state(dut: Any) -> None:
    await initialize(dut)
    narrow = bytearray(CONTEXT)
    narrow[20:22] = (8).to_bytes(2, "big")
    request = frame(ControlCommand.STAGE, 30, body=bytes(narrow))
    await send(dut, request)
    await ack(dut, 30, 2)
    assert int(dut.m_context_installed.value) == 0
