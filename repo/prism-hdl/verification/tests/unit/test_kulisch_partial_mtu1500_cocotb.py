"""Kulisch groups split at MTU 1500 while preserving special-state bytes."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import ExactValue, encode_kulisch
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
SOURCE = bytes.fromhex("66778899aabb")
DESTINATION = bytes.fromhex("001122334455")
FINITE = encode_kulisch(ExactValue("finite", False, Fraction(1)), 320)
NEGATIVE_ZERO = encode_kulisch(ExactValue("zero", True, Fraction(0)), 320)


@cocotb.test()
async def odd_frame_capacity_and_tail_preserve_values(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    expected = tuple(
        encode_data_frame(
            DataPacket(
                PacketClass.DATA,
                KEY,
                10,
                11,
                12,
                17 + index,
                first,
                (NumberGroup(ConcreteFormat.KULISCH, (FINITE, NEGATIVE_ZERO) * (count // 2)),),
                last=index == 2,
            ),
            destination_mac=DESTINATION,
            source_mac=SOURCE,
            mtu=1500,
            kulisch_bits=320,
        )
        for index, (first, count) in enumerate(((0, 34), (34, 34), (68, 2)))
    )
    integer = int.from_bytes(FINITE[1:], "little")
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(expected[0][:56], "big") << 17
    dut.s_total_elements.value = 70
    dut.s_mtu.value = 1500
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = 2
    dut.s_tags.value = 0x0500
    dut.s_integers.value = integer
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    frames: list[bytes] = []
    partial = bytearray()

    async def observe() -> None:
        while True:
            await FallingEdge(dut.clk)
            await ReadOnly()
            assert int(dut.m_fault.value) == 0
            if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
                keep = int(dut.m_axis_tkeep.value)
                partial.extend(
                    int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()]
                )
                if int(dut.m_axis_tlast.value):
                    assert len(partial) == int(dut.m_frame_bytes.value)
                    frames.append(bytes(partial))
                    partial.clear()

    observer = cocotb.start_soon(observe())
    sent = 0
    for _ in range(300):
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = int(sent < 70)
        dut.s_tile_first_element.value = min(sent, 68)
        await ReadOnly()
        accepted = sent < 70 and int(dut.s_tile_ready.value)
        await RisingEdge(dut.clk)
        if accepted:
            sent += 2
        if sent == 70:
            break
    assert sent == 70
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(300):
        await FallingEdge(dut.clk)
        if len(frames) == len(expected):
            break
    observer.cancel()
    assert frames == list(expected)
