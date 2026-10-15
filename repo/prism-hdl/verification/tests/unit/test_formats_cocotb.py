from __future__ import annotations

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native


@cocotb.test()
async def fp32_add_matches_reference_and_holds_under_stall(dut):
    seed = 7
    random.seed(seed)
    dut._log.info("deterministic_seed=%d", seed)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    vectors = [
        (0x3F800000, 0x40000000),
        (0x7F800000, 0xFF800000),
        (0x80000000, 0x80000000),
        (0x00000001, 0x00000001),
        (0x7FC01234, 0x3F800000),
    ]
    vectors += [(random.getrandbits(32), random.getrandbits(32)) for _ in range(100)]
    for left, right in vectors:
        while not int(dut.s_ready.value):
            await RisingEdge(dut.clk)
        dut.s_left.value = left
        dut.s_right.value = right
        dut.s_valid.value = 1
        await RisingEdge(dut.clk)
        dut.s_valid.value = 0
        expected = round_native(
            combine_exact(
                (
                    decode_native(left, ConcreteFormat.FP32),
                    decode_native(right, ConcreteFormat.FP32),
                )
            ),
            ConcreteFormat.FP32,
        )
        dut.m_ready.value = 0
        while not int(dut.m_valid.value):
            await RisingEdge(dut.clk)
        for _ in range(random.randrange(0, 4)):
            await RisingEdge(dut.clk)
            assert int(dut.m_valid.value)
            assert int(dut.m_result.value) == expected
        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        dut.m_ready.value = 0
