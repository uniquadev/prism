"""A lane-banked exact pipeline accepts distinct FP32 tiles every cycle."""

from __future__ import annotations

import struct
from fractions import Fraction
from random import Random
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, decode_kulisch


def bits_for_integer(value: int) -> int:
    return int.from_bytes(struct.pack("<f", float(value)), "little")


def exact_integer(value: int) -> ExactValue:
    if value == 0:
        return ExactValue("zero", False, Fraction(0))
    return ExactValue("finite", value < 0, Fraction(value))


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_slot.value = 0
    dut.s_first_element.value = 0
    dut.s_format.value = int(ConcreteFormat.FP32)
    dut.s_element_bits.value = 0
    dut.s_element_keep.value = 0
    dut.s_valid.value = 0
    dut.s_release.value = 0
    dut.s_result_slot.value = 0
    dut.s_result_read_valid.value = 0
    dut.s_result_read_arm.value = 0
    dut.m_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def capture(dut: Any, outputs: list[tuple[int, tuple[ExactValue, ...]]]) -> None:
    while True:
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value) and int(dut.m_ready.value):
            assert int(dut.m_errors.value) == 0
            assert int(dut.m_element_keep.value) == 0xFFFF
            tags = int(dut.m_kulisch_tags.value)
            integers = int(dut.m_kulisch_integers.value)
            values = tuple(
                decode_kulisch(
                    bytes((tags >> (lane * 8) & 0xFF,))
                    + (integers >> (lane * 320) & ((1 << 320) - 1)).to_bytes(40, "little"),
                    320,
                )
                for lane in range(16)
            )
            outputs.append((int(dut.m_first_element.value), values))


async def send_tile(dut: Any, *, slot: int, fmt: ConcreteFormat, bits: int) -> int:
    widths = {
        ConcreteFormat.INT8: 1,
        ConcreteFormat.FP16: 2,
        ConcreteFormat.BF16: 2,
        ConcreteFormat.FP32: 4,
    }
    waits = 0
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_slot.value = slot
        dut.s_first_element.value = slot * 16
        dut.s_format.value = int(fmt)
        dut.s_element_bits.value = int.from_bytes(
            bits.to_bytes(widths[fmt], "little") * 16, "little"
        )
        dut.s_element_keep.value = 0xFFFF
        dut.s_valid.value = 1
        await ReadOnly()
        if int(dut.s_ready.value):
            await RisingEdge(dut.clk)
            break
        waits += 1
    else:
        raise AssertionError("exact tile pipeline never returned its input credit")
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    return waits


