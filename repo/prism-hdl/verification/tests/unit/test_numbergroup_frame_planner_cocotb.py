"""The frame planner assigns tiles to frames and refuses a tile that fails its checks."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

INT8 = 1


async def initialize(dut: Any, *, start_clock: bool = True) -> None:
    if start_clock:
        cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = 0
    dut.s_packet_id.value = 5
    dut.s_total_elements.value = 1000
    dut.s_first_element.value = 0
    dut.s_mtu.value = 576
    dut.s_kulisch_bits.value = 320
    dut.s_count.value = 0
    dut.s_bytes.value = 0
    dut.s_groups.value = 1
    dut.s_first_frame_tiles.value = 0
    dut.s_format.value = INT8
    dut.s_uniform.value = 1
    dut.s_padded.value = 0
    dut.s_encoding_valid.value = 1
    dut.s_valid.value = 0
    dut.m_tile_ready.value = 1
    dut.m_patch_ready.value = 1
    dut.m_frame_ready.value = 3
    dut.s_release_valid.value = 0
    dut.s_release_bank.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def watch_plans(dut: Any, plans: list[tuple[int, int, int, int]]) -> None:
    while True:
        await RisingEdge(dut.clk)
        if int(dut.m_tile_valid.value) and int(dut.m_tile_ready.value):
            plans.append(
                (
                    int(dut.m_tile_bank.value),
                    int(dut.m_tile_offset.value),
                    int(dut.m_tile_bytes.value),
                    int(dut.m_tile_strip_descriptor.value),
                )
            )


async def offer(dut: Any, first: int, count: int, size: int) -> None:
    """Offer one uniform INT8 tile until the planner takes it."""
    await FallingEdge(dut.clk)
    dut.s_first_element.value = first
    dut.s_count.value = count
    dut.s_bytes.value = size
    dut.s_valid.value = 1
    for _ in range(20):
        await ReadOnly()
        taken = int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        if taken:
            break
        await FallingEdge(dut.clk)
    else:
        raise AssertionError("the planner did not take the tile")
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0


@cocotb.test()
async def tiles_of_one_group_are_planned_one_behind_the_other(dut: Any) -> None:
    await initialize(dut)
    plans: list[tuple[int, int, int, int]] = []
    watcher = cocotb.start_soon(watch_plans(dut, plans))
    await offer(dut, 0, 64, 68)
    await offer(dut, 64, 64, 68)
    await offer(dut, 128, 16, 20)
    for _ in range(4):
        await RisingEdge(dut.clk)
    watcher.cancel()
    # The second and third tile extend the group of the first: they leave
    # their descriptor behind and follow it without a gap.
    assert plans == [(0, 0, 68, 0), (0, 68, 64, 1), (0, 132, 16, 1)]
    assert int(dut.m_fault.value) == 0
    assert int(dut.m_bank_busy.value) == 0b01


@cocotb.test()
async def refused_tile_raises_the_fault_gets_no_plan_and_opens_no_bank(dut: Any) -> None:
    await initialize(dut)
    plans: list[tuple[int, int, int, int]] = []
    watcher = cocotb.start_soon(watch_plans(dut, plans))
    # The first tile of the vector does not begin at element zero.
    await offer(dut, 16, 64, 68)
    assert int(dut.m_fault.value) == 1
    assert int(dut.s_ready.value) == 0
    for _ in range(6):
        await RisingEdge(dut.clk)
    assert plans == []
    assert int(dut.m_bank_busy.value) == 0
    # No bank is busy, so a reset takes the planner back to its start.
    await FallingEdge(dut.clk)
    dut.s_reset.value = 1
    await FallingEdge(dut.clk)
    dut.s_reset.value = 0
    assert int(dut.m_fault.value) == 0
    await offer(dut, 0, 64, 68)
    # A tile that does not continue the vector, behind a good one.
    await offer(dut, 200, 64, 68)
    assert int(dut.m_fault.value) == 1
    for _ in range(6):
        await RisingEdge(dut.clk)
    watcher.cancel()
    assert plans == [(0, 0, 68, 0)]
    assert int(dut.m_bank_busy.value) == 0b01
