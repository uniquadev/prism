"""Validated NumberGroup values retain deterministic arithmetic lane ownership."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 02 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0102 0304 0a0b0c0d 00000009 0003 02 01 0010 0f10 0000 "
    "01 00 0002 7f80 0000 "
    "02 00 0001 003c 0000"
)
KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
DST = bytes.fromhex("001122334455")
SRC = bytes.fromhex("66778899aabb")


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tvalid.value = 0
    dut.m_tile_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(dut: Any, frame: bytes) -> None:
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        await FallingEdge(dut.clk)
        dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
        dut.s_axis_tkeep.value = (1 << len(beat)) - 1
        dut.s_axis_tlast.value = int(offset + len(beat) == len(frame))
        dut.s_axis_tvalid.value = 1
        await ReadOnly()
        assert int(dut.s_axis_tready.value) == 1
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0


async def receive(dut: Any, expected: list[tuple[int, int, int, int, int]]) -> None:
    observed: list[tuple[int, int, int, int, int]] = []
    for tick in range(3000):
        await FallingEdge(dut.clk)
        dut.m_tile_ready.value = int(tick % 5 not in (0, 1))
        await ReadOnly()
        if int(dut.m_tile_valid.value) and int(dut.m_tile_ready.value):
            observed.append(
                (
                    int(dut.m_tile_first_element.value),
                    int(dut.m_tile_format.value),
                    int(dut.m_tile_count.value),
                    int(dut.m_tile_bits.value),
                    int(dut.m_tile_keep.value),
                )
            )
            if len(observed) == len(expected):
                assert observed == expected
                return
    raise AssertionError(f"tile builder stalled after {observed!r}")


@cocotb.test()
async def golden_mixed_groups_keep_global_lanes(dut: Any) -> None:
    await initialize(dut)
    await send(dut, GOLDEN)
    await receive(
        dut,
        [
            (0, 1, 2, (0x7F << (9 * 8)) | (0x80 << (10 * 8)), (1 << 9) | (1 << 10)),
            (0, 2, 1, 0x3C00 << (11 * 16), 1 << 11),
        ],
    )


@cocotb.test()
async def different_grouping_keeps_same_range_and_lane(dut: Any) -> None:
    await initialize(dut)
    layouts = (
        (
            NumberGroup(ConcreteFormat.INT8, (1, 2)),
            NumberGroup(ConcreteFormat.BF16, (0x3F80,)),
        ),
        (
            NumberGroup(ConcreteFormat.INT8, (1,)),
            NumberGroup(ConcreteFormat.INT8, (2,)),
            NumberGroup(ConcreteFormat.BF16, (0x3F80,)),
        ),
    )
    expected = [
        (0, 1, 1, 1 << (15 * 8), 1 << 15),
        (16, 1, 1, 2, 1),
        (16, 3, 1, 0x3F80 << 16, 1 << 1),
    ]
    for packet_id, groups in enumerate(layouts):
        packet = DataPacket(
            PacketClass.DATA, KEY, packet_id, 2, 3, packet_id, 15, groups, last=True
        )
        frame = encode_data_frame(
            packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
        )
        await send(dut, frame)
        await receive(dut, expected)


@cocotb.test()
async def every_native_format_keeps_fixed_lanes_across_beats_and_tail(dut: Any) -> None:
    await initialize(dut)
    widths = {
        ConcreteFormat.INT8: 8,
        ConcreteFormat.FP16: 16,
        ConcreteFormat.BF16: 16,
        ConcreteFormat.FP32: 32,
    }
    for packet_id, (fmt, width) in enumerate(widths.items(), start=50):
        await FallingEdge(dut.clk)
        dut.rst_n.value = 0
        dut.s_axis_tvalid.value = 0
        dut.m_tile_ready.value = 0
        for _ in range(3):
            await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        values = tuple((index * 37 + 1) & ((1 << width) - 1) for index in range(51))
        frame = encode_data_frame(
            DataPacket(
                PacketClass.DATA,
                KEY,
                1,
                2,
                3,
                packet_id,
                0,
                (NumberGroup(fmt, values),),
                last=True,
            ),
            destination_mac=DST,
            source_mac=SRC,
            mtu=1500,
            kulisch_bits=279,
        )
        await send(dut, frame)
        expected = []
        for first in (0, 16, 32, 48):
            tail = values[first : first + 16]
            bits = sum(value << (width * lane) for lane, value in enumerate(tail))
            expected.append((first, int(fmt), len(tail), bits, (1 << len(tail)) - 1))
        await receive(dut, expected)
