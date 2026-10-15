"""AXI frame class routing stays fixed across beats and backpressure."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tvalid.value = 0
    dut.m_control_tready.value = 1
    dut.m_data_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


def beat(packet_class: int) -> int:
    return packet_class << (15 * 8)


@cocotb.test()
async def first_beat_decision_survives_stall_and_later_class_bytes(dut: Any) -> None:
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = beat(1)
    dut.s_axis_tkeep.value = (1 << 64) - 1
    dut.s_axis_tlast.value = 0
    dut.s_axis_tvalid.value = 1
    dut.m_control_tready.value = 0
    await Timer(1, unit="ps")
    assert int(dut.m_control_tvalid.value) == 1
    assert int(dut.m_data_tvalid.value) == 0
    assert int(dut.s_axis_tready.value) == 0
    await FallingEdge(dut.clk)
    dut.m_control_tready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = beat(2)
    dut.s_axis_tlast.value = 1
    await Timer(1, unit="ps")
    assert int(dut.m_control_tvalid.value) == 1
    assert int(dut.m_data_tvalid.value) == 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = beat(3)
    await Timer(1, unit="ps")
    assert int(dut.m_data_tvalid.value) == 1
    assert int(dut.m_control_tvalid.value) == 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def unsupported_classes_and_short_first_beats_are_dropped(dut: Any) -> None:
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = beat(4)
    dut.s_axis_tkeep.value = (1 << 60) - 1
    dut.s_axis_tlast.value = 1
    dut.s_axis_tvalid.value = 1
    await Timer(1, unit="ps")
    assert int(dut.m_drop_valid.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = beat(9)
    await Timer(1, unit="ps")
    assert int(dut.m_drop_valid.value) == 1
    assert int(dut.m_control_tvalid.value) == 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = beat(1)
    dut.s_axis_tkeep.value = (1 << 15) - 1
    await Timer(1, unit="ps")
    assert int(dut.m_drop_valid.value) == 1
    assert int(dut.m_control_tvalid.value) == 0
