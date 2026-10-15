"""A bounded receiver window reserves whole element intervals atomically."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_candidate.value = 0
    dut.s_contributor_slot.value = 0
    dut.s_first_element.value = 0
    dut.s_element_count.value = 0
    dut.s_total_elements.value = 64
    dut.s_window_elements.value = 512
    dut.s_last.value = 0
    dut.s_valid.value = 0
    dut.s_release.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def reserve(
    dut: Any,
    contributor: int,
    first: int,
    count: int,
    *,
    total: int = 64,
    last: bool | None = None,
) -> int:
    await FallingEdge(dut.clk)
    dut.s_contributor_slot.value = contributor
    dut.s_first_element.value = first
    dut.s_element_count.value = count
    dut.s_total_elements.value = total
    dut.s_last.value = int(first + count == total if last is None else last)
    # The window prepares its comparisons in two steps before a frame is offered.
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(300):
        await ReadOnly()
        if int(dut.m_valid.value):
            break
        await FallingEdge(dut.clk)
    else:
        raise AssertionError("interval admission did not finish")
    reason = int(dut.m_reason.value)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    return reason


@cocotb.test()
async def runtime_window_span_limits_future_intervals_without_losing_credit(dut: Any) -> None:
    await initialize(dut)
    dut.s_window_elements.value = 16
    assert await reserve(dut, 0, 8, 8) == 0
    assert await reserve(dut, 0, 16, 1) == 1
    assert await reserve(dut, 0, 0, 8) == 0
    assert int(dut.m_watermarks.value) == 16
    assert await reserve(dut, 0, 16, 1) == 0


@cocotb.test()
async def overlapping_interval_rejected_before_any_new_element_is_reserved(dut: Any) -> None:
    await initialize(dut)
    assert await reserve(dut, 0, 0, 3) == 0
    assert await reserve(dut, 0, 1, 4) == 2
    assert await reserve(dut, 0, 3, 2) == 0
    assert await reserve(dut, 0, 0, 3) == 2
    assert await reserve(dut, 1, 0, 5) == 0
    assert await reserve(dut, 1, 60, 4) == 0
    assert int(dut.m_complete.value) == 0


@cocotb.test()
async def invalid_range_and_release_do_not_leak_arithmetic_ownership(dut: Any) -> None:
    await initialize(dut)
    assert await reserve(dut, 0, 7, 0) == 1
    assert await reserve(dut, 0, 63, 2) == 1
    assert await reserve(dut, 0, 0xFFFFFFFF, 2) == 1
    assert await reserve(dut, 0, 63, 1) == 0
    assert int(dut.m_complete.value) == 0
    await FallingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.s_release_ready.value) == 1
    await FallingEdge(dut.clk)
    dut.s_release.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_release.value = 0
    assert await reserve(dut, 0, 63, 1) == 0


@cocotb.test()
async def last_requires_full_coverage_from_each_contributor(dut: Any) -> None:
    await initialize(dut)
    assert await reserve(dut, 0, 0, 1, total=3) == 0
    assert int(dut.m_watermarks.value) == 1
    assert await reserve(dut, 0, 1, 2, total=3) == 0
    assert int(dut.m_watermarks.value) == 3
    assert int(dut.m_complete.value) == 0b01
    assert await reserve(dut, 1, 2, 1, total=3) == 0
    assert int(dut.m_watermarks.value) == 3
    assert int(dut.m_complete.value) == 0b01
    assert await reserve(dut, 1, 0, 2, total=3) == 0
    assert int(dut.m_watermarks.value) == (3 << 32) | 3
    assert int(dut.m_complete.value) == 0b11
    assert await reserve(dut, 0, 0, 1, total=4) == 1
    assert await reserve(dut, 0, 0, 1, total=3, last=True) == 1
    assert int(dut.m_complete.value) == 0b11


@cocotb.test()
async def long_vector_advances_bounded_window_without_full_vector_bitmap(dut: Any) -> None:
    await initialize(dut)
    for first in range(0, 4096, 350):
        count = min(350, 4096 - first)
        assert await reserve(dut, 0, first, count, total=4096) == 0
        assert int(dut.m_watermarks.value) == first + count
    assert int(dut.m_complete.value) == 0b01
    assert await reserve(dut, 0, 0, 350, total=4096, last=False) == 2
    assert int(dut.m_watermarks.value) == 4096


@cocotb.test()
async def interval_credit_exhaustion_preserves_holes_and_recovery(dut: Any) -> None:
    await initialize(dut)
    for first in range(2, 34, 2):
        assert await reserve(dut, 0, first, 1, total=64) == 0
    assert await reserve(dut, 0, 34, 1, total=64) == 3
    assert int(dut.m_watermarks.value) == 0
    assert await reserve(dut, 0, 0, 2, total=64) == 0
    assert int(dut.m_watermarks.value) == 3
    assert await reserve(dut, 0, 3, 1, total=64) == 0
    assert int(dut.m_watermarks.value) == 5
    assert await reserve(dut, 0, 34, 1, total=64) == 0


@cocotb.test()
async def intervals_that_touch_are_admitted_and_overlapping_ones_refused(dut: Any) -> None:
    await initialize(dut)
    assert await reserve(dut, 0, 8, 8) == 0
    # Directly above and directly below a stored interval.
    assert await reserve(dut, 0, 16, 8) == 0
    assert await reserve(dut, 0, 4, 4) == 0
    # Inside a stored interval, across the end of one, across the start of one.
    assert await reserve(dut, 0, 12, 2) == 2
    assert await reserve(dut, 0, 23, 2) == 2
    assert await reserve(dut, 0, 3, 2) == 2
    assert int(dut.m_watermarks.value) & 0xFFFFFFFF == 0
    # The interval at the watermark releases the three stored ones.
    assert await reserve(dut, 0, 0, 4) == 0
    assert int(dut.m_watermarks.value) & 0xFFFFFFFF == 24
    assert await reserve(dut, 0, 23, 2) == 2
    assert await reserve(dut, 0, 24, 2) == 0
