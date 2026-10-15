"""Final-round all sixteen exact lanes with elastic tile-level metadata."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, encode_kulisch, round_native


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_first_element.value = 0
    dut.s_element_keep.value = 0
    dut.s_kulisch_tags.value = 0
    dut.s_kulisch_integers.value = 0
    dut.s_output_format.value = 4
    dut.s_valid.value = 0
    dut.s_enable.value = 1
    dut.s_fault.value = 0
    dut.s_flush.value = 0
    dut.m_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


@cocotb.test()
async def sixty_four_fp32_tiles_round_at_one_tile_per_cycle(dut: Any) -> None:
    await initialize(dut)
    encoded = encode_kulisch(ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24)), 320)
    dut.s_kulisch_tags.value = int.from_bytes(encoded[:1] * 16, "little")
    dut.s_kulisch_integers.value = int.from_bytes(encoded[1:] * 16, "little")
    dut.s_element_keep.value = 0xFFFF
    sent = 0
    received: list[tuple[int, int]] = []
    issue_cycles: list[int] = []
    for cycle in range(80):
        await FallingEdge(dut.clk)
        dut.s_valid.value = int(sent < 64)
        dut.s_first_element.value = min(sent, 63) * 16
        await ReadOnly()
        accepted = sent < 64 and int(dut.s_ready.value) == 1
        if int(dut.m_valid.value):
            assert int(dut.m_error.value) == 0
            assert int(dut.m_element_keep.value) == 0xFFFF
            received.append((int(dut.m_first_element.value), int(dut.m_element_bits.value)))
        await RisingEdge(dut.clk)
        if accepted:
            issue_cycles.append(cycle)
            sent += 1
        if len(received) == 64:
            break
    assert sent == 64 and len(received) == 64
    assert issue_cycles == list(range(issue_cycles[0], issue_cycles[0] + 64))
    assert [first for first, _bits in received] == list(range(0, 1024, 16))
    assert all(
        bits == int.from_bytes((0x3F800000).to_bytes(4, "little") * 16, "little")
        for _first, bits in received
    )


@cocotb.test()
async def stalled_tile_holds_bits_and_recovers_credit(dut: Any) -> None:
    await initialize(dut)
    encoded = encode_kulisch(ExactValue("finite", False, Fraction(1, 1 << 24)), 320)
    dut.s_kulisch_tags.value = int.from_bytes(encoded[:1] * 16, "little")
    dut.s_kulisch_integers.value = int.from_bytes(encoded[1:] * 16, "little")
    dut.s_element_keep.value = 0xFFFF
    dut.s_first_element.value = 32
    dut.m_ready.value = 0
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(16):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            break
    else:
        raise AssertionError("tile rounder did not produce a stalled result")
    first = int(dut.m_first_element.value)
    bits = int(dut.m_element_bits.value)
    for _ in range(5):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_first_element.value) == first
        assert int(dut.m_element_bits.value) == bits
    assert first == 32
    assert bits == int.from_bytes((0x33800000).to_bytes(4, "little") * 16, "little")
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.m_valid.value) == 0


@cocotb.test()
async def mixed_tiles_keep_metadata_aligned_through_backpressure(dut: Any) -> None:
    await initialize(dut)
    cases = (
        (ExactValue("finite", False, Fraction(3)), ConcreteFormat.INT8, 0xFFFF),
        (ExactValue("finite", True, Fraction(-7, 2)), ConcreteFormat.FP16, 0x00FF),
        (ExactValue("finite", False, Fraction(1, 1 << 24)), ConcreteFormat.BF16, 0xFF00),
        (
            ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24)),
            ConcreteFormat.FP32,
            0x5555,
        ),
        (ExactValue("finite", True, Fraction(-2)), ConcreteFormat.INT8, 0xAAAA),
        (ExactValue("finite", False, Fraction(5)), ConcreteFormat.FP16, 0xFFFF),
    )
    sent = 0
    received = 0
    for cycle in range(100):
        await FallingEdge(dut.clk)
        dut.m_ready.value = int(cycle >= 12 and cycle % 4 != 0)
        dut.s_valid.value = int(sent < len(cases))
        if sent < len(cases):
            value, output_format, keep = cases[sent]
            encoded = encode_kulisch(value, 320)
            dut.s_first_element.value = sent * 16
            dut.s_element_keep.value = keep
            dut.s_kulisch_tags.value = int.from_bytes(encoded[:1] * 16, "little")
            dut.s_kulisch_integers.value = int.from_bytes(encoded[1:] * 16, "little")
            dut.s_output_format.value = int(output_format)
        await ReadOnly()
        accepted = sent < len(cases) and int(dut.s_ready.value) == 1
        delivered = int(dut.m_valid.value) == 1 and int(dut.m_ready.value) == 1
        if delivered:
            value, output_format, keep = cases[received]
            width = (
                8
                if output_format == ConcreteFormat.INT8
                else (32 if output_format == ConcreteFormat.FP32 else 16)
            )
            bits = round_native(value, output_format)
            expected = sum((bits if keep & (1 << lane) else 0) << (32 * lane) for lane in range(16))
            assert int(dut.m_first_element.value) == received * 16
            assert int(dut.m_element_keep.value) == keep
            assert int(dut.m_element_bits.value) == expected
            assert int(dut.m_error.value) == 0
            assert bits < (1 << width)
        await RisingEdge(dut.clk)
        sent += int(accepted)
        received += int(delivered)
        if received == len(cases):
            break
    assert sent == received == len(cases)


@cocotb.test()
async def tile_waits_for_its_path_and_carries_the_fault_of_the_operation(dut: Any) -> None:
    await initialize(dut)
    encoded = encode_kulisch(ExactValue("finite", False, Fraction(1)), 320)
    dut.s_kulisch_tags.value = int.from_bytes(encoded[:1] * 16, "little")
    dut.s_kulisch_integers.value = int.from_bytes(encoded[1:] * 16, "little")
    dut.s_element_keep.value = 0xFFFF
    dut.s_enable.value = 0
    for first in (0, 16):
        dut.s_first_element.value = first
        await FallingEdge(dut.clk)
        dut.s_valid.value = 1
        await ReadOnly()
        assert int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0
    # Both tiles are rounded and wait: results do not leave on this path.
    for _ in range(20):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_valid.value) == 0
    await FallingEdge(dut.clk)
    dut.s_enable.value = 1
    seen: list[tuple[int, int]] = []
    for cycle in range(12):
        await FallingEdge(dut.clk)
        # The operation fails after the first tile has left.
        if len(seen) == 1:
            dut.s_fault.value = 1
            dut.m_ready.value = int(cycle > 8)
        await ReadOnly()
        taken = int(dut.m_valid.value) and int(dut.m_ready.value)
        entry = (int(dut.m_first_element.value), int(dut.m_error.value))
        await RisingEdge(dut.clk)
        if taken:
            seen.append(entry)
    assert seen == [(0, 0), (16, 1)]


@cocotb.test()
async def flush_drops_every_tile_inside_and_returns_the_queue_places(dut: Any) -> None:
    await initialize(dut)
    encoded = encode_kulisch(ExactValue("finite", False, Fraction(1)), 320)
    dut.s_kulisch_tags.value = int.from_bytes(encoded[:1] * 16, "little")
    dut.s_kulisch_integers.value = int.from_bytes(encoded[1:] * 16, "little")
    dut.s_element_keep.value = 0xFFFF
    dut.m_ready.value = 0

    async def offer(first: int) -> bool:
        await FallingEdge(dut.clk)
        dut.s_first_element.value = first
        dut.s_valid.value = 1
        await ReadOnly()
        taken = int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0
        return taken

    # Fill the queue, with the consumer stalled, until no tile is accepted.
    accepted = 0
    while await offer(accepted * 16):
        accepted += 1
        assert accepted <= 32
    assert accepted == 32
    await FallingEdge(dut.clk)
    dut.s_flush.value = 1
    for _ in range(8):
        await FallingEdge(dut.clk)
    dut.s_flush.value = 0
    dut.m_ready.value = 1
    for _ in range(12):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_valid.value) == 0
    # Every place is free again, and what is rounded now is what comes out.
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    again = 0
    while await offer(1024 + again * 16):
        again += 1
        assert again <= 32
    assert again == 32
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    firsts: list[int] = []
    for _ in range(46):
        await ReadOnly()
        if int(dut.m_valid.value):
            firsts.append(int(dut.m_first_element.value))
        await FallingEdge(dut.clk)
    assert firsts == [1024 + index * 16 for index in range(32)]
