"""All native Kulisch deposits use the protocol's common 2^-149 scale."""

from __future__ import annotations

import random
from typing import Any

import cocotb
from cocotb.triggers import Timer
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import decode_native

SCALE = 1 << 149


def expected_integer(bits: int, fmt: ConcreteFormat) -> tuple[int, str, bool]:
    value = decode_native(bits, fmt)
    if value.kind in {"finite", "zero"}:
        assert value.value is not None
        integer = value.value * SCALE
        assert integer.denominator == 1
        return int(integer), value.kind, value.sign
    return 0, value.kind, value.sign


@cocotb.test()
async def floating_deposits_match_exact_bits(dut: Any) -> None:
    rng = random.Random(0x505249534D)
    patterns = {
        ConcreteFormat.FP16: [0, 1, 0x8001, 0x3C00, 0x7BFF, 0x7C00, 0xFC00, 0x7E01],
        ConcreteFormat.BF16: [0, 1, 0x8001, 0x3F80, 0x7F7F, 0x7F80, 0xFF80, 0x7FC1],
        ConcreteFormat.FP32: [
            0,
            1,
            0x80000001,
            0x3F800000,
            0x7F7FFFFF,
            0x7F800000,
            0xFF800000,
            0x7FC00001,
        ],
    }
    for fmt, edge_cases in patterns.items():
        width = 16 if fmt != ConcreteFormat.FP32 else 32
        for bits in (*edge_cases, *(rng.getrandbits(width) for _ in range(100))):
            dut.input_bits.value = bits
            dut.input_format.value = int(fmt)
            await Timer(1, unit="ps")
            expected, kind, sign = expected_integer(bits, fmt)
            assert int(dut.deposit.value) == expected & ((1 << 279) - 1)
            assert int(dut.finite.value) == int(kind in {"finite", "zero"})
            assert int(dut.zero.value) == int(kind == "zero")
            assert int(dut.zero_sign.value) == int(kind == "zero" and sign)
            assert int(dut.nan.value) == int(kind == "nan")
            assert int(dut.positive_infinity.value) == int(kind == "infinity" and not sign)
            assert int(dut.negative_infinity.value) == int(kind == "infinity" and sign)
            assert int(dut.overflow.value) == 0
            assert int(dut.format_error.value) == 0
