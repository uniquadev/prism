"""Final native RNE is checked against the independent rational-number oracle."""

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
    decode_native,
    encode_kulisch,
    round_native,
)

WIDTH = 320
NATIVE = (
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
    dut.s_output_format.value = 4
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def check(
    dut: Any,
    value: ExactValue,
    output_format: ConcreteFormat,
    *,
    narrow_bits: int | None = None,
) -> None:
    expected_error = False
    try:
        expected = round_native(value, output_format)
    except ValueError:
        expected = 0
        expected_error = True
    encoded = encode_kulisch(value, WIDTH) if narrow_bits is None else b""
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    dut.s_mode_wide.value = int(narrow_bits is None)
    dut.s_fp32_bits.value = 0 if narrow_bits is None else narrow_bits
    dut.s_kulisch_tag.value = encoded[0] if encoded else 0
    dut.s_kulisch_integer.value = (
        int.from_bytes(encoded[1:], "little", signed=False) if encoded else 0
    )
    dut.s_output_format.value = int(output_format)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    # What stands at the inputs after the value belongs to no value.
    dut.s_mode_wide.value = int(narrow_bits is not None)
    dut.s_fp32_bits.value = 0xC1200000
    dut.s_kulisch_tag.value = 1
    dut.s_kulisch_integer.value = (1 << (WIDTH - 2)) + 12345
    dut.s_output_format.value = int(ConcreteFormat.FP16)
    for _ in range(8):
        await ReadOnly()
        if int(dut.m_valid.value):
            break
        await FallingEdge(dut.clk)
    else:
        raise AssertionError("exact final rounder did not produce a result")
    assert int(dut.m_format.value) == int(output_format)
    assert bool(int(dut.m_error.value)) == expected_error
    if not expected_error:
        assert int(dut.m_bits.value) == expected, (
            value,
            output_format,
            hex(int(dut.m_bits.value)),
            hex(expected),
        )


@cocotb.test()
async def exact_ties_subnormals_overflow_and_special_states(dut: Any) -> None:
    await initialize(dut)
    finite_values = (
        Fraction(1) + Fraction(1, 1 << 11),
        Fraction(1) + Fraction(3, 1 << 11),
        Fraction(1) + Fraction(1, 1 << 24),
        Fraction(1, 1 << 24),
        Fraction(1, 1 << 25),
        Fraction(1, 1 << 133),
        Fraction(1, 1 << 149),
        Fraction(65520),
        Fraction(-128),
        Fraction(-129),
        Fraction(127, 2),
        # The significand carries: into the next exponent, out of the range
        # of the format, and from the largest subnormal to the smallest
        # normal value.
        Fraction(2) - Fraction(1, 1 << 25),
        Fraction(-4) + Fraction(1, 1 << 12),
        Fraction(2**128 - 2**103),
        Fraction(2**128 - 2**119),
        Fraction(1, 1 << 14) - Fraction(1, 1 << 26),
        Fraction(1, 1 << 126) - Fraction(1, 1 << 140),
        Fraction(1, 1 << 126) - Fraction(1, 1 << 149),
        # The lowest normal exponent, with a fraction.
        Fraction(3, 1 << 127),
        Fraction(-3, 1 << 15),
    )
    for rational in finite_values:
        value = ExactValue("finite", rational < 0, rational)
        for output_format in NATIVE:
            await check(dut, value, output_format)
    for value in (
        ExactValue("nan", False),
        ExactValue("infinity", False),
        ExactValue("infinity", True),
        ExactValue("zero", False, Fraction(0)),
        ExactValue("zero", True, Fraction(0)),
    ):
        for output_format in NATIVE:
            await check(dut, value, output_format)


@cocotb.test()
async def seeded_exact_values_and_narrow_fp32_states(dut: Any) -> None:
    await initialize(dut)
    generator = random.Random(0xC0A7E)
    for _ in range(80):
        exponent = generator.randrange(0, 278)
        integer = (1 << exponent) + generator.randrange(0, 1 << min(exponent, 20))
        if generator.randrange(2):
            integer = -integer
        value = ExactValue("finite", integer < 0, Fraction(integer, 1 << 149))
        await check(dut, value, generator.choice(NATIVE))
    for bits in (0, 0x80000000, 1, 0x3F800000, 0x7F800000, 0x7FC00000):
        value = decode_native(bits, ConcreteFormat.FP32)
        for output_format in NATIVE:
            await check(dut, value, output_format, narrow_bits=bits)