@cocotb.test()
async def exact_three_rank_tiles_issue_each_cycle_and_preserve_half_ulp(dut: Any) -> None:
    await initialize(dut)
    outputs: list[tuple[int, tuple[ExactValue, ...]]] = []
    observer = cocotb.start_soon(capture(dut, outputs))
    issue_cycles: list[int] = []
    tiles = tuple(
        (slot, value) for value in (0x3F800000, 0x33800000, 0xBF800000) for slot in range(16)
    )
    sent = 0
    for cycle in range(200):
        await FallingEdge(dut.clk)
        if sent < len(tiles):
            slot, value = tiles[sent]
            dut.s_slot.value = slot
            dut.s_first_element.value = slot * 16
            dut.s_element_bits.value = int.from_bytes(value.to_bytes(4, "little") * 16, "little")
            dut.s_element_keep.value = 0xFFFF
            dut.s_valid.value = 1
        else:
            dut.s_valid.value = 0
        await ReadOnly()
        accepted = sent < len(tiles) and int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        if accepted:
            issue_cycles.append(cycle)
            sent += 1
        if len(outputs) == len(tiles):
            break
    assert sent == len(tiles)
    assert issue_cycles == list(range(issue_cycles[0], issue_cycles[0] + len(tiles)))
    assert len(outputs) == len(tiles)
    expected_values = (
        ExactValue("finite", False, Fraction(1)),
        ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24)),
        ExactValue("finite", False, Fraction(1, 1 << 24)),
    )
    for sequence, (first, values) in enumerate(outputs):
        assert first == sequence % 16 * 16
        assert values == (expected_values[sequence // 16],) * 16
    dut._log.info("exact native tile pipeline accepted 48 full tiles in 48 cycles")
    observer.cancel()


@cocotb.test()
async def same_slot_hazard_mixed_formats_backpressure_and_release(dut: Any) -> None:
    await initialize(dut)
    outputs: list[tuple[int, tuple[ExactValue, ...]]] = []
    observer = cocotb.start_soon(capture(dut, outputs))
    assert await send_tile(dut, slot=0, fmt=ConcreteFormat.INT8, bits=7) == 0
    waits = await send_tile(dut, slot=0, fmt=ConcreteFormat.FP16, bits=0x0001)
    assert waits >= 1
    for _ in range(30):
        await FallingEdge(dut.clk)
        if len(outputs) == 2:
            break
    assert len(outputs) == 2
    assert outputs[0][1] == (ExactValue("finite", False, Fraction(7)),) * 16
    assert outputs[1][1] == (ExactValue("finite", False, Fraction(7) + Fraction(1, 1 << 24)),) * 16
    dut.m_ready.value = 0
    await send_tile(dut, slot=1, fmt=ConcreteFormat.BF16, bits=0xBF80)
    for _ in range(12):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            break
    else:
        raise AssertionError("stalled exact tile never reached the output")
    for _ in range(8):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_first_element.value) == 16
        assert int(dut.m_element_keep.value) == 0xFFFF
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    for _ in range(30):
        await FallingEdge(dut.clk)
        if len(outputs) == 3:
            break
    assert outputs[2][1] == (ExactValue("finite", True, Fraction(-1)),) * 16
    for _ in range(10):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.s_release_ready.value):
            break
    else:
        raise AssertionError("exact tile pipeline did not drain before release")
    await FallingEdge(dut.clk)
    dut.s_release.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_release.value = 0
    await send_tile(dut, slot=0, fmt=ConcreteFormat.BF16, bits=0xBF80)
    for _ in range(20):
        await FallingEdge(dut.clk)
        if len(outputs) == 4:
            break
    assert outputs[3][1] == (ExactValue("finite", True, Fraction(-1)),) * 16
    observer.cancel()


@cocotb.test()
async def two_4096_element_ranks_use_all_256_exact_slots_without_aliases(dut: Any) -> None:
    await initialize(dut)
    outputs: list[tuple[int, tuple[ExactValue, ...]]] = []
    observer = cocotb.start_soon(capture(dut, outputs))
    ones = int.from_bytes((0x3F800000).to_bytes(4, "little") * 16, "little")
    negative_ones = int.from_bytes((0xBF800000).to_bytes(4, "little") * 16, "little")
    sent = 0
    issue_cycles: list[int] = []
    for cycle in range(600):
        await FallingEdge(dut.clk)
        dut.s_valid.value = int(sent < 512)
        dut.s_slot.value = min(sent % 256, 255)
        dut.s_first_element.value = min(sent % 256, 255) * 16
        dut.s_format.value = int(ConcreteFormat.FP32)
        dut.s_element_bits.value = ones if sent < 256 else negative_ones
        dut.s_element_keep.value = 0xFFFF
        await ReadOnly()
        accepted = sent < 512 and int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        if accepted:
            issue_cycles.append(cycle)
            sent += 1
        if len(outputs) == 512:
            break
    assert sent == 512
    assert len(issue_cycles) == 512
    assert issue_cycles[-1] - issue_cycles[0] + 1 == 512
    assert len(outputs) == 512
    one = ExactValue("finite", False, Fraction(1))
    zero = ExactValue("zero", False, Fraction(0))
    for sequence, (first, values) in enumerate(outputs):
        assert first == sequence % 256 * 16
        assert values == (one if sequence < 256 else zero,) * 16
    reads: list[tuple[int, int, int, int]] = []
    requested = 0
    for _ in range(300):
        await FallingEdge(dut.clk)
        dut.s_result_read_arm.value = 1
        dut.s_result_read_valid.value = int(requested < 256)
        dut.s_result_slot.value = min(requested, 255)
        await ReadOnly()
        accepted = requested < 256 and int(dut.s_result_read_ready.value) == 1
        if int(dut.m_result_valid.value):
            reads.append(
                (
                    int(dut.m_result_slot.value),
                    int(dut.m_result_present.value),
                    int(dut.m_result_tags.value),
                    int(dut.m_result_integers.value),
                )
            )
        await RisingEdge(dut.clk)
        if accepted:
            requested += 1
        if len(reads) == 256:
            break
    assert requested == 256
    assert len(reads) == 256
    assert all(slot == index for index, (slot, *_rest) in enumerate(reads))
    assert all(present == 0xFFFF for _slot, present, _tags, _integers in reads)
    assert all(tags == int.from_bytes(bytes((4,)) * 16, "little") for _, _, tags, _ in reads)
    assert all(integers == 0 for _, _, _, integers in reads)
    dut._log.info("exact pipeline issued 512 tiles for two 4096-element ranks without bubbles")
    observer.cancel()


