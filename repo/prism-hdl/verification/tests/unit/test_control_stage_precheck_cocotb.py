"""Trusted in-band STAGE reaches the SINGLE fixed-context precheck."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

CONTEXT = bytes.fromhex(
    "01020200ffff0000000200080000200000000001011805dc80ff040802000000"
    "02000000000000010000000208000000"
    "000a000b000a000b"
    "000a00010002010102000000000100000000000108000000"
    "000b00010003010102000000000200010000000108000000"
)
NODE = bytes.fromhex("020000000003")
MANAGER = bytes.fromhex("020000000000")


def stage_frame(context: bytes, source: bytes = MANAGER) -> bytes:
    header = (
        bytes.fromhex("0102030405060708 1122 3344 5566 778899aa 0a0b0c0d fffe fffe 01 00")
        + len(context).to_bytes(2, "big")
        + bytes.fromhex("00 01")
    )
    assert len(header) == 32
    return NODE + source + bytes.fromhex("88b5 20 01") + header + context


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
    dut.m_stage_ready.value = 0
    dut.m_command_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(dut: Any, frame: bytes) -> None:
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        for _ in range(200):
            await FallingEdge(dut.clk)
            dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            dut.s_axis_tkeep.value = (1 << len(beat)) - 1
            dut.s_axis_tlast.value = int(offset + len(beat) == len(frame))
            dut.s_axis_tvalid.value = 1
            await ReadOnly()
            if int(dut.s_axis_tready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError("STAGE ingress failed to return a frame credit")
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0


async def await_stage(dut: Any) -> tuple[int, int]:
    for _ in range(300):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_stage_valid.value):
            return int(dut.m_stage_accept.value), int(dut.m_stage_error.value)
    raise AssertionError("no STAGE precheck result")


@cocotb.test()
async def golden_stage_passes_complete_frame_and_context_precheck(dut: Any) -> None:
    await initialize(dut)
    assert len(CONTEXT) == 104
    await send(dut, stage_frame(CONTEXT))
    assert await await_stage(dut) == (1, 0)
    assert int(dut.m_child_count.value) == 2
    assert int(dut.m_result_count.value) == 2
    assert int(dut.m_element_count.value) == 1
    assert int(dut.m_kulisch_bits.value) == 280
    assert int(dut.m_accumulator.value) == 0x80
    assert int(dut.m_partial_wire.value) == 0xFF
    assert int(dut.m_local_endpoints.value) & 0xFFFFFFFF == (11 << 16) | 10
    assert int(dut.m_local_ports.value) & 0xFFFFFFFF == (3 << 16) | 2
    assert int(dut.m_rank_ids.value) & 0xFFFFFFFF == 1 << 16
    assert int(dut.m_result_enabled.value) & 0b11 == 0b11
    await FallingEdge(dut.clk)
    dut.m_stage_ready.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def stage_width_failure_is_reported_without_admission(dut: Any) -> None:
    await initialize(dut)
    body = bytearray(CONTEXT)
    body[20:22] = (8).to_bytes(2, "big")
    await send(dut, stage_frame(bytes(body)))
    assert await await_stage(dut) == (0, 2)


@cocotb.test()
async def untrusted_source_does_not_reach_context_parser(dut: Any) -> None:
    await initialize(dut)
    await send(dut, stage_frame(CONTEXT, bytes.fromhex("66778899aabb")))
    for _ in range(200):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_stage_valid.value) == 0


@cocotb.test()
async def malformed_rank_binding_rejected_after_fixed_context(dut: Any) -> None:
    await initialize(dut)
    body = bytearray(CONTEXT)
    second_binding = 48 + 8 + 24
    body[second_binding + 14 : second_binding + 16] = (0).to_bytes(2, "big")
    await send(dut, stage_frame(bytes(body)))
    assert await await_stage(dut) == (0, 4)


@cocotb.test()
async def trusted_commit_command_surfaces_without_stage(dut: Any) -> None:
    await initialize(dut)
    frame = bytearray(stage_frame(CONTEXT)[:48])
    frame[42] = 2
    frame[44:46] = b"\0\0"
    frame.extend(bytes(12))
    await send(dut, bytes(frame))
    for _ in range(100):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_command_valid.value):
            break
    else:
        raise AssertionError("trusted COMMIT command was not surfaced")
    assert int(dut.m_command.value) == 2
    assert int(dut.m_stage_valid.value) == 0
    await FallingEdge(dut.clk)
    dut.m_command_ready.value = 1
    await RisingEdge(dut.clk)
