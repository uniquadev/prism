"""Sixteen exact lanes feed two-value Kulisch packets without egress gaps."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from ..unit.test_kulisch_partial_tile_streamer_cocotb import (
    ELEMENTS,
    VALUE,
    WIDTH,
    expected_frames,
)

TARGET_GBPS = 120.0


@cocotb.test()
async def exact_tiles_sustain_kulisch_partial_frames(dut: Any) -> None:
    await exercise_path(dut, stall_period=0)


@cocotb.test()
async def exact_tiles_hold_frames_under_backpressure(dut: Any) -> None:
    await exercise_path(dut, stall_period=7)


async def exercise_path(dut: Any, *, stall_period: int) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    expected = expected_frames()
    integer = int.from_bytes(VALUE[1:], "little")
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(expected[0][:56], "big") << 17
    dut.s_total_elements.value = ELEMENTS
    dut.s_mtu.value = 576
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = 16
    dut.s_tile_tags.value = 0
    dut.s_tile_integers.value = sum(integer << (lane * WIDTH) for lane in range(16))
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    frames: list[bytes] = []
    partial = bytearray()
    accepted_cycles: list[int] = []
    cycle = 0
    axi_bytes = 0
    held: tuple[int, int, int, int] | None = None

    async def observe() -> None:
        nonlocal cycle, axi_bytes, held
        while True:
            await FallingEdge(dut.clk)
            if stall_period:
                dut.m_axis_tready.value = int(cycle % stall_period != 0)
            await ReadOnly()
            assert int(dut.m_fault.value) == 0
            current = (
                int(dut.m_axis_tdata.value),
                int(dut.m_axis_tkeep.value),
                int(dut.m_axis_tlast.value),
                int(dut.m_axis_tvalid.value),
            )
            if held is not None:
                assert current == held
            held = current if current[3] and not int(dut.m_axis_tready.value) else None
            if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
                keep = int(dut.m_axis_tkeep.value)
                assert keep and keep == (1 << keep.bit_count()) - 1
                axi_bytes += keep.bit_count()
                partial.extend(
                    int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()]
                )
                accepted_cycles.append(cycle)
                if int(dut.m_axis_tlast.value):
                    assert len(partial) == int(dut.m_frame_bytes.value)
                    frames.append(bytes(partial))
                    partial.clear()
            cycle += 1

    observer = cocotb.start_soon(observe())
    sent = 0
    for _ in range(10000):
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = int(sent < ELEMENTS)
        dut.s_tile_first_element.value = min(sent, ELEMENTS - 16)
        await ReadOnly()
        accepted = sent < ELEMENTS and int(dut.s_tile_ready.value)
        await RisingEdge(dut.clk)
        if accepted:
            sent += 16
        if sent == ELEMENTS:
            break
    assert sent == ELEMENTS
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(10000):
        await FallingEdge(dut.clk)
        if len(frames) == len(expected):
            break
    observer.cancel()

    assert frames == list(expected)
    assert axi_bytes == sum(map(len, expected))
    assert len(accepted_cycles) == 9 * len(expected)
    output_window = accepted_cycles[-1] - accepted_cycles[0] + 1
    frame_gbps = axi_bytes * 8 * 0.25 / output_window
    dut._log.info(
        "Exact tile to Kulisch partials AXI frame=%.2f Gb/s; %d frames, %d beats, %d cycles",
        frame_gbps,
        len(frames),
        len(accepted_cycles),
        output_window,
    )
    if stall_period:
        assert output_window > len(accepted_cycles)
    else:
        assert frame_gbps >= TARGET_GBPS