@cocotb.test()
async def seeded_conflicts_backpressure_and_result_reads_keep_exact_state(dut: Any) -> None:
    await initialize(dut)
    random = Random(0xEA17)
    state = [[0] * 16 for _ in range(16)]
    present = [0] * 16
    operations: list[tuple[int, int, int, tuple[int, ...]]] = []
    for _ in range(128):
        slot = random.randrange(16)
        delta = random.choice((-2, -1, 1, 2))
        keep = (1 << random.randrange(1, 17)) - 1
        for lane in range(16):
            if keep & (1 << lane):
                state[slot][lane] += delta
                present[slot] |= 1 << lane
        operations.append((slot, bits_for_integer(delta), keep, tuple(state[slot])))

    sent = 0
    emitted = 0
    held: tuple[int, int, int, int] | None = None
    for cycle in range(1500):
        await FallingEdge(dut.clk)
        dut.m_ready.value = int(cycle % 11 not in (4, 5, 6))
        dut.s_valid.value = int(sent < len(operations))
        if sent < len(operations):
            slot, bits, keep, _expected = operations[sent]
            dut.s_slot.value = slot
            dut.s_first_element.value = slot * 16
            dut.s_format.value = int(ConcreteFormat.FP32)
            dut.s_element_bits.value = int.from_bytes(bits.to_bytes(4, "little") * 16, "little")
            dut.s_element_keep.value = keep
        await ReadOnly()
        take_input = sent < len(operations) and int(dut.s_ready.value)
        valid = int(dut.m_valid.value)
        ready = int(dut.m_ready.value)
        output = (
            int(dut.m_first_element.value),
            int(dut.m_element_keep.value),
            int(dut.m_kulisch_tags.value),
            int(dut.m_kulisch_integers.value),
        )
        if held is not None:
            assert valid and output == held
        held = output if valid and not ready else None
        if valid and ready:
            slot, _bits, keep, expected = operations[emitted]
            assert output[0] == slot * 16
            assert output[1] == keep
            assert int(dut.m_errors.value) == 0
            for lane in range(16):
                if keep & (1 << lane):
                    actual = decode_kulisch(
                        bytes((output[2] >> (lane * 8) & 0xFF,))
                        + (output[3] >> (lane * 320) & ((1 << 320) - 1)).to_bytes(40, "little"),
                        320,
                    )
                    assert actual == exact_integer(expected[lane])
            emitted += 1
        await RisingEdge(dut.clk)
        if take_input:
            sent += 1
        if emitted == len(operations):
            break
    assert sent == emitted == len(operations)

    requested = 0
    received = 0
    held_result: tuple[int, int, int, int] | None = None
    for cycle in range(100):
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0
        dut.m_ready.value = 1
        # A result stays for one cycle; the requester is what pauses.
        asking = requested < 16 and cycle % 7 not in (2, 3)
        dut.s_result_read_arm.value = 1
        dut.s_result_read_valid.value = int(asking)
        dut.s_result_slot.value = min(requested, 15)
        await ReadOnly()
        take_request = asking and int(dut.s_result_read_ready.value)
        valid = int(dut.m_result_valid.value)
        ready = 1
        response = (
            int(dut.m_result_slot.value),
            int(dut.m_result_present.value),
            int(dut.m_result_tags.value),
            int(dut.m_result_integers.value),
        )
        if held_result is not None:
            assert valid and response == held_result
        held_result = response if valid and not ready else None
        if valid and ready:
            assert response[0] == received
            assert response[1] == present[received]
            for lane in range(16):
                if response[1] & (1 << lane):
                    actual = decode_kulisch(
                        bytes((response[2] >> (lane * 8) & 0xFF,))
                        + (response[3] >> (lane * 320) & ((1 << 320) - 1)).to_bytes(40, "little"),
                        320,
                    )
                    assert actual == exact_integer(state[received][lane])
            received += 1
        await RisingEdge(dut.clk)
        if take_request:
            requested += 1
        if received == 16:
            break
    assert requested == received == 16


