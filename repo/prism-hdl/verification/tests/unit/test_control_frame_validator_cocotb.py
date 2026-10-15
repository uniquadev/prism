"""CONTROL frames are admitted only after whole-frame and padding validation."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 01 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0a0b0c0d 0102 0304 07 00 0000 00 01 "
    "000000000000000000000000"
)


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_mtu.value = 1500
    dut.m_ready.value = 0
    dut.m_read_address.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(dut: Any, frame: bytes, bad_keep: bool = False) -> None:
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        for _ in range(100):
            await FallingEdge(dut.clk)
            dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            keep = (1 << len(beat)) - 1
            dut.s_axis_tkeep.value = keep ^ (1 << 10) if bad_keep else keep
            dut.s_axis_tlast.value = int(offset + len(beat) == len(frame))
            dut.s_axis_tvalid.value = 1
            await ReadOnly()
            if int(dut.s_axis_tready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError("CONTROL receiver remained busy")
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0


async def report(dut: Any) -> tuple[int, int]:
    for _ in range(100):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            return int(dut.m_accept.value), int(dut.m_error_code.value)
    raise AssertionError("CONTROL validator did not report")


@cocotb.test()
async def independent_golden_control_header_and_zero_padding(dut: Any) -> None:
    await initialize(dut)
    assert len(GOLDEN) == 60
    await send(dut, GOLDEN)
    assert await report(dut) == (1, 0)
    assert int(dut.m_transaction_id.value) == 0x0A0B0C0D
    assert int(dut.m_command.value) == 7
    assert int(dut.m_body_bytes.value) == 0
    assert int(dut.m_frame_bytes.value) == 60
    await FallingEdge(dut.clk)
    dut.m_read_address.value = 42
    await ReadOnly()
    assert int(dut.m_read_data.value) == 7


@cocotb.test()
async def multibeat_stage_preserves_body_octets(dut: Any) -> None:
    await initialize(dut)
    header = bytearray(GOLDEN[:48])
    header[42] = 1
    header[44:46] = (48).to_bytes(2, "big")
    frame = bytes(header) + bytes(range(48))
    await send(dut, frame)
    assert await report(dut) == (1, 0)
    assert int(dut.m_frame_bytes.value) == 96
    for address in (48, 63, 64, 95):
        await FallingEdge(dut.clk)
        dut.m_read_address.value = address
        await ReadOnly()
        assert int(dut.m_read_data.value) == frame[address]


@cocotb.test()
async def bad_padding_or_axikeep_cannot_expose_body(dut: Any) -> None:
    await initialize(dut)
    frame = bytearray(GOLDEN)
    frame[-1] = 1
    await send(dut, bytes(frame))
    assert await report(dut) == (0, 4)
    assert int(dut.m_read_data.value) == 0
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    await send(dut, GOLDEN, bad_keep=True)
    assert await report(dut) == (0, 1)


@cocotb.test()
async def invalid_command_and_length_are_rejected(dut: Any) -> None:
    await initialize(dut)
    frame = bytearray(GOLDEN)
    frame[42] = 9
    await send(dut, bytes(frame))
    assert await report(dut) == (0, 2)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    frame = bytearray(GOLDEN)
    frame[44:46] = (1).to_bytes(2, "big")
    await send(dut, bytes(frame))
    assert await report(dut) == (0, 2)


@cocotb.test()
async def truncated_stage_and_invalid_fragment_count_are_rejected(dut: Any) -> None:
    await initialize(dut)
    frame = bytearray(GOLDEN)
    frame[42] = 1
    frame[44:46] = (48).to_bytes(2, "big")
    await send(dut, bytes(frame))
    assert await report(dut) == (0, 3)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    frame = bytearray(GOLDEN)
    frame[47] = 0
    await send(dut, bytes(frame))
    assert await report(dut) == (0, 2)


@cocotb.test()
async def frame_longer_than_the_largest_frame_is_a_receive_error(dut: Any) -> None:
    """Six bytes too many still fit the frame buffer; the length check must catch them."""
    await initialize(dut)
    await send(dut, GOLDEN.ljust(1520, b"\0"))
    assert await report(dut) == (0, 1)
