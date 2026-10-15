"""Auto wire selection checked against the independent exact CCL oracle."""

from __future__ import annotations

import random
from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import (
    ExactValue,
    decode_kulisch,
    decode_native,
    encode_kulisch,
    is_lossless,
)

ORDER = (
    ConcreteFormat.INT8,
    ConcreteFormat.FP16,
    ConcreteFormat.BF16,
    ConcreteFormat.FP32,
)


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.s_mode_wide.value = 0
    dut.s_fp32_bits.value = 0
    dut.s_kulisch_tag.value = 0
    dut.s_kulisch_integer.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def result(dut: Any, limit: int = 16) -> None:
    """Wait for the selection: the classifier takes several registered steps."""
    for _ in range(limit):
        await ReadOnly()
        if int(dut.m_valid.value):
            return
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    raise AssertionError("classifier produced no selection")


async def select(
    dut: Any, value: ExactValue, *, native_bits: int | None = None
) -> tuple[ConcreteFormat, ExactValue]:
    width = len(dut.s_kulisch_integer)
    mask = (1 << width) - 1
    wire = encode_kulisch(value, width)
    await FallingEdge(dut.clk)
    dut.s_mode_wide.value = int(native_bits is None)
    dut.s_fp32_bits.value = 0 if native_bits is None else native_bits
    dut.s_kulisch_tag.value = wire[0]
    dut.s_kulisch_integer.value = int.from_bytes(wire[1:], "little") & mask
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    await result(dut)
    assert int(dut.m_error.value) == 0
    fmt = ConcreteFormat(int(dut.m_format.value))
    if fmt == ConcreteFormat.KULISCH:
        raw_integer = int(dut.m_kulisch_integer.value)
        signed_integer = (
            raw_integer - (1 << width) if raw_integer & (1 << (width - 1)) else raw_integer
        )
        got_wire = bytes([int(dut.m_kulisch_tag.value)]) + signed_integer.to_bytes(
            (width + 7) // 8, "little", signed=True
        )
        decoded = decode_kulisch(got_wire, width)
    else:
        decoded = decode_native(int(dut.m_native_bits.value), fmt)
    assert decoded == value, (value, fmt, decoded)
    expected = next((candidate for candidate in ORDER if is_lossless(value, candidate)), None)
    assert fmt == (expected or ConcreteFormat.KULISCH), (value, fmt, expected)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    return fmt, decoded


@cocotb.test()
async def exact_native_and_special_selection(dut: Any) -> None:
    await initialize(dut)
    cases = (
        (ExactValue("finite", False, Fraction(7)), ConcreteFormat.INT8),
        (ExactValue("finite", True, Fraction(-128)), ConcreteFormat.INT8),
        (ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 11)), ConcreteFormat.FP32),
        (ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24)), ConcreteFormat.KULISCH),
        (ExactValue("finite", False, Fraction(1, 1 << 133)), ConcreteFormat.BF16),
        (ExactValue("finite", False, Fraction(1, 1 << 149)), ConcreteFormat.FP32),
        (ExactValue("zero", False, Fraction(0)), ConcreteFormat.INT8),
        (ExactValue("zero", True, Fraction(0)), ConcreteFormat.FP16),
        (ExactValue("infinity", True), ConcreteFormat.FP16),
        (ExactValue("nan", False), ConcreteFormat.FP16),
    )
    for value, expected in cases:
        fmt, _ = await select(dut, value)
        assert fmt == expected, (value, fmt, expected)
    await select(dut, decode_native(0x3F800000, ConcreteFormat.FP32), native_bits=0x3F800000)
    await select(dut, decode_native(0x80000000, ConcreteFormat.FP32), native_bits=0x80000000)


@cocotb.test()
async def seeded_values_match_exact_oracle(dut: Any) -> None:
    await initialize(dut)
    rng = random.Random(0xA170)
    for _ in range(120):
        coefficient = rng.randint(-(1 << 26), 1 << 26) or 1
        exponent = rng.randint(-149, 90)
        scale = Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)
        value = Fraction(coefficient) * scale
        exact = ExactValue("finite", value < 0, value)
        await select(dut, exact)


@cocotb.test()
async def native_range_and_subnormal_boundaries_match_exact_oracle(dut: Any) -> None:
    await initialize(dut)
    for high_bit in (0, 15, 16, 22, 23, 24, 124, 125, 134, 135, 136, 163, 164, 165, 275, 276, 277):
        for low_bit in (high_bit, max(0, high_bit - 7), 0):
            integer = (1 << high_bit) | (1 << low_bit)
            for sign in (-1, 1):
                value = Fraction(sign * integer, 1 << 149)
                await select(dut, ExactValue("finite", value < 0, value))


@cocotb.test()
async def invalid_kulisch_is_rejected_without_a_false_format(dut: Any) -> None:
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.s_mode_wide.value = 1
    dut.s_kulisch_tag.value = 0
    dut.s_kulisch_integer.value = 0
    dut.s_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    await result(dut)
    assert int(dut.m_error.value) == 1


@cocotb.test()
async def every_significant_bit_and_precision_boundary(dut: Any) -> None:
    """Exercise the entire accumulator, including non-native high bits."""
    await initialize(dut)
    width = len(dut.s_kulisch_integer)
    for high in range(width - 1):
        for distance in (0, 7, 8, 10, 11, 23, 24):
            low = max(0, high - distance)
            integer = (1 << high) | (1 << low)
            for sign in (-1, 1):
                value = Fraction(sign * integer, 1 << 149)
                await select(dut, ExactValue("finite", value < 0, value))
    value = Fraction(-(1 << (width - 1)), 1 << 149)
    await select(dut, ExactValue("finite", True, value))