@cocotb.test()
async def read_waits_for_the_tiles_before_it_and_shuts_out_the_tiles_after_it(dut: Any) -> None:
    await initialize(dut)
    await send_tile(dut, slot=3, fmt=ConcreteFormat.FP32, bits=bits_for_integer(1))
    # The request comes while the tile is still in the stages; it is granted
    # only when the tile has reached the memory.
    dut.s_result_read_arm.value = 1
    dut.s_result_read_valid.value = 1
    dut.s_result_slot.value = 3
    waited = 0
    for _ in range(20):
        await ReadOnly()
        if int(dut.s_result_read_ready.value):
            break
        waited += 1
        await FallingEdge(dut.clk)
    else:
        raise AssertionError("read request was never granted")
    assert waited >= 4
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_result_read_arm.value = 0
    dut.s_result_read_valid.value = 0
    # A tile offered from now on is not taken, and the result of the read is
    # that of the tile before it.
    dut.s_slot.value = 5
    dut.s_first_element.value = 5 * 16
    dut.s_element_bits.value = int.from_bytes(
        bits_for_integer(7).to_bytes(4, "little") * 16, "little"
    )
    dut.s_element_keep.value = 0xFFFF
    dut.s_valid.value = 1
    results = []
    for _ in range(12):
        await ReadOnly()
        assert int(dut.s_ready.value) == 0
        if int(dut.m_result_valid.value):
            results.append(
                (
                    int(dut.m_result_slot.value),
                    int(dut.m_result_present.value),
                    int(dut.m_result_integers.value) & ((1 << 320) - 1),
                )
            )
        await FallingEdge(dut.clk)
    assert results == [(3, 0xFFFF, 1 << 149)]
    # After the release the bank is empty and takes tiles again.
    dut.s_valid.value = 0
    await FallingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.s_release_ready.value) == 1
    await FallingEdge(dut.clk)
    dut.s_release.value = 1
    await FallingEdge(dut.clk)
    dut.s_release.value = 0
    await send_tile(dut, slot=3, fmt=ConcreteFormat.FP32, bits=bits_for_integer(2))
    dut.s_result_read_arm.value = 1
    dut.s_result_read_valid.value = 1
    dut.s_result_slot.value = 3
    for _ in range(20):
        await ReadOnly()
        if int(dut.s_result_read_ready.value):
            break
        await FallingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_result_read_valid.value = 0
    for _ in range(4):
        await ReadOnly()
        if int(dut.m_result_valid.value):
            break
        await FallingEdge(dut.clk)
    else:
        raise AssertionError("no result after the release")
    assert int(dut.m_result_integers.value) & ((1 << 320) - 1) == 2 << 149
