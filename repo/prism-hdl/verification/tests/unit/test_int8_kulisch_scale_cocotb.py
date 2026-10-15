"""INT8 deposits use the same fixed-point scale as floating inputs."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.triggers import Timer
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import decode_native


@cocotb.test()
async def all_int8_deposits_match_exact_bits(dut: Any) -> None:
    for bits in range(256):
        dut.input_bits.value = bits
        await Timer(1, unit="ps")
        decoded = decode_native(bits, ConcreteFormat.INT8)
        assert decoded.value is not None
        expected = int(decoded.value) << 149
        assert int(dut.deposit.value) == expected & ((1 << 279) - 1)
        assert int(dut.finite.value) == 1
        assert int(dut.zero.value) == int(decoded.kind == "zero")
        assert int(dut.overflow.value) == 0
