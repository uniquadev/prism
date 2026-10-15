"""Completed FP32 tiles can be read eight at a time without reordering."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


@cocotb.test()
async def wide_read_waits_for_all_slots_and_preserves_a_stalled_result(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_release.value = 0
    dut.s_total_elements.value = 129
    dut.s_slot.value = 0
    dut.s_present.value = 0
    dut.s_bits.value = 0
    dut.s_error.value = 0
    dut.s_valid.value = 0
    dut.s_result_slot.value = 0
    dut.s_wide_read.value = 1
    dut.s_result_read_valid.value = 0
    dut.m_result_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    for slot in range(8):
        await FallingEdge(dut.clk)
        dut.s_slot.value = slot
        dut.s_present.value = 0xFFFF
        dut.s_bits.value = 0x3F800000 + slot
        dut.s_error.value = int(slot == 3)
        dut.s_valid.value = 1
        dut.s_result_read_valid.value = 1
        dut.s_result_slot.value = slot // 8
        await ReadOnly()
        assert int(dut.s_ready.value) == 1
        assert int(dut.s_result_read_ready.value) == 0
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.s_slot.value = 8
    dut.s_present.value = 1
    dut.s_bits.value = 0x40400000
    dut.s_error.value = 0
    dut.s_result_slot.value = 0
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    assert int(dut.s_result_read_ready.value) == 1
    await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    dut.s_result_read_valid.value = 0
    dut.m_result_ready.value = 0
    for _ in range(3):
        await ReadOnly()
        assert int(dut.m_all_written.value) == 1
        assert int(dut.m_result_valid.value) == 1
        assert int(dut.m_result_slot.value) == 0
        assert int(dut.m_result_present.value) == (1 << 128) - 1
        assert int(dut.m_result_error.value) == 1
        bits = int(dut.m_result_bits.value)
        for stripe in range(8):
            assert (bits >> (stripe * 512)) & 0xFFFFFFFF == 0x3F800000 + stripe
        await FallingEdge(dut.clk)

    dut.m_result_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_result_slot.value = 1
    dut.s_result_read_valid.value = 1
    await ReadOnly()
    assert int(dut.s_result_read_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_result_read_valid.value = 0
    await ReadOnly()
    assert int(dut.m_result_valid.value) == 1
    assert int(dut.m_result_slot.value) == 1
    assert int(dut.m_result_present.value) == 1
    assert int(dut.m_result_bits.value) & 0xFFFFFFFF == 0x40400000
    assert int(dut.m_result_error.value) == 0
