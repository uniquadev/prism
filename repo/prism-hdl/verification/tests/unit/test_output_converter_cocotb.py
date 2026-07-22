from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import WireFormat


def pack(values: list[int]) -> int:
    return sum(value << (32 * lane) for lane, value in enumerate(values))


def unpack(raw: int, width: int, lanes: int = 4) -> list[int]:
    mask = (1 << width) - 1
    return [(raw >> (32 * lane)) & mask for lane in range(lanes)]


async def reset(dut) -> None:
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1


async def convert(dut, values: list[int], wire_format: int) -> None:
    dut.s_fp32_bits.value = pack(values)
    dut.s_element_keep.value = 0xF
    dut.s_format.value = wire_format
    dut.s_valid.value = 1
    await Timer(1, unit="ps")
    assert int(dut.s_ready.value)
    await RisingEdge(dut.clk)
    dut.s_valid.value = 0
    await Timer(1, unit="ps")
    assert int(dut.m_valid.value)


async def consume(dut) -> None:
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    dut.m_ready.value = 0
    await Timer(1, unit="ps")
    assert not int(dut.m_valid.value)


@cocotb.test()
async def output_formats_report_rounding_status_and_hold_under_stall(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)

    await convert(dut, [0x3F800000, 0x7F7FFFFF, 0x00000001, 0x7FC12345], WireFormat.FP16)
    assert unpack(int(dut.m_element_bits.value), 16) == [0x3C00, 0x7C00, 0x0000, 0x7E00]
    assert int(dut.m_overflow.value) == 0b0010
    assert int(dut.m_underflow.value) == 0b0100
    assert int(dut.m_inexact.value) == 0b0110
    assert int(dut.m_canonical_nan.value) == 0b1000
    held = tuple(
        int(signal.value)
        for signal in (
            dut.m_element_bits,
            dut.m_element_keep,
            dut.m_overflow,
            dut.m_underflow,
            dut.m_inexact,
            dut.m_canonical_nan,
            dut.m_format_error,
        )
    )
    for _ in range(3):
        await RisingEdge(dut.clk)
        assert held == tuple(
            int(signal.value)
            for signal in (
                dut.m_element_bits,
                dut.m_element_keep,
                dut.m_overflow,
                dut.m_underflow,
                dut.m_inexact,
                dut.m_canonical_nan,
                dut.m_format_error,
            )
        )
    await consume(dut)

    await convert(dut, [0x3F800000, 0xC0000000, 0x7F800000, 0x7FC12345], WireFormat.BF16)
    assert unpack(int(dut.m_element_bits.value), 16) == [0x3F80, 0xC000, 0x7F80, 0x7FC0]
    assert int(dut.m_overflow.value) == 0
    assert int(dut.m_underflow.value) == 0
    assert int(dut.m_inexact.value) == 0
    assert int(dut.m_canonical_nan.value) == 0b1000
    await consume(dut)

    await convert(dut, [0x3F800000, 0xC0000000, 0x7F800000, 0x7FC12345], WireFormat.FP32)
    assert unpack(int(dut.m_element_bits.value), 32) == [
        0x3F800000,
        0xC0000000,
        0x7F800000,
        0x7FC00000,
    ]
    assert int(dut.m_canonical_nan.value) == 0b1000
    await consume(dut)

    await convert(dut, [0x3F800000] * 4, int(WireFormat.INVALID))
    assert int(dut.m_format_error.value)
    assert int(dut.m_element_bits.value) == 0
    await consume(dut)
