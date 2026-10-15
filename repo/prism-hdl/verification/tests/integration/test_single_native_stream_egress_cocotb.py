"""SINGLE native RESULT streams once to each configured recipient."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.wire.data import PacketClass, decode_data_frame

NODE = bytes.fromhex("020000000003")
RANKS = (bytes.fromhex("020000000001"), bytes.fromhex("020000000002"))


def result_value(index: int, width: int) -> int:
    """A value of the output width that differs from element to element."""
    return (index * 0x9E3779B1 + 0x7F4A7C15) >> 5 & ((1 << (8 * width)) - 1)


def result_tile(slot: int, width: int, total: int) -> tuple[int, int]:
    """Keep mask and bits of one tile of sixteen results, one 32-bit lane each."""
    count = min(16, total - slot * 16)
    bits = 0
    for lane in range(16):
        # The bits above the output width, and the lanes past the vector,
        # carry a pattern that must not reach the frame.
        value = 0xA5A5A5A5
        if lane < count:
            value = (value << (8 * width) & 0xFFFFFFFF) | result_value(slot * 16 + lane, width)
        bits |= value << (32 * lane)
    return (1 << count) - 1, bits


async def stream_result(dut: Any, fmt: int, width: int, recipients: int, total: int = 4096) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_start_valid.value = 0
    dut.s_clear.value = 0
    dut.s_operation.value = (1 << 80) | (1 << 64) | (1 << 32) | 1
    dut.s_element_count.value = total
    dut.s_mtu.value = 1500
    dut.s_output_format.value = fmt
    dut.s_child_count.value = recipients
    dut.s_result_count.value = recipients
    dut.s_result_enabled.value = (1 << recipients) - 1
    dut.s_local_endpoints.value = 10 | (11 << 16)
    dut.s_peer_endpoints.value = 1 | (2 << 16)
    dut.s_local_ports.value = 2 | (3 << 16)
    dut.s_peer_macs.value = int.from_bytes(RANKS[0], "big") | (
        int.from_bytes(RANKS[1], "big") << 48
    )
    dut.s_local_mac.value = int.from_bytes(NODE, "big")
    dut.m_store_read_ready.value = 0
    dut.s_tile_first_element.value = 0
    dut.s_tile_keep.value = 0
    dut.s_tile_bits.value = 0
    dut.s_tile_error.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    dut.s_start_valid.value = 1
    await ReadOnly()
    assert int(dut.s_start_ready.value)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_start_valid.value = 0

    pending_slot: int | None = None
    frames: dict[int, list[bytes]] = {slot: [] for slot in range(recipients)}
    partial = bytearray()
    held: tuple[int, int, int, int] | None = None
    sending = False
    for cycle in range(5000):
        await FallingEdge(dut.clk)
        dut.m_axis_tready.value = int(cycle % 7 != 3)
        dut.m_store_read_ready.value = int(pending_slot is None)
        # Once the vector is collected and leaving, a tile nobody asked for
        # is on offer; it must not be taken.
        stray = sending and pending_slot is None
        dut.s_tile_valid.value = int(pending_slot is not None or stray)
        if stray:
            dut.s_tile_first_element.value = 0
            dut.s_tile_keep.value = 0xFFFF
            dut.s_tile_bits.value = (1 << 512) - 1
        if pending_slot is not None:
            keep, bits = result_tile(pending_slot, width, total)
            dut.s_tile_first_element.value = pending_slot * 16
            dut.s_tile_keep.value = keep
            dut.s_tile_bits.value = bits
        await ReadOnly()
        take_request = bool(int(dut.m_store_read_valid.value) and int(dut.m_store_read_ready.value))
        request_slot = int(dut.m_store_read_slot.value) if take_request else 0
        take_tile = bool(int(dut.s_tile_valid.value) and int(dut.s_tile_ready.value))
        assert not (stray and take_tile)
        valid = int(dut.m_axis_tvalid.value)
        ready = int(dut.m_axis_tready.value)
        beat = (
            int(dut.m_axis_tdata.value),
            int(dut.m_axis_tkeep.value),
            int(dut.m_axis_tlast.value),
            int(dut.m_axis_frame_bytes.value),
        )
        if held is not None:
            assert valid and beat == held
        held = beat if valid and not ready else None
        sending = sending or bool(valid)
        if valid and ready:
            port = int(dut.m_egress_port.value)
            slot = port - 2
            assert slot in frames
            assert beat[1] == (1 << beat[1].bit_count()) - 1
            partial.extend(beat[0].to_bytes(64, "little")[: beat[1].bit_count()])
            if beat[2]:
                assert len(partial) == beat[3]
                frames[slot].append(bytes(partial))
                partial.clear()
        await RisingEdge(dut.clk)
        if take_tile:
            pending_slot = None
        if take_request:
            assert pending_slot is None
            pending_slot = request_slot
        if int(dut.m_all_sent.value):
            break

    assert int(dut.m_all_sent.value)
    assert int(dut.m_sent_mask.value) == (1 << recipients) - 1
    assert int(dut.m_fault.value) == 0
    elements_per_frame = 22 * (64 // width)
    for slot in range(recipients):
        decoded = [decode_data_frame(frame, mtu=1500, kulisch_bits=280) for frame in frames[slot]]
        assert [packet.first_element for packet in decoded] == list(
            range(0, total, elements_per_frame)
        )
        assert [packet.packet_id for packet in decoded] == list(
            range(slot + 1, slot + 1 + len(decoded))
        )
        assert all(packet.packet_class == PacketClass.RESULT for packet in decoded)
        assert all(packet.groups[0].format.value == fmt for packet in decoded)
        assert all(len(packet.groups) == 1 for packet in decoded)
        mask = (1 << (8 * width)) - 1
        values = [value & mask for packet in decoded for value in packet.groups[0].values]
        assert values == [result_value(index, width) for index in range(total)]
        assert [packet.last for packet in decoded] == [False] * (len(decoded) - 1) + [True]


@cocotb.test()
async def int8_result_streams_once(dut: Any) -> None:
    await stream_result(dut, 1, 1, 1)


@cocotb.test()
async def fp16_result_streams_once(dut: Any) -> None:
    await stream_result(dut, 2, 2, 1)


@cocotb.test()
async def bf16_result_streams_once(dut: Any) -> None:
    await stream_result(dut, 3, 2, 1)


@cocotb.test()
async def fp32_result_streams_once(dut: Any) -> None:
    await stream_result(dut, 4, 4, 1)


@cocotb.test()
async def two_recipients_receive_complete_vectors(dut: Any) -> None:
    await stream_result(dut, 4, 4, 2)


@cocotb.test()
async def int8_result_with_a_short_last_tile_keeps_every_value(dut: Any) -> None:
    await stream_result(dut, 1, 1, 1, total=1451)


@cocotb.test()
async def fp16_result_with_a_short_last_tile_keeps_every_value(dut: Any) -> None:
    await stream_result(dut, 2, 2, 1, total=1451)


@cocotb.test()
async def bf16_result_with_one_source_tile_more_than_a_word(dut: Any) -> None:
    await stream_result(dut, 3, 2, 2, total=37)


@cocotb.test()
async def fp32_result_with_a_short_last_tile_keeps_every_value(dut: Any) -> None:
    await stream_result(dut, 4, 4, 1, total=1451)


@cocotb.test()
async def result_shorter_than_one_tile_is_one_frame(dut: Any) -> None:
    await stream_result(dut, 1, 1, 1, total=5)
