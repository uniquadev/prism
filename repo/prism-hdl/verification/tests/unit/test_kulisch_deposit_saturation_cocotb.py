from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import WireFormat


@cocotb.test()
async def narrow_deposit_converter_saturates_both_signs(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    values = [0x7F7FFFFF, 0xFF7FFFFF, 0x00000001, 0x80000001]
    dut.s_element_bits.value = sum(value << (32 * lane) for lane, value in enumerate(values))
    dut.s_element_keep.value = 0xF
    dut.s_format.value = int(WireFormat.FP32)
    dut.s_valid.value = 1
    await RisingEdge(dut.clk)
    dut.s_valid.value = 0
    await Timer(1, unit="ps")

    raw = int(dut.m_deposits.value)
    assert [(raw >> (16 * lane)) & 0xFFFF for lane in range(4)] == [
        0x7FFF,
        0x8000,
        0x0001,
        0xFFFF,
    ]
    assert int(dut.m_overflow.value) == 0b0011
    assert int(dut.m_finite.value) == 0xF
