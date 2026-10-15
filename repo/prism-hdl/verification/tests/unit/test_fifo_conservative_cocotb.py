from __future__ import annotations

from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def conservative_full_boundary_recovers_then_sustains_one_item_per_cycle(dut):
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    reference = deque()
    capacity = 0
    for value in range(64):
        dut.s_data.value = value
        dut.s_valid.value = 1
        await Timer(1, unit="ps")
        if not int(dut.s_ready.value):
            break
        capacity += 1
        reference.append(value)
        await RisingEdge(dut.clk)
    assert capacity >= 2

    dut.m_ready.value = 1
    dut.s_data.value = capacity
    await Timer(1, unit="ps")
    assert int(dut.occupancy.value) == capacity
    assert int(dut.s_ready.value) == 0
    assert int(dut.m_data.value) == reference.popleft()
    await RisingEdge(dut.clk)

    received = [0]
    for value in range(capacity, capacity + 16):
        dut.s_data.value = value
        await Timer(1, unit="ps")
        assert int(dut.s_ready.value) == 1
        assert int(dut.m_valid.value) == 1
        received.append(int(dut.m_data.value))
        reference.popleft()
        reference.append(value)
        await RisingEdge(dut.clk)

    dut.s_valid.value = 0
    while reference:
        await Timer(1, unit="ps")
        assert int(dut.m_valid.value) == 1
        value = int(dut.m_data.value)
        assert value == reference.popleft()
        received.append(value)
        await RisingEdge(dut.clk)

    assert received == list(range(capacity + 16))
