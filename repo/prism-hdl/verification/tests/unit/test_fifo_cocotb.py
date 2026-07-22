from __future__ import annotations

import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def non_power_of_two_fifo_wraps_with_simultaneous_io(dut):
    seed = 0x50524953
    random.seed(seed)
    dut._log.info("deterministic_seed=%d", seed)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    source = deque(range(500))
    reference = deque()
    received = []
    active = None
    for _ in range(10000):
        if active is None and source and random.randrange(5) != 0:
            active = source.popleft()
        dut.s_valid.value = active is not None
        if active is not None:
            dut.s_data.value = active
        dut.m_ready.value = random.randrange(2)
        await Timer(1, unit="ps")
        push = active is not None and int(dut.s_ready.value)
        pop = int(dut.m_valid.value) and int(dut.m_ready.value)
        pushed_value = active
        popped_value = int(dut.m_data.value) if pop else None
        await RisingEdge(dut.clk)
        await Timer(1, unit="ps")
        if pop:
            expected = reference.popleft()
            assert popped_value == expected
            received.append(popped_value)
        if push:
            reference.append(pushed_value)
            active = None
        assert int(dut.occupancy.value) == len(reference)
        if not source and active is None and not reference:
            break
    assert received == list(range(500))


@cocotb.test()
async def full_fifo_accepts_replacement_without_a_bubble(dut):
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    for value in range(5):
        dut.s_data.value = value
        dut.s_valid.value = 1
        await Timer(1, unit="ps")
        assert int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
    dut.s_valid.value = 0
    await Timer(1, unit="ps")
    assert int(dut.occupancy.value) == 5
    assert int(dut.s_ready.value) == 0

    dut.s_data.value = 5
    dut.s_valid.value = 1
    dut.m_ready.value = 1
    await Timer(1, unit="ps")
    assert int(dut.m_data.value) == 0
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    dut.s_valid.value = 0
    await Timer(1, unit="ps")
    assert int(dut.occupancy.value) == 5

    received = []
    for _ in range(5):
        await Timer(1, unit="ps")
        assert int(dut.m_valid.value) == 1
        received.append(int(dut.m_data.value))
        await RisingEdge(dut.clk)
    assert received == [1, 2, 3, 4, 5]
