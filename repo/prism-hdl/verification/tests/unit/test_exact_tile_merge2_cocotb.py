"""Two port-local exact tiles merge without re-rounding or stale RAM lanes."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.numbers import ExactValue, combine_exact, decode_kulisch, encode_kulisch


def repeated(value: ExactValue) -> tuple[int, int]:
    encoded = encode_kulisch(value, 320)
    return (
        int.from_bytes(encoded[:1] * 16, "little"),
        int.from_bytes(encoded[1:] * 16, "little"),
    )


@cocotb.test()
async def exact_merge_streams_tiles_and_holds_under_backpressure(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_slot.value = 0
    dut.s_present0.value = 0
    dut.s_tags0.value = 0
    dut.s_integers0.value = 0
    dut.s_present1.value = 0
    dut.s_tags1.value = 0
    dut.s_integers1.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    one = ExactValue("finite", False, Fraction(1))
    half_ulp = ExactValue("finite", False, Fraction(1, 1 << 24))
    negative_one = ExactValue("finite", True, Fraction(-1))
    positive_inf = ExactValue("infinity", False, None)
    negative_inf = ExactValue("infinity", True, None)
    negative_zero = ExactValue("zero", True, Fraction(0))
    # The smallest FP32 value lies in the lower half of the accumulator; added
    # to its negative it carries through every bit, from the lower half into
    # the upper one. Two equal values just below the middle carry into it too.
    tiny = ExactValue("finite", False, Fraction(1, 1 << 149))
    negative_tiny = ExactValue("finite", True, Fraction(-1, 1 << 149))
    small = ExactValue("finite", False, Fraction(1, 1 << 50))
    cases = (
        (
            one,
            half_ulp,
            0xFFFF,
            0xFFFF,
            ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24)),
        ),
        (positive_inf, negative_inf, 0xFFFF, 0xFFFF, ExactValue("nan", False, None)),
        (one, negative_one, 0, 0xFFFF, negative_one),
        (negative_zero, negative_zero, 0xFFFF, 0xFFFF, negative_zero),
        (tiny, negative_tiny, 0xFFFF, 0xFFFF, combine_exact((tiny, negative_tiny))),
        (negative_tiny, small, 0xFFFF, 0xFFFF, combine_exact((negative_tiny, small))),
        (small, small, 0xFFFF, 0xFFFF, combine_exact((small, small))),
    )
    sent = 0
    received = 0
    held: tuple[int, int, int, int] | None = None
    for cycle in range(50):
        await FallingEdge(dut.clk)
        dut.m_ready.value = int(cycle % 7 not in (3, 4))
        dut.s_valid.value = int(sent < len(cases))
        if sent < len(cases):
            left, right, present0, present1, _expected = cases[sent]
            tags0, integers0 = repeated(left)
            tags1, integers1 = repeated(right)
            dut.s_slot.value = sent
            dut.s_present0.value = present0
            dut.s_tags0.value = tags0
            dut.s_integers0.value = integers0
            dut.s_present1.value = present1
            dut.s_tags1.value = tags1
            dut.s_integers1.value = integers1
        await ReadOnly()
        take_input = sent < len(cases) and int(dut.s_ready.value)
        valid = int(dut.m_valid.value)
        ready = int(dut.m_ready.value)
        output = (
            int(dut.m_slot.value),
            int(dut.m_present.value),
            int(dut.m_tags.value),
            int(dut.m_integers.value),
        )
        if held is not None:
            assert valid and output == held
        held = output if valid and not ready else None
        if valid and ready:
            assert output[0] == received
            assert output[1] == 0xFFFF
            assert int(dut.m_error.value) == 0
            expected = cases[received][4]
            for lane in range(16):
                actual = decode_kulisch(
                    bytes((output[2] >> (lane * 8) & 0xFF,))
                    + (output[3] >> (lane * 320) & ((1 << 320) - 1)).to_bytes(40, "little"),
                    320,
                )
                assert actual == expected
            received += 1
        await RisingEdge(dut.clk)
        if take_input:
            sent += 1
        if received == len(cases):
            break
    assert sent == received == len(cases)
