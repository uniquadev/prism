"""Byte-accurate NumberGroup admission and ordered value extraction."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import decode_native, encode_kulisch
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
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = 279
    dut.m_value_ready.value = 0
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


async def receive(
    dut: Any,
    expected: list[tuple[int, int, int, bytes, bool, bool]],
    *,
    stall_every: int = 0,
) -> None:
    observed: list[tuple[int, int, int, bytes, bool, bool]] = []
    current = bytearray()
    last_metadata = (0, 0, 0)
    saw_committed = False
    for tick in range(12000):
        await FallingEdge(dut.clk)
        dut.m_value_ready.value = int(not stall_every or tick % stall_every != 0)
        await ReadOnly()
        if int(dut.m_frame_valid.value):
            assert int(dut.m_frame_accept.value) == 1
            assert int(dut.m_frame_error.value) == 0
            saw_committed = True
        if int(dut.m_value_valid.value) and int(dut.m_value_ready.value):
            global_index = int(dut.m_global_index.value)
            fmt = int(dut.m_format.value)
            group_index = int(dut.m_group_index.value)
            byte_index = int(dut.m_byte_index.value)
            width = int(dut.m_value_bytes.value)
            assert byte_index == len(current)
            current.append(int(dut.m_value_byte.value))
            last_metadata = (global_index, fmt, group_index)
            if int(dut.m_element_last_byte.value):
                assert len(current) == width
                observed.append(
                    (
                        *last_metadata,
                        bytes(current),
                        bool(int(dut.m_group_last_byte.value)),
                        bool(int(dut.m_packet_last_byte.value)),
                    )
                )
                current.clear()
        if int(dut.m_done_valid.value):
            assert observed == expected
            assert saw_committed
            return
    raise AssertionError("NumberGroup reader did not finish within bounded cycles")


@cocotb.test()
async def independently_transcribed_golden_groups(dut: Any) -> None:
    await initialize(dut)
    await send(dut, GOLDEN)
    await receive(
        dut,
        [
            (9, 1, 0, bytes.fromhex("7f"), False, False),
            (10, 1, 0, bytes.fromhex("80"), True, False),
            (11, 2, 1, bytes.fromhex("003c"), True, True),
        ],
        stall_every=3,
    )


@cocotb.test()
async def packet_layout_does_not_change_global_positions(dut: Any) -> None:
    await initialize(dut)
    layouts = (
        (
            NumberGroup(ConcreteFormat.INT8, (1, 2, 3)),
            NumberGroup(ConcreteFormat.FP16, (0x3C00,)),
        ),
        (
            NumberGroup(ConcreteFormat.INT8, (1,)),
            NumberGroup(ConcreteFormat.INT8, (2, 3)),
            NumberGroup(ConcreteFormat.FP16, (0x3C00,)),
        ),
    )
    for packet_id, groups in enumerate(layouts):
        packet = DataPacket(PacketClass.DATA, KEY, 1, 2, 3, packet_id, 17, groups, last=True)
        frame = encode_data_frame(
            packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
        )
        await send(dut, frame)
        expected: list[tuple[int, int, int, bytes, bool, bool]] = []
        index = 17
        for group_index, group in enumerate(groups):
            for value_index, value in enumerate(group.values):
                width = 1 if group.format == ConcreteFormat.INT8 else 2
                expected.append(
                    (
                        index,
                        int(group.format),
                        group_index,
                        int(value).to_bytes(width, "little"),
                        value_index == len(group.values) - 1,
                        group_index == len(groups) - 1 and value_index == len(group.values) - 1,
                    )
                )
                index += 1
        await receive(dut, expected, stall_every=4)


@cocotb.test()
async def widest_kulisch_value_is_segmented_without_truncation(dut: Any) -> None:
    await initialize(dut)
    dut.s_mtu.value = 576
    dut.s_kulisch_bits.value = 4096
    value = encode_kulisch(decode_native(0x80000001, ConcreteFormat.FP32), 4096)
    packet = DataPacket(
        PacketClass.RESULT,
        KEY,
        2,
        1,
        3,
        99,
        0xFFFFFFFE,
        (NumberGroup(ConcreteFormat.KULISCH, (value,)),),
        last=True,
    )
    frame = encode_data_frame(
        packet, destination_mac=DST, source_mac=SRC, mtu=576, kulisch_bits=4096
    )
    assert len(value) == 513
    assert len(frame) == 576
    await send(dut, frame)
    await receive(dut, [(0xFFFFFFFE, 0x80, 0, value, True, True)], stall_every=7)
