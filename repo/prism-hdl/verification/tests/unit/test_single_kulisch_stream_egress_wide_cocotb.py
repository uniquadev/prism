"""A 64-lane exact RESULT source feeds the SINGLE AUTO packet path."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, encode_kulisch
from prism_ccl.wire.data import PacketClass, decode_data_frame

# Cycles from the first tile to the first output beat: a guard against
# latency growing unnoticed, not a rate.
FIRST_OUTPUT_LIMIT = 96


async def receive_result(dut: Any, metrics: dict[str, int], *, stall: bool) -> list[bytes]:
    frames: list[bytes] = []
    partial = bytearray()
    for cycle in range(5000):
        await FallingEdge(dut.clk)
        dut.m_axis_tready.value = int(not stall or cycle % 7 not in (2, 3))
        await ReadOnly()
        assert not int(dut.m_fault.value)
        if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
            now = int(get_sim_time(unit="ns"))
            metrics.setdefault("first_output_ns", now)
            metrics["last_output_ns"] = now
            keep = int(dut.m_axis_tkeep.value)
            assert keep == (1 << keep.bit_count()) - 1
            partial.extend(int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            if int(dut.m_axis_tlast.value):
                assert len(partial) == int(dut.m_axis_frame_bytes.value)
                frames.append(bytes(partial))
                partial.clear()
                if frames[-1][49] & 0x01:
                    return frames
    raise AssertionError("RESULT output did not complete")


async def run_exact_auto_result(
    dut: Any,
    lanes: int,
    *,
    stall: bool = False,
    exact_lanes: tuple[int, ...] = (),
    start_clock: bool = True,
) -> float:
    """Send 4096 values, INT8 except on the exact lanes of every tile.

    Returns the rate of the output frames from the first to the last beat.
    """
    width = len(dut.s_tile_integers) // lanes
    exact_value = ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149))
    exact_wire = encode_kulisch(exact_value, width)
    narrow = 7 << 149
    exact = int.from_bytes(exact_wire[1:], "little")
    if start_clock:
        cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_start_valid.value = 0
    dut.s_clear.value = 0
    dut.s_operation.value = (1 << 80) | (1 << 64) | (1 << 32) | 1
    dut.s_element_count.value = 4096
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = width
    dut.s_auto_output.value = 1
    dut.s_native_input.value = 0
    dut.s_native_wide.value = 0
    dut.s_error_only.value = 0
    dut.s_child_count.value = 1
    dut.s_result_enabled.value = 1
    dut.s_local_endpoints.value = 10
    dut.s_peer_endpoints.value = 1
    dut.s_local_ports.value = 2
    dut.s_peer_macs.value = int.from_bytes(bytes.fromhex("020000000001"), "big")
    dut.s_local_mac.value = int.from_bytes(bytes.fromhex("020000000003"), "big")
    dut.m_store_read_ready.value = 1
    dut.s_tile_first_element.value = 0
    dut.s_tile_keep.value = (1 << lanes) - 1
    dut.s_tile_tags.value = 0
    dut.s_tile_integers.value = sum(
        (exact if lane in exact_lanes else narrow) << (width * lane) for lane in range(lanes)
    )
    dut.s_tile_native_bits.value = 0
    dut.s_tile_error.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    dut.s_start_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_start_valid.value = 0

    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive_result(dut, metrics, stall=stall))
    issued = 0
    sent = 0
    first_ns = None
    for _ in range(5000):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = sent * lanes
        dut.s_tile_valid.value = int(sent < issued)
        await ReadOnly()
        if int(dut.m_store_read_valid.value) and int(dut.m_store_read_ready.value):
            assert int(dut.m_store_read_slot.value) == issued
            issued += 1
        if int(dut.s_tile_valid.value) and int(dut.s_tile_ready.value):
            if first_ns is None:
                first_ns = int(get_sim_time(unit="ns"))
            sent += 1
        if sent == 4096 // lanes and issued == 4096 // lanes:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"issued {issued} and delivered {sent} of {4096 // lanes} exact tiles")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    assert not int(dut.m_fault.value)
    packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=width) for payload in frames]
    next_element = 0
    values = []
    for packet in packets:
        assert packet.packet_class == PacketClass.RESULT
        assert packet.first_element == next_element
        next_element += packet.element_count
        assert exact_lanes or len(packet.groups) == 1
        values.extend((group.format, value) for group in packet.groups for value in group.values)
    assert values == [
        (ConcreteFormat.KULISCH, exact_wire)
        if index % lanes in exact_lanes
        else (ConcreteFormat.INT8, 7)
        for index in range(4096)
    ], exact_lanes
    assert packets[-1].last
    assert first_ns is not None
    burst_cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
    total_cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
    frame_gbps = sum(map(len, frames)) * 8 / (burst_cycles * 4)
    if exact_lanes:
        dut._log.info(
            "%d-lane exact AUTO RESULT, %d-bit exact values at lanes %s: AXI frame %.2f Gb/s; "
            "%d frames, %d bytes, %d/%d cycles (burst/total)",
            lanes,
            width,
            exact_lanes,
            frame_gbps,
            len(frames),
            sum(map(len, frames)),
            burst_cycles,
            total_cycles,
        )
    else:
        burst_gbps = 4096 * 8 / (burst_cycles * 4)
        total_gbps = 4096 * 8 / (total_cycles * 4)
        dut._log.info(
            "%d-lane exact AUTO RESULT INT8: %.2f Gb/s output burst; %.2f Gb/s "
            "first-input-to-last; %d/%d cycles",
            lanes,
            burst_gbps,
            total_gbps,
            burst_cycles,
            total_cycles,
        )
        if not stall:
            assert burst_gbps >= 100
    if not stall:
        assert total_cycles - burst_cycles <= FIRST_OUTPUT_LIMIT, total_cycles - burst_cycles
    return frame_gbps


@cocotb.test()
async def exact_auto_result_uses_wide_tiles_and_sustains_narrow_output(dut: Any) -> None:
    await run_exact_auto_result(dut, 64)


@cocotb.test()
async def sparse_exact_results_among_narrow_results_sustain_axi_frame_rate(dut: Any) -> None:
    """A few results per tile need the exact format; the frames still fill the link.

    The last case is the tile with the fewest bytes per segment of all: four
    segments, the first without an exact value and the last with nothing else.
    """
    lanes = len(dut.s_tile_keep)
    cases = (
        (0,),
        (17,),
        (40,),
        (16, 33, 50),
        (15, 16, 47, 48),
        (0, 16, 32, 48),
        (16, 32, 48),
        (16, 32, 63),
    )
    shortfalls = []
    for index, exact_lanes in enumerate(cases):
        if index:
            await FallingEdge(dut.clk)
        rate = await run_exact_auto_result(
            dut, lanes, exact_lanes=exact_lanes, start_clock=index == 0
        )
        if rate < 100:
            shortfalls.append(f"{exact_lanes}: {rate:.2f} Gb/s")
    assert not shortfalls, "sparse exact results, sustained output rate: " + "; ".join(shortfalls)


async def start_result(dut: Any, lanes: int, total: int, *, start_clock: bool) -> None:
    """Reset the egress and start an AUTO RESULT of `total` exact values of seven."""
    width = len(dut.s_tile_integers) // lanes
    if start_clock:
        cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_start_valid.value = 0
    dut.s_clear.value = 0
    dut.s_operation.value = (1 << 80) | (1 << 64) | (1 << 32) | 1
    dut.s_element_count.value = total
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = width
    dut.s_auto_output.value = 1
    dut.s_native_input.value = 0
    dut.s_native_wide.value = 0
    dut.s_error_only.value = 0
    dut.s_child_count.value = 1
    dut.s_result_enabled.value = 1
    dut.s_local_endpoints.value = 10
    dut.s_peer_endpoints.value = 1
    dut.s_local_ports.value = 2
    dut.s_peer_macs.value = int.from_bytes(bytes.fromhex("020000000001"), "big")
    dut.s_local_mac.value = int.from_bytes(bytes.fromhex("020000000003"), "big")
    dut.m_store_read_ready.value = 1
    dut.s_tile_first_element.value = 0
    dut.s_tile_keep.value = 0
    dut.s_tile_tags.value = 0
    dut.s_tile_integers.value = sum((7 << 149) << (width * lane) for lane in range(lanes))
    dut.s_tile_native_bits.value = 0
    dut.s_tile_error.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    dut.s_start_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_start_valid.value = 0


async def deliver_tiles(dut: Any, tiles: list[tuple[int, int]]) -> None:
    """Hand over the tiles, each as (first element, values), as they are asked for."""
    issued = 0
    sent = 0
    for _ in range(400):
        await FallingEdge(dut.clk)
        if sent < len(tiles):
            first, count = tiles[sent]
            dut.s_tile_first_element.value = first
            dut.s_tile_keep.value = (1 << count) - 1
        dut.s_tile_valid.value = int(sent < issued and sent < len(tiles))
        await ReadOnly()
        if int(dut.m_store_read_valid.value) and int(dut.m_store_read_ready.value):
            issued += 1
        if int(dut.s_tile_valid.value):
            sent += 1
        if sent == len(tiles):
            break
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0


@cocotb.test()
async def short_last_tile_is_expected_and_a_misplaced_tile_is_refused(dut: Any) -> None:
    lanes = len(dut.s_tile_keep)
    width = len(dut.s_tile_integers) // lanes
    # Two full tiles and a last one of seventeen values.
    total = 2 * lanes + 17
    await start_result(dut, lanes, total, start_clock=True)
    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive_result(dut, metrics, stall=False))
    await deliver_tiles(dut, [(0, lanes), (lanes, lanes), (2 * lanes, 17)])
    frames = await receiver
    packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=width) for payload in frames]
    values = [value for packet in packets for group in packet.groups for value in group.values]
    assert values == [7] * total
    assert packets[-1].last and not int(dut.m_fault.value)

    # The second tile is not the one that follows the first.
    await FallingEdge(dut.clk)
    await start_result(dut, lanes, total, start_clock=False)
    await deliver_tiles(dut, [(0, lanes), (2 * lanes, lanes)])
    for _ in range(6):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_fault.value):
            break
    else:
        raise AssertionError("a misplaced tile was not refused")
