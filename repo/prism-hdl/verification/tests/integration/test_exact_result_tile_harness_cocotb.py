"""Two exact 4096-element inputs feed one tile/cycle final native extraction."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


@cocotb.test()
async def exact_accumulation_and_fp32_rounding_remain_parallel(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_slot.value = 0
    dut.s_first_element.value = 0
    dut.s_format.value = 4
    dut.s_element_bits.value = 0
    dut.s_element_keep.value = 0
    dut.s_valid.value = 0
    dut.s_result_slot.value = 0
    dut.s_result_read_valid.value = 0
    dut.s_output_format.value = 4
    dut.m_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    one_tile = int.from_bytes((0x3F800000).to_bytes(4, "little") * 16, "little")
    negative_tile = int.from_bytes((0xBF800000).to_bytes(4, "little") * 16, "little")
    sent = 0
    issue_cycles: list[int] = []
    for cycle in range(540):
        await FallingEdge(dut.clk)
        dut.s_valid.value = int(sent < 512)
        dut.s_slot.value = min(sent % 256, 255)
        dut.s_first_element.value = min(sent % 256, 255) * 16
        dut.s_element_bits.value = one_tile if sent < 256 else negative_tile
        dut.s_element_keep.value = 0xFFFF
        await ReadOnly()
        accepted = sent < 512 and int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        if accepted:
            issue_cycles.append(cycle)
            sent += 1
        if sent == 512:
            break
    assert sent == 512
    assert issue_cycles[-1] - issue_cycles[0] + 1 == 512
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    # The bank grants a read once its stages are empty; the first request
    # below waits for that.
    for _ in range(4):
        await FallingEdge(dut.clk)

    requested = 0
    results: list[tuple[int, int]] = []
    read_cycles: list[int] = []
    result_cycles: list[int] = []
    for cycle in range(280):
        await FallingEdge(dut.clk)
        dut.s_result_read_valid.value = int(requested < 256)
        dut.s_result_slot.value = min(requested, 255)
        await ReadOnly()
        accepted = requested < 256 and int(dut.s_result_read_ready.value) == 1
        if int(dut.m_valid.value) and int(dut.m_ready.value):
            assert int(dut.m_error.value) == 0
            assert int(dut.m_element_keep.value) == 0xFFFF
            results.append((int(dut.m_first_element.value), int(dut.m_element_bits.value)))
            result_cycles.append(cycle)
        await RisingEdge(dut.clk)
        if accepted:
            read_cycles.append(cycle)
            requested += 1
        if len(results) == 256:
            break
    assert requested == 256 and len(results) == 256
    assert read_cycles[-1] - read_cycles[0] + 1 == 256
    assert result_cycles[-1] - result_cycles[0] + 1 == 256
    assert results == [(first, 0) for first in range(0, 4096, 16)]
    dut._log.info("exact-to-FP32 result tiles sustain 128.00 Gb/s numeric payload")


@cocotb.test()
async def reads_stop_while_the_rounding_keeps_places_for_tiles_on_their_way(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_slot.value = 0
    dut.s_first_element.value = 0
    dut.s_format.value = 4
    dut.s_element_bits.value = 0
    dut.s_element_keep.value = 0
    dut.s_valid.value = 0
    dut.s_result_slot.value = 0
    dut.s_result_read_valid.value = 0
    dut.s_output_format.value = 4
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    # Nothing was accumulated: every result is an empty tile. The consumer
    # takes nothing, so the reads must stop while places are left for the
    # results that were already asked for.
    dut.m_ready.value = 0
    granted = 0
    for _ in range(120):
        await FallingEdge(dut.clk)
        dut.s_result_read_valid.value = 1
        dut.s_result_slot.value = granted % 256
        await ReadOnly()
        taken = int(dut.s_result_read_ready.value) == 1
        await RisingEdge(dut.clk)
        granted += int(taken)
    await FallingEdge(dut.clk)
    dut.s_result_read_valid.value = 0
    assert 16 <= granted <= 32, granted
    dut.m_ready.value = 1
    firsts: list[int] = []
    for _ in range(80):
        await ReadOnly()
        if int(dut.m_valid.value):
            firsts.append(int(dut.m_first_element.value))
        await FallingEdge(dut.clk)
    assert firsts == [index * 16 for index in range(granted)]
