"""A 4096-bit Kulisch value fits the minimum negotiated MTU exactly."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import ExactValue, encode_kulisch
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

WIDTH = 4096
VALUE = encode_kulisch(ExactValue("finite", False, Fraction(1)), WIDTH)
KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
FRAME = encode_data_frame(
    DataPacket(
        PacketClass.DATA,
        KEY,
        10,
        11,
        12,
        17,
        0,
        (NumberGroup(ConcreteFormat.KULISCH, (VALUE,)),),
        last=True,
    ),
    destination_mac=bytes.fromhex("001122334455"),
    source_mac=bytes.fromhex("66778899aabb"),
    mtu=576,
    kulisch_bits=WIDTH,
)


async def initialize(dut: Any, *, count: int) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(FRAME[:56], "big") << 17
    dut.s_total_elements.value = count
    dut.s_mtu.value = 576
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = count
    dut.s_tags.value = 0
    dut.s_integers.value = int.from_bytes(VALUE[1:], "little")
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


@cocotb.test()
async def widest_value_round_trips_as_one_frame(dut: Any) -> None:
    await initialize(dut, count=1)
    dut.s_tile_valid.value = 1
    await ReadOnly()
    assert int(dut.s_tile_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    received = bytearray()
    for _ in range(50):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_fault.value) == 0
        if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
            keep = int(dut.m_axis_tkeep.value)
            received.extend(int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            if int(dut.m_axis_tlast.value):
                assert int(dut.m_frame_bytes.value) == len(FRAME) == 576
                break
    assert bytes(received) == FRAME


@cocotb.test()
async def two_widest_values_cannot_enter_one_frame(dut: Any) -> None:
    await initialize(dut, count=2)
    dut.s_tile_valid.value = 1
    await ReadOnly()
    assert int(dut.s_tile_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    await ReadOnly()
    assert int(dut.m_fault.value) == 1
    assert int(dut.m_axis_tvalid.value) == 0
