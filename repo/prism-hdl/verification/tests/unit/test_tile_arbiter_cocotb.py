from __future__ import annotations

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def round_robin_is_fair_and_stable_under_backpressure(dut) -> None:
    random.seed(0xA11B17E2)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for port in range(2):
        dut.s_meta[port].value = 0
        dut.s_element_keep[port].value = 0xF
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    counters = [0, 0]
    observed_ports = []
    held = None
    for _cycle in range(1000):
        dut.s_valid.value = 0b11
        for port in range(2):
            dut.s_element_bits[port].value = (port << 31) | counters[port]
        ready = random.randrange(4) != 0
        dut.m_ready.value = ready
        await Timer(1, unit="ps")
        if int(dut.m_valid.value):
            value = int(dut.m_element_bits.value)
            if not ready:
                if held is not None:
                    assert value == held
                held = value
            else:
                held = None
                port = (value >> 31) & 1
                observed_ports.append(port)
        accepted = [bool((int(dut.s_ready.value) >> port) & 1) for port in range(2)]
        await RisingEdge(dut.clk)
        for port in range(2):
            counters[port] += int(accepted[port])
        if len(observed_ports) == 100:
            break

    assert observed_ports == [index % 2 for index in range(100)]
    assert counters == [50, 50]
