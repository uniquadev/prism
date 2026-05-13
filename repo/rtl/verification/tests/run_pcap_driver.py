
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Lorenzo Cipolletti

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


PCAP_OUT = "traces/passthrough_out.pcap"


async def reset_dut(dut, cycles=10):
    dut.eos.value = 0
    dut.rst_n.value = 0

    for _ in range(cycles):
        await RisingEdge(dut.clk)

    dut.rst_n.value = 1

    for _ in range(2):
        await RisingEdge(dut.clk)


async def close_pcap_dumper(dut):
    dut.eos.value = 1

    for _ in range(5):
        await RisingEdge(dut.clk)

    dut.eos.value = 0

    for _ in range(20):
        await RisingEdge(dut.clk)


@cocotb.test()
async def run_custom_pcap_driver(dut):
    cocotb.start_soon(Clock(dut.clk, 3104, units="ps").start())

    await reset_dut(dut)

    for _ in range(100000):
        await RisingEdge(dut.clk)

        if int(dut.pcapfinished.value) == 1:
            break
    else:
        await close_pcap_dumper(dut)
        raise AssertionError("Timed out waiting for pcapfinished")

    for _ in range(10000):
        await RisingEdge(dut.clk)

    await close_pcap_dumper(dut)

    await Timer(1, units="ns")

    assert os.path.exists(PCAP_OUT), f"Missing output PCAP: {PCAP_OUT}"
