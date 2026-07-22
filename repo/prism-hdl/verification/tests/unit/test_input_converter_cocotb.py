from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import WireFormat


def pack(values):
    result = 0
    for lane, value in enumerate(values):
        result |= value << (lane * 32)
    return result


@cocotb.test()
async def every_input_format_uses_the_canonical_scalar_codec(dut):
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    vectors = (
        (
            WireFormat.INT8,
            [0x00, 0x01, 0x7F, 0x80],
            [0x00000000, 0x3F800000, 0x42FE0000, 0xC3000000],
        ),
        (
            WireFormat.FP16,
            [0x3C00, 0xC000, 0x7E01, 0x0001],
            [0x3F800000, 0xC0000000, 0x7FC00000, 0x33800000],
        ),
        (
            WireFormat.BF16,
            [0x3F80, 0xC000, 0x7FC1, 0x0001],
            [0x3F800000, 0xC0000000, 0x7FC00000, 0x00010000],
        ),
        (
            WireFormat.FP32,
            [0x3F800000, 0xC0000000, 0x7FA12345, 0x00000001],
            [0x3F800000, 0xC0000000, 0x7FC00000, 0x00000001],
        ),
    )
    for wire_format, encoded, expected in vectors:
        while not int(dut.s_ready.value):
            await RisingEdge(dut.clk)
        dut.s_element_bits.value = pack(encoded)
        dut.s_element_keep.value = 0xF
        dut.s_format.value = int(wire_format)
        dut.s_valid.value = 1
        await RisingEdge(dut.clk)
        await Timer(1, unit="ps")
        dut.s_valid.value = 0
        assert int(dut.m_valid.value)
        assert int(dut.m_fp32_bits.value) == pack(expected)
        assert int(dut.m_element_keep.value) == 0xF
        assert not int(dut.m_format_error.value)
        held = int(dut.m_fp32_bits.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ps")
        assert int(dut.m_valid.value) and int(dut.m_fp32_bits.value) == held
        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        await Timer(1, unit="ps")
        dut.m_ready.value = 0
