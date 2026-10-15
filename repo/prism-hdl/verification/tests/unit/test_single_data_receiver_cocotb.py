"""Bound SINGLE DATA frames reserve intervals before native tile delivery."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(1, 1, 0, 1, 1)
NODE = bytes.fromhex("020000000003")
RANK0 = bytes.fromhex("020000000001")
RANK1 = bytes.fromhex("020000000002")


def key_bits() -> int:
    return (1 << 80) | (1 << 64) | (1 << 32) | 1


def frame(
    rank: int,
    *,
    mtu: int = 1500,
    packet_id: int = 0,
    first_element: int = 0,
    source_mac: bytes | None = None,
    groups: tuple[NumberGroup, ...] | None = None,
    last: bool = True,
) -> bytes:
    default_groups = (
        (NumberGroup(ConcreteFormat.FP16, (0x3C00, 0x3C00)),)
        if rank == 0
        else (NumberGroup(ConcreteFormat.BF16, (0x3380, 0xBF80)),)
    )
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        1,
        10 + rank,
        10 + rank,
        packet_id,
        first_element,
        default_groups if groups is None else groups,
        last=last,
    )
    return encode_data_frame(
        packet,
        destination_mac=NODE,
        source_mac=source_mac or (RANK0 if rank == 0 else RANK1),
        mtu=mtu,
        kulisch_bits=279,
    )


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_active.value = 1
    dut.s_operation.value = key_bits()
    dut.s_total_elements.value = 2
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = 279
    dut.s_local_mac.value = int.from_bytes(NODE, "big")
    dut.s_child_count.value = 2
    dut.s_local_endpoints.value = (11 << 16) | 10
    dut.s_peer_endpoints.value = (1 << 16) | 1
    dut.s_local_ports.value = 0
    dut.s_peer_macs.value = (int.from_bytes(RANK1, "big") << 48) | int.from_bytes(RANK0, "big")
    dut.s_native_masks.value = (4 << 8) | 2
    dut.s_release.value = 0
    dut.m_frame_event_ready.value = 1
    dut.m_tile_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(dut: Any, payload: bytes, *, tail_fill: int = 0) -> None:
    for offset in range(0, len(payload), 64):
        beat = payload[offset : offset + 64]
        for _ in range(2000):
            await FallingEdge(dut.clk)
            dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, bytes((tail_fill,))), "little")
            dut.s_axis_tkeep.value = (1 << len(beat)) - 1
            dut.s_axis_tlast.value = int(offset + len(beat) == len(payload))
            dut.s_axis_tvalid.value = 1
            await ReadOnly()
            if int(dut.s_axis_tready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError("DATA receiver did not return ingress credit")
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0


async def send_contiguous(dut: Any, frames: tuple[bytes, ...]) -> None:
    for payload in frames:
        for offset in range(0, len(payload), 64):
            beat = payload[offset : offset + 64]
            for _ in range(2000):
                await FallingEdge(dut.clk)
                dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
                dut.s_axis_tkeep.value = (1 << len(beat)) - 1
                dut.s_axis_tlast.value = int(offset + len(beat) == len(payload))
                dut.s_axis_tvalid.value = 1
                await ReadOnly()
                if int(dut.s_axis_tready.value):
                    await RisingEdge(dut.clk)
                    break
            else:
                raise AssertionError("contiguous DATA stream exceeded ingress timeout")
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0


async def monitor(
    dut: Any,
    tiles: list[tuple[int, int, int, int, int]],
    events: list[int],
    tile_cycles: list[int] | None = None,
    tile_words: list[int] | None = None,
) -> None:
    cycle = 0
    while True:
        await FallingEdge(dut.clk)
        await ReadOnly()
        cycle += 1
        if int(dut.m_tile_valid.value) and int(dut.m_tile_ready.value):
            tiles.append(
                (
                    int(dut.m_tile_first_element.value),
                    int(dut.m_tile_format.value),
                    int(dut.m_tile_count.value),
                    int(dut.m_tile_contributor_slot.value),
                    int(dut.m_tile_keep.value),
                )
            )
            if tile_cycles is not None:
                tile_cycles.append(cycle)
            if tile_words is not None:
                tile_words.append(int(dut.m_tile_bits.value))
        if int(dut.m_frame_event_valid.value):
            events.append(int(dut.m_frame_event_status.value))


async def wait_events(dut: Any, events: list[int], count: int) -> None:
    for _ in range(3000):
        await FallingEdge(dut.clk)
        if len(events) >= count:
            return
    raise AssertionError(f"only {len(events)} DATA frame events; expected {count}")


@cocotb.test()
async def bound_terminal_arithmetic_error_bypasses_numeric_window(dut: Any) -> None:
    await initialize(dut)
    error = encode_data_frame(
        DataPacket(
            PacketClass.DATA,
            KEY,
            1,
            10,
            10,
            7,
            2,
            (),
            last=True,
            accumulation_inexact=True,
        ),
        destination_mac=NODE,
        source_mac=RANK0,
        mtu=1500,
        kulisch_bits=279,
    )
    await send(dut, error)
    for _ in range(120):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_arithmetic_error.value):
            break
    else:
        raise AssertionError("bound arithmetic error did not reach SINGLE")
    # The frame ends the stream at the end of the vector, where a DATA frame
    # without values would be in place: it must not be taken for one, now or
    # once the interval window has had time to answer.
    for _ in range(60):
        assert int(dut.m_receive_complete.value) == 0
        assert int(dut.m_tile_valid.value) == 0
        assert int(dut.m_frame_event_valid.value) == 0
        await FallingEdge(dut.clk)
        await ReadOnly()
    await FallingEdge(dut.clk)
    dut.s_release.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_release.value = 0
    await ReadOnly()
    assert int(dut.m_arithmetic_error.value) == 0


@cocotb.test()
async def twelve_fp32_frames_advance_one_4096_element_receive_stream(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 4096
    dut.s_native_masks.value = (4 << 8) | 8
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_cycles: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_cycles))
    for packet_id, first in enumerate(range(0, 4096, 352)):
        count = min(352, 4096 - first)
        await send(
            dut,
            frame(
                0,
                packet_id=packet_id,
                first_element=first,
                groups=(NumberGroup(ConcreteFormat.FP32, (0x3F800000,) * count),),
                last=first + count == 4096,
            ),
        )
        await wait_events(dut, events, packet_id + 1)
        assert events[-1] == 0
        assert int(dut.m_frame_cumulative_element.value) == first + count
    assert len(events) == 12
    assert int(dut.m_receive_complete.value) & 1
    assert len(tiles) == 256
    assert [tile[0] for tile in tiles] == list(range(0, 4096, 16))
    assert all(tile[1:] == (4, 16, 0, 0xFFFF) for tile in tiles)
    assert all(right - left == 1 for left, right in pairwise(tile_cycles[:22]))
    elapsed_cycles = tile_cycles[-1] - tile_cycles[0] + 1
    dut._log.info(
        "receiver FP32 payload %.2f Gb/s across %d frames and %d tile cycles",
        4096 * 32 / (elapsed_cycles * 4),
        12,
        elapsed_cycles,
    )
    observer.cancel()


@cocotb.test()
async def back_to_back_fp32_frames_overlap_receive_and_application(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 4096
    dut.s_native_masks.value = (4 << 8) | 8
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_cycles: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_cycles))
    frames = tuple(
        frame(
            0,
            packet_id=packet_id,
            first_element=first,
            groups=(
                NumberGroup(
                    ConcreteFormat.FP32,
                    (0x3F800000,) * min(352, 4096 - first),
                ),
            ),
            last=first + min(352, 4096 - first) == 4096,
        )
        for packet_id, first in enumerate(range(0, 4096, 352))
    )
    await send_contiguous(dut, frames)
    await wait_events(dut, events, 12)
    assert events == [0] * 12
    assert int(dut.m_receive_complete.value) & 1
    assert [tile[0] for tile in tiles] == list(range(0, 4096, 16))
    elapsed_cycles = tile_cycles[-1] - tile_cycles[0] + 1
    dut._log.info(
        "back-to-back receiver FP32 payload %.2f Gb/s across %d frames and %d tile cycles",
        4096 * 32 / (elapsed_cycles * 4),
        12,
        elapsed_cycles,
    )
    observer.cancel()


@cocotb.test()
async def invalid_prefetched_frame_does_not_claim_the_following_interval(dut: Any) -> None:
    await initialize(dut)
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    invalid = bytearray(frame(0, packet_id=0))
    invalid[56] = 0xFF
    valid = frame(0, packet_id=1)
    await send_contiguous(dut, (bytes(invalid), valid))
    await wait_events(dut, events, 1)
    assert events == [0]
    assert tiles == [(0, 2, 2, 0, 0b11)]
    assert int(dut.m_receive_complete.value) & 1
    observer.cancel()


@cocotb.test()
async def two_bound_ranks_complete_and_duplicate_interval_cannot_issue(dut: Any) -> None:
    await initialize(dut)
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    await send(dut, frame(0), tail_fill=0xA5)
    await wait_events(dut, events, 1)
    assert events == [0]
    assert int(dut.m_frame_binding_valid.value) == 1
    assert int(dut.m_frame_contributor_slot.value) == 0
    assert int(dut.m_frame_cumulative_element.value) == 2
    assert int(dut.m_frame_complete.value) == 1
    assert tiles == [(0, 2, 2, 0, 0b11)]
    assert int(dut.m_receive_complete.value) & 0b11 == 0b01
    await send(dut, frame(0))
    await wait_events(dut, events, 2)
    assert events[-1] == 4 and len(tiles) == 1
    await send(
        dut,
        frame(0, groups=(NumberGroup(ConcreteFormat.FP16, (0x3C00, 0xBC00)),)),
    )
    await wait_events(dut, events, 3)
    assert events[-1] == 4 and len(tiles) == 1
    await send(dut, frame(1))
    await wait_events(dut, events, 4)
    assert events == [0, 4, 4, 0]
    assert int(dut.m_frame_contributor_slot.value) == 1
    assert int(dut.m_frame_cumulative_element.value) == 2
    assert tiles[-1] == (0, 3, 2, 1, 0b11)
    assert int(dut.m_receive_complete.value) & 0b11 == 0b11
    await send(dut, frame(0, packet_id=99))
    await wait_events(dut, events, 5)
    assert events[-1] == 4
    assert len(tiles) == 2
    await FallingEdge(dut.clk)
    dut.s_release.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_release.value = 0
    for _ in range(20):
        await FallingEdge(dut.clk)
        if int(dut.m_idle.value):
            break
    assert int(dut.m_receive_complete.value) == 0
    await send(dut, frame(0, packet_id=100))
    await wait_events(dut, events, 6)
    assert events[-1] == 0
    observer.cancel()


@cocotb.test()
async def duplicate_intervals_do_not_reissue_arithmetic(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 4
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    first = frame(
        0,
        packet_id=50,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x3C00,)),),
        last=False,
    )
    second = frame(
        0,
        packet_id=51,
        first_element=1,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x4000,)),),
        last=False,
    )
    await send(dut, first)
    await wait_events(dut, events, 1)
    await send(dut, second)
    await wait_events(dut, events, 2)
    assert events == [0, 0]
    tile_count = len(tiles)
    await send(dut, first)
    await wait_events(dut, events, 3)
    assert events[-1] == 4 and len(tiles) == tile_count
    changed = frame(
        0,
        packet_id=50,
        groups=(NumberGroup(ConcreteFormat.FP16, (0xBC00,)),),
        last=False,
    )
    await send(dut, changed)
    await wait_events(dut, events, 4)
    assert events[-1] == 4 and len(tiles) == tile_count
    third = frame(
        0,
        packet_id=52,
        first_element=2,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x4200,)),),
        last=False,
    )
    await send(dut, third)
    await wait_events(dut, events, 5)
    assert events[-1] == 0
    tile_count = len(tiles)
    await send(dut, second)
    await wait_events(dut, events, 6)
    assert events[-1] == 4 and len(tiles) == tile_count
    await send(dut, first)
    await wait_events(dut, events, 7)
    assert events[-1] == 4 and len(tiles) == tile_count
    reused_id = frame(
        0,
        packet_id=50,
        first_element=3,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x4400,)),),
    )
    await send(dut, reused_id)
    await wait_events(dut, events, 8)
    assert events[-1] == 0 and len(tiles) == tile_count + 1
    await send(
        dut,
        frame(
            0,
            packet_id=53,
            first_element=3,
            groups=(NumberGroup(ConcreteFormat.FP16, (0x4400,)),),
        ),
    )
    await wait_events(dut, events, 9)
    assert events[-1] == 4 and len(tiles) == tile_count + 1
    assert int(dut.m_receive_complete.value) & 1
    observer.cancel()


@cocotb.test()
async def bounded_packet_window_accepts_reordered_ids_and_intervals(dut: Any) -> None:
    await initialize(dut)
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    first = frame(
        0,
        packet_id=80,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x3C00,)),),
        last=False,
    )
    last = frame(
        0,
        packet_id=81,
        first_element=1,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x4000,)),),
    )
    await send(dut, last)
    await wait_events(dut, events, 1)
    assert events == [0] and not (int(dut.m_receive_complete.value) & 1)
    await send(dut, first)
    await wait_events(dut, events, 2)
    assert events == [0, 0]
    assert int(dut.m_receive_complete.value) & 1
    tile_count = len(tiles)
    await send(dut, last)
    await wait_events(dut, events, 3)
    assert events[-1] == 4 and len(tiles) == tile_count
    observer.cancel()


@cocotb.test()
async def int8_second_mtu_packet_is_admitted_within_two_packet_window(dut: Any) -> None:
    await check_reordered_native_pair(dut, ConcreteFormat.INT8, 1400, 1, 1)


async def check_reordered_native_pair(
    dut: Any,
    format_id: ConcreteFormat,
    elements_per_frame: int,
    value: int,
    native_mask: int,
) -> None:
    await initialize(dut)
    total_elements = 2 * elements_per_frame
    dut.s_total_elements.value = total_elements
    dut.s_native_masks.value = (4 << 8) | native_mask
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    early_last = frame(
        0,
        packet_id=99,
        groups=(NumberGroup(format_id, (value,) * elements_per_frame),),
    )
    await send(dut, early_last)
    await wait_events(dut, events, 1)
    assert events == [4] and not tiles, "early LAST must not reserve an interval"
    first = frame(
        0,
        packet_id=100,
        groups=(NumberGroup(format_id, (value,) * elements_per_frame),),
        last=False,
    )
    second = frame(
        0,
        packet_id=101,
        first_element=elements_per_frame,
        groups=(NumberGroup(format_id, (value,) * elements_per_frame),),
    )
    await send(dut, second)
    await wait_events(dut, events, 2)
    assert events == [4, 0], "the second chunk is within the receive window"
    assert not (int(dut.m_receive_complete.value) & 1)
    await send(dut, first)
    await wait_events(dut, events, 3)
    assert events == [4, 0, 0]
    assert int(dut.m_receive_complete.value) & 1
    assert int(dut.m_frame_cumulative_element.value) == total_elements
    lane_positions = [
        tile[0] + lane for tile in tiles for lane in range(64) if tile[4] & (1 << lane)
    ]
    assert sorted(lane_positions) == list(range(total_elements))
    tile_count = len(tiles)
    await send(dut, second)
    await wait_events(dut, events, 4)
    assert events[-1] == 4 and len(tiles) == tile_count
    overlapping = frame(
        0,
        packet_id=102,
        first_element=elements_per_frame - 1,
        groups=(NumberGroup(format_id, (value, value)),),
        last=False,
    )
    await send(dut, overlapping)
    await wait_events(dut, events, 5)
    assert events[-1] == 4 and len(tiles) == tile_count
    observer.cancel()


@cocotb.test()
async def int8_full_mtu_pair_fits_the_two_frame_element_window(dut: Any) -> None:
    await check_reordered_native_pair(dut, ConcreteFormat.INT8, 1452, 1, 1)


@cocotb.test()
async def runtime_mtu_limits_the_reordered_element_window(dut: Any) -> None:
    await initialize(dut)
    dut.s_mtu.value = 576
    dut.s_total_elements.value = 1057
    dut.s_native_masks.value = (4 << 8) | 1
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    second = frame(
        0,
        mtu=576,
        packet_id=101,
        first_element=528,
        groups=(NumberGroup(ConcreteFormat.INT8, (1,) * 528),),
        last=False,
    )
    beyond_window = frame(
        0,
        mtu=576,
        packet_id=102,
        first_element=1056,
        groups=(NumberGroup(ConcreteFormat.INT8, (1,)),),
    )
    first = frame(
        0,
        mtu=576,
        packet_id=100,
        groups=(NumberGroup(ConcreteFormat.INT8, (1,) * 528),),
        last=False,
    )
    await send(dut, second)
    await wait_events(dut, events, 1)
    assert events == [0]
    await send(dut, beyond_window)
    await wait_events(dut, events, 2)
    assert events[-1] == 4
    await send(dut, first)
    await wait_events(dut, events, 3)
    assert events[-1] == 0 and int(dut.m_frame_cumulative_element.value) == 1056
    await send(dut, beyond_window)
    await wait_events(dut, events, 4)
    assert events[-1] == 0 and int(dut.m_receive_complete.value) & 1
    assert sum(tile[4].bit_count() for tile in tiles) == 1057
    observer.cancel()


@cocotb.test()
async def fp16_reversed_mtu_packets_preserve_intervals(dut: Any) -> None:
    await check_reordered_native_pair(dut, ConcreteFormat.FP16, 726, 0x3C00, 2)


@cocotb.test()
async def bf16_reversed_mtu_packets_preserve_intervals(dut: Any) -> None:
    await check_reordered_native_pair(dut, ConcreteFormat.BF16, 726, 0x3F80, 4)


@cocotb.test()
async def fp32_reversed_mtu_packets_preserve_intervals(dut: Any) -> None:
    await check_reordered_native_pair(dut, ConcreteFormat.FP32, 363, 0x3F800000, 8)


@cocotb.test()
async def wrong_peer_format_or_last_does_not_reserve_arithmetic_interval(dut: Any) -> None:
    await initialize(dut)
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    await send(dut, frame(0, source_mac=RANK1))
    await wait_events(dut, events, 1)
    assert events[-1] == 4 and not tiles
    await send(
        dut,
        frame(0, groups=(NumberGroup(ConcreteFormat.BF16, (0x3F80, 0x3F80)),)),
    )
    await wait_events(dut, events, 2)
    assert events[-1] == 4 and not tiles
    await send(dut, frame(0, last=False))
    await wait_events(dut, events, 3)
    assert events[-1] == 4 and not tiles
    await send(dut, frame(0))
    await wait_events(dut, events, 4)
    assert events[-1] == 0 and len(tiles) == 1
    observer.cancel()


@cocotb.test()
async def frame_event_retains_metadata_under_progress_backpressure(dut: Any) -> None:
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.m_frame_event_ready.value = 0
    await send(dut, frame(0, packet_id=77))
    for _ in range(2000):
        await FallingEdge(dut.clk)
        if int(dut.m_frame_event_valid.value):
            break
    assert int(dut.m_frame_event_valid.value) == 1
    for _ in range(5):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_frame_event_valid.value) == 1
        assert int(dut.m_frame_event_status.value) == 0
        assert int(dut.m_frame_packet_id.value) == 77
        assert int(dut.m_frame_cumulative_element.value) == 2
    await send(dut, frame(0, packet_id=78))
    assert int(dut.m_frame_event_valid.value) == 1
    assert int(dut.m_frame_packet_id.value) == 77
    await FallingEdge(dut.clk)
    dut.m_frame_event_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_frame_event_ready.value = 0
    for _ in range(2000):
        await FallingEdge(dut.clk)
        if int(dut.m_frame_event_valid.value):
            assert int(dut.m_frame_packet_id.value) == 78
            assert int(dut.m_frame_event_status.value) == 4
            break
    else:
        raise AssertionError("prefetched frame did not report its overlap")


@cocotb.test()
async def duplicate_wide_frame_does_not_issue_twice(dut: Any) -> None:
    await initialize(dut)
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    dut.s_total_elements.value = 3
    payload = frame(
        0,
        packet_id=91,
        groups=(NumberGroup(ConcreteFormat.FP16, (0x3C00, 0x4000, 0x4200)),),
    )
    assert len(payload) > 64
    await send(dut, payload, tail_fill=0xA5)
    await wait_events(dut, events, 1)
    assert events == [0] and len(tiles) == 1

    await send(dut, payload)
    for cycles_after_last_beat in range(16):
        await FallingEdge(dut.clk)
        if len(events) == 2:
            dut._log.info("two-beat duplicate rejected after %d cycles", cycles_after_last_beat)
            break
    else:
        raise AssertionError("two-beat duplicate rejection took more than 16 cycles")
    assert events == [0, 4] and len(tiles) == 1
    observer.cancel()


@cocotb.test()
async def uniform_fp32_group_issues_sixteen_positions_per_cycle(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 64
    dut.s_native_masks.value = (4 << 8) | 8
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_cycles: list[int] = []
    tile_words: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_cycles, tile_words))
    values = tuple(0x3F800000 + index for index in range(64))
    payload = frame(0, packet_id=92, groups=(NumberGroup(ConcreteFormat.FP32, values),))
    await send(dut, payload)
    await wait_events(dut, events, 1)
    assert events == [0]
    assert tiles == [(offset, 4, 16, 0, 0xFFFF) for offset in range(0, 64, 16)]
    assert tile_cycles == list(range(tile_cycles[0], tile_cycles[0] + 4))
    assert tile_words == [
        sum(value << (32 * lane) for lane, value in enumerate(values[offset : offset + 16]))
        for offset in range(0, 64, 16)
    ]
    observer.cancel()


@cocotb.test()
async def fp32_tail_tile_holds_under_backpressure(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 18
    dut.s_native_masks.value = (4 << 8) | 8
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_words: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_words=tile_words))

    async def stall_tiles() -> None:
        held: tuple[int, int, int, int] | None = None
        for cycle in range(500):
            await FallingEdge(dut.clk)
            dut.m_tile_ready.value = int(cycle % 3 != 1)
            await ReadOnly()
            valid = int(dut.m_tile_valid.value)
            beat = (
                int(dut.m_tile_first_element.value),
                int(dut.m_tile_count.value),
                int(dut.m_tile_keep.value),
                int(dut.m_tile_bits.value),
            )
            if held is not None:
                assert valid and beat == held
            held = beat if valid and not int(dut.m_tile_ready.value) else None

    staller = cocotb.start_soon(stall_tiles())
    values = tuple(0x3F800000 + index for index in range(18))
    await send(dut, frame(0, packet_id=93, groups=(NumberGroup(ConcreteFormat.FP32, values),)))
    await wait_events(dut, events, 1)
    assert events == [0]
    assert tiles == [(0, 4, 16, 0, 0xFFFF), (16, 4, 2, 0, 0x3)]
    assert tile_words == [
        sum(value << (32 * lane) for lane, value in enumerate(values[offset : offset + 16]))
        for offset in (0, 16)
    ]
    staller.cancel()
    observer.cancel()


@cocotb.test()
async def fp32_chunk_starting_inside_tile_keeps_global_lanes(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 19
    dut.s_native_masks.value = (4 << 8) | 8
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_words: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_words=tile_words))
    values = tuple(0x3F800000 + index for index in range(18))
    payload = frame(
        0,
        packet_id=94,
        first_element=1,
        groups=(NumberGroup(ConcreteFormat.FP32, values),),
    )
    await send(dut, payload)
    await wait_events(dut, events, 1)
    assert events == [0]
    assert tiles == [(0, 4, 15, 0, 0xFFFE), (16, 4, 3, 0, 0x7)]
    assert tile_words == [
        sum(value << (32 * (lane + 1)) for lane, value in enumerate(values[:15])),
        sum(value << (32 * lane) for lane, value in enumerate(values[15:])),
    ]
    observer.cancel()


async def check_full_native_group(
    dut: Any, input_format: ConcreteFormat, element_count: int, mask: int
) -> None:
    await initialize(dut)
    dut.s_total_elements.value = element_count
    dut.s_native_masks.value = (4 << 8) | mask
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_cycles: list[int] = []
    tile_words: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_cycles, tile_words))
    if input_format == ConcreteFormat.INT8:
        values = tuple((index % 127) + 1 for index in range(element_count))
        width = 8
    elif input_format == ConcreteFormat.FP16:
        values = tuple(0x3C00 | (index % 1024) for index in range(element_count))
        width = 16
    else:
        values = tuple(0x3F80 | (index % 128) for index in range(element_count))
        width = 16
    payload = frame(
        0,
        packet_id=95,
        groups=(NumberGroup(input_format, values),),
    )
    assert len(payload) <= 1514
    await send(dut, payload)
    await wait_events(dut, events, 1)
    assert events == [0]
    capacity = 512 // width
    assert tiles == [
        (
            offset,
            int(input_format),
            min(capacity, element_count - offset),
            0,
            (1 << min(capacity, element_count - offset)) - 1,
        )
        for offset in range(0, element_count, capacity)
    ]
    assert tile_cycles == list(range(tile_cycles[0], tile_cycles[0] + len(tiles)))
    assert tile_words == [
        sum(
            value << (lane * width) for lane, value in enumerate(values[offset : offset + capacity])
        )
        for offset in range(0, element_count, capacity)
    ]
    assert int(dut.m_receive_complete.value) & 1
    observer.cancel()


@cocotb.test()
async def full_mtu_int8_group_issues_native_beat_per_cycle(dut: Any) -> None:
    await check_full_native_group(dut, ConcreteFormat.INT8, 1452, 1)


@cocotb.test()
async def full_mtu_fp16_group_issues_native_beat_per_cycle(dut: Any) -> None:
    await check_full_native_group(dut, ConcreteFormat.FP16, 726, 2)


@cocotb.test()
async def full_mtu_bf16_group_issues_native_beat_per_cycle(dut: Any) -> None:
    await check_full_native_group(dut, ConcreteFormat.BF16, 726, 4)


async def check_native_backpressure(dut: Any, input_format: ConcreteFormat, mask: int) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 66
    dut.s_native_masks.value = (4 << 8) | mask
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    tile_words: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events, tile_words=tile_words))
    width = 8 if input_format == ConcreteFormat.INT8 else 16
    values = tuple(index + 1 for index in range(65))

    async def stall_tiles() -> None:
        held: tuple[int, int, int, int] | None = None
        for cycle in range(500):
            await FallingEdge(dut.clk)
            dut.m_tile_ready.value = int(cycle % 4 == 0)
            await ReadOnly()
            valid = int(dut.m_tile_valid.value)
            beat = (
                int(dut.m_tile_first_element.value),
                int(dut.m_tile_count.value),
                int(dut.m_tile_keep.value),
                int(dut.m_tile_bits.value),
            )
            if held is not None:
                assert valid and beat == held
            held = beat if valid and not int(dut.m_tile_ready.value) else None

    staller = cocotb.start_soon(stall_tiles())
    await send(
        dut,
        frame(
            0,
            packet_id=96,
            first_element=1,
            groups=(NumberGroup(input_format, values),),
        ),
    )
    await wait_events(dut, events, 1)
    assert events == [0]
    capacity = 512 // width
    expected_tiles = []
    expected_words = []
    value_index = 0
    while value_index < len(values):
        global_index = value_index + 1
        lane_start = global_index % capacity
        count = min(capacity - lane_start, len(values) - value_index)
        expected_tiles.append(
            (
                global_index - lane_start,
                int(input_format),
                count,
                0,
                ((1 << count) - 1) << lane_start,
            )
        )
        expected_words.append(
            sum(
                value << ((lane_start + lane) * width)
                for lane, value in enumerate(values[value_index : value_index + count])
            )
        )
        value_index += count
    assert tiles == expected_tiles
    assert tile_words == expected_words
    staller.cancel()
    observer.cancel()


@cocotb.test()
async def int8_native_tiles_hold_under_backpressure(dut: Any) -> None:
    await check_native_backpressure(dut, ConcreteFormat.INT8, 1)


@cocotb.test()
async def fp16_native_tiles_hold_under_backpressure(dut: Any) -> None:
    await check_native_backpressure(dut, ConcreteFormat.FP16, 2)


@cocotb.test()
async def bf16_native_tiles_hold_under_backpressure(dut: Any) -> None:
    await check_native_backpressure(dut, ConcreteFormat.BF16, 4)


def other_frame(
    *,
    key: OperationKey = KEY,
    first_element: int = 0,
    last: bool = True,
) -> bytes:
    packet = DataPacket(
        PacketClass.DATA,
        key,
        1,
        10,
        10,
        0,
        first_element,
        (NumberGroup(ConcreteFormat.FP16, (0x3C00, 0x3C00)),),
        last=last,
    )
    return encode_data_frame(
        packet, destination_mac=NODE, source_mac=RANK0, mtu=1500, kulisch_bits=279
    )


@cocotb.test()
async def frame_that_is_not_of_the_operation_reserves_no_interval(dut: Any) -> None:
    await initialize(dut)
    tiles: list[tuple[int, int, int, int, int]] = []
    events: list[int] = []
    observer = cocotb.start_soon(monitor(dut, tiles, events))
    refused = (
        # Another generation of the same operation.
        other_frame(key=replace(KEY, operation_generation=KEY.operation_generation + 1)),
        # Another job.
        other_frame(key=replace(KEY, job_id=KEY.job_id + 1)),
        # Elements past the end of the vector.
        other_frame(first_element=2),
    )
    for count, payload in enumerate(refused, start=1):
        await send(dut, payload)
        await wait_events(dut, events, count)
        assert events[-1] == 4 and not tiles, count
    # The frame of the operation is still taken afterwards.
    await send(dut, frame(0))
    await wait_events(dut, events, len(refused) + 1)
    assert events[-1] == 0 and len(tiles) == 1
    observer.cancel()
