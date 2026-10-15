"""Ping-pong FP32 RESULT frames match NumberGroup bytes under AXI pressure."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
SOURCE = bytes.fromhex("66778899aabb")
DESTINATION = bytes.fromhex("001122334455")


def expected_frames(values: tuple[int, ...]) -> tuple[bytes, ...]:
    frames: list[bytes] = []
    for packet_id, first in enumerate(range(0, len(values), 352), start=17):
        count = min(352, len(values) - first)
        packet = DataPacket(
            PacketClass.RESULT,
            KEY,
            10,
            11,
            12,
            packet_id,
            first,
            (NumberGroup(ConcreteFormat.FP32, values[first : first + count]),),
            last=first + count == len(values),
        )
        frames.append(
            encode_data_frame(
                packet,
                destination_mac=DESTINATION,
                source_mac=SOURCE,
                mtu=1500,
                kulisch_bits=320,
            )
        )
    return tuple(frames)


async def initialize(dut: Any, header: bytes, total: int, *, clock: bool = True) -> None:
    if clock:
        cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(header[:56], "big") << 17
    dut.s_total_elements.value = total
    dut.s_mtu.value = 1500
    dut.s_format.value = 4
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = 0
    dut.s_tile_bits.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def capture(
    dut: Any,
    received: list[bytes],
    beat_cycles: list[int],
    *,
    stall_period: int,
) -> None:
    partial = bytearray()
    held: tuple[int, int, int, int] | None = None
    cycle = 0
    while True:
        await FallingEdge(dut.clk)
        dut.m_axis_tready.value = int(not stall_period or cycle % stall_period != 3)
        await ReadOnly()
        valid = int(dut.m_axis_tvalid.value)
        ready = int(dut.m_axis_tready.value)
        beat = (
            int(dut.m_axis_tdata.value),
            int(dut.m_axis_tkeep.value),
            int(dut.m_axis_tlast.value),
            int(dut.m_frame_bytes.value),
        )
        if held is not None:
            assert valid and beat == held
        held = beat if valid and not ready else None
        assert int(dut.m_fault.value) == 0
        if valid and ready:
            keep = beat[1]
            assert keep != 0 and keep == (1 << keep.bit_count()) - 1
            partial.extend(beat[0].to_bytes(64, "little")[: keep.bit_count()])
            beat_cycles.append(cycle)
            if beat[2]:
                assert len(partial) == beat[3]
                received.append(bytes(partial))
                partial.clear()
        cycle += 1


async def exercise(dut: Any, *, stall_period: int) -> tuple[int, int]:
    values = tuple(0x3F800000 + (index & 0xFFFF) for index in range(4096))
    expected = expected_frames(values)
    await initialize(dut, expected[0], len(values))
    received: list[bytes] = []
    beat_cycles: list[int] = []
    observer = cocotb.start_soon(capture(dut, received, beat_cycles, stall_period=stall_period))
    sent = 0
    input_stalls = 0
    for _ in range(3000):
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = int(sent < 256)
        dut.s_tile_first_element.value = min(sent, 255) * 16
        dut.s_tile_count.value = 16
        dut.s_tile_bits.value = (
            int.from_bytes(
                b"".join(
                    value.to_bytes(4, "little") for value in values[sent * 16 : sent * 16 + 16]
                ),
                "little",
            )
            if sent < 256
            else 0
        )
        await ReadOnly()
        accepted = sent < 256 and int(dut.s_tile_ready.value) == 1
        if sent < 256 and not accepted:
            input_stalls += 1
        await RisingEdge(dut.clk)
        if accepted:
            sent += 1
        if sent == 256:
            break
    assert sent == 256
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(3000):
        await FallingEdge(dut.clk)
        if len(received) == len(expected):
            break
    observer.cancel()
    assert tuple(received) == expected
    assert len(expected) == 12
    elapsed_cycles = beat_cycles[-1] - beat_cycles[0] + 1
    return elapsed_cycles, input_stalls


@cocotb.test()
async def twelve_result_frames_sustain_fp32_payload_without_output_stalls(dut: Any) -> None:
    cycles, input_stalls = await exercise(dut, stall_period=0)
    rate = 4096 * 32 / (cycles * 4)
    dut._log.info(
        "FP32 RESULT payload %.2f Gb/s across 12 frames, %d accepted-window cycles, "
        "%d input stalls",
        rate,
        cycles,
        input_stalls,
    )
    assert rate >= 100


@cocotb.test()
async def backpressured_result_frames_keep_packet_identity_and_bytes(dut: Any) -> None:
    cycles, _stalls = await exercise(dut, stall_period=7)
    dut._log.info("backpressured FP32 RESULT took %d accepted-window cycles", cycles)


@cocotb.test()
async def short_tail_keeps_only_declared_fp32_values(dut: Any) -> None:
    values = tuple(0x3F800000 + index for index in range(18))
    expected = expected_frames(values)
    await initialize(dut, expected[0], len(values))
    received: list[bytes] = []
    cycles: list[int] = []
    observer = cocotb.start_soon(capture(dut, received, cycles, stall_period=0))
    for first, count in ((0, 16), (16, 2)):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = first
        dut.s_tile_count.value = count
        dut.s_tile_bits.value = int.from_bytes(
            b"".join(value.to_bytes(4, "little") for value in values[first : first + count])
            + b"\xa5" * (64 - count * 4),
            "little",
        )
        dut.s_tile_valid.value = 1
        await ReadOnly()
        assert int(dut.s_tile_ready.value) == 1
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(30):
        await FallingEdge(dut.clk)
        if received:
            break
    observer.cancel()
    assert tuple(received) == expected
    assert len(cycles) == 3


def tile_bits(values: tuple[int, ...]) -> int:
    return int.from_bytes(b"".join(value.to_bytes(4, "little") for value in values), "little")


async def offer(dut: Any, first: int, values: tuple[int, ...]) -> None:
    """Offer one tile until it is taken."""
    await FallingEdge(dut.clk)
    dut.s_tile_first_element.value = first
    dut.s_tile_count.value = len(values)
    dut.s_tile_bits.value = tile_bits(values)
    dut.s_tile_valid.value = 1
    while True:
        await ReadOnly()
        taken = int(dut.s_tile_ready.value) == 1
        await RisingEdge(dut.clk)
        if taken:
            break
        await FallingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0


async def collect(dut: Any, received: list[bytes]) -> None:
    partial = bytearray()
    while True:
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
            keep = int(dut.m_axis_tkeep.value)
            partial.extend(int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            if int(dut.m_axis_tlast.value):
                received.append(bytes(partial))
                partial.clear()


@cocotb.test()
async def refused_tile_that_would_close_a_frame_sends_nothing_and_a_reset_recovers(
    dut: Any,
) -> None:
    values = tuple(0x40000000 + index for index in range(16))
    expected = expected_frames(values)
    # The reset comes in the cycle the fault rises, and long after it.
    for wait in (0, 40):
        await initialize(dut, expected[0], len(values), clock=wait == 0)
        received: list[bytes] = []
        observer = cocotb.start_soon(collect(dut, received))
        # The only tile of the vector, at the wrong position: it has all the
        # elements that are left, so it closes its frame in the cycle it is taken.
        await offer(dut, 16, values)
        assert int(dut.m_fault.value) == 1
        assert int(dut.s_tile_ready.value) == 0
        for _ in range(wait):
            await FallingEdge(dut.clk)
        assert received == []
        dut.s_reset.value = 1
        await FallingEdge(dut.clk)
        dut.s_reset.value = 0
        assert int(dut.m_fault.value) == 0
        await offer(dut, 0, values)
        for _ in range(40):
            await RisingEdge(dut.clk)
        observer.cancel()
        assert tuple(received) == expected
        assert int(dut.m_fault.value) == 0


@cocotb.test()
async def refused_tile_does_not_follow_the_frame_before_it_at_any_distance(dut: Any) -> None:
    started = False
    # The refused tile either opens the second frame or is added to it.
    for open_tiles in (0, 1):
        values = tuple(0x41000000 + index for index in range(352 + 16 * (open_tiles + 1)))
        expected = expected_frames(values)
        # The first frame takes 23 beats; the refused tile arrives before, during
        # and after them, also in the cycle the output would turn to its frame.
        for distance in range(0, 34):
            await initialize(dut, expected[0], len(values), clock=not started)
            started = True
            received: list[bytes] = []
            observer = cocotb.start_soon(collect(dut, received))
            for tile in range(22 + open_tiles):
                await offer(dut, tile * 16, values[tile * 16 : tile * 16 + 16])
            for _ in range(distance):
                await RisingEdge(dut.clk)
            await offer(dut, len(values), values[-16:])
            assert int(dut.m_fault.value) == 1
            for _ in range(60):
                await RisingEdge(dut.clk)
            observer.cancel()
            assert received == [expected[0]], (open_tiles, distance)
            assert int(dut.s_tile_ready.value) == 0
