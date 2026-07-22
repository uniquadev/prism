from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import WireFormat


@cocotb.test()
async def selects_smallest_width_and_reports_fallback(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    cases = (
        (WireFormat.INT8, 1, 8, 64, 0, True),
        (WireFormat.BF16, 1, 262, 288, 1, True),
        (WireFormat.FP32, 1024, 288, 288, 1, True),
        (WireFormat.FP32, 1025, 289, 288, 1, False),
        (WireFormat.FP32, 2048, 289, 288, 1, False),
    )
    for wire_format, terms, required, selected, index, sufficient in cases:
        dut.s_input_format.value = int(wire_format)
        dut.s_maximum_terms.value = terms
        dut.s_valid.value = 1
        await Timer(1, unit="ps")
        assert int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        dut.s_valid.value = 0
        await Timer(1, unit="ps")
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_required_width.value) == required
        assert int(dut.m_selected_width.value) == selected
        assert int(dut.m_width_index.value) == index
        assert bool(dut.m_sufficient.value) is sufficient
        assert bool(dut.m_accumulation_inexact.value) is (not sufficient)

        held = (
            int(dut.m_required_width.value),
            int(dut.m_selected_width.value),
            int(dut.m_width_index.value),
            int(dut.m_sufficient.value),
            int(dut.m_accumulation_inexact.value),
        )
        await RisingEdge(dut.clk)
        await Timer(1, unit="ps")
        assert held == (
            int(dut.m_required_width.value),
            int(dut.m_selected_width.value),
            int(dut.m_width_index.value),
            int(dut.m_sufficient.value),
            int(dut.m_accumulation_inexact.value),
        )
        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        dut.m_ready.value = 0
