"""Narrow, backpressured transfer of canonical Kulisch wire integers."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, decode_native, encode_kulisch


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_global_index.value = 0
    dut.s_format.value = 0x80
    dut.s_byte_index.value = 0
    dut.s_value_byte.value = 0
    dut.s_element_last_byte.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def exercise(dut: Any, values: list[tuple[int, bytes]]) -> None:
    outgoing = [
        (global_index, byte_index, value, byte_index == len(encoded) - 1)
        for global_index, encoded in values
        for byte_index, value in enumerate(encoded)
    ]
    expected = [
        (
            global_index,
            encoded[0],
            index,
            int.from_bytes(segment.ljust(4, b"\0"), "little"),
            (1 << len(segment)) - 1,
            index == (len(encoded[1:]) - 1) // 4,
        )
        for global_index, encoded in values
        for index, segment in enumerate(
            encoded[1:][offset : offset + 4] for offset in range(0, len(encoded) - 1, 4)
        )
    ]
    sent = 0
    observed: list[tuple[int, int, int, int, int, bool]] = []
    for cycle in range(3000):
        await FallingEdge(dut.clk)
        dut.m_ready.value = int(cycle % 7 not in (0, 1, 5))
        if sent < len(outgoing):
            global_index, byte_index, value, last_byte = outgoing[sent]
            dut.s_global_index.value = global_index
            dut.s_byte_index.value = byte_index
            dut.s_value_byte.value = value
            dut.s_element_last_byte.value = int(last_byte)
            dut.s_valid.value = 1
        else:
            dut.s_valid.value = 0
        await ReadOnly()
        if int(dut.s_valid.value) and int(dut.s_ready.value):
            sent += 1
        if int(dut.m_valid.value) and int(dut.m_ready.value):
            observed.append(
                (
                    int(dut.m_global_index.value),
                    int(dut.m_state_tag.value),
                    int(dut.m_segment_index.value),
                    int(dut.m_segment_data.value),
                    int(dut.m_segment_keep.value),
                    bool(int(dut.m_segment_last.value)),
                )
            )
        await RisingEdge(dut.clk)
        if len(observed) == len(expected):
            assert sent == len(outgoing)
            assert observed == expected
            return
    raise AssertionError(f"segmenter stalled after {sent} bytes and {len(observed)} segments")


@cocotb.test()
async def finite_special_and_widest_values_preserve_every_byte(dut: Any) -> None:
    await initialize(dut)
    values = [
        (17, encode_kulisch(decode_native(0x3F800000, ConcreteFormat.FP32), 279)),
        (18, encode_kulisch(ExactValue("zero", True, Fraction(0)), 279)),
        (19, encode_kulisch(decode_native(0x80000001, ConcreteFormat.FP32), 4096)),
    ]
    await exercise(dut, values)
