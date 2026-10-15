"""The striped bank port returns each result from the bank that holds it."""

from __future__ import annotations

import struct
from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, decode_kulisch

BANKS = 4
TILES = 12


def value_of(tile: int, lane: int) -> int:
    """A different small integer for every lane of every tile."""
    return 1 + 17 * tile + lane


def expected_tile(tile: int) -> tuple[ExactValue, ...]:
    return tuple(ExactValue("finite", False, Fraction(value_of(tile, lane))) for lane in range(16))


def tile_bits(tile: int) -> int:
    payload = b"".join(struct.pack("<f", float(value_of(tile, lane))) for lane in range(16))
    return int.from_bytes(payload, "little")


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_first_element.value = 0
    dut.s_format.value = int(ConcreteFormat.FP32)
    dut.s_bits.value = 0
    dut.s_keep.value = 0
    dut.s_valid.value = 0
    dut.s_flush.value = 0
    dut.s_release.value = 0
    dut.s_result_slot.value = 0
    dut.s_wide_result.value = 0
    dut.s_result_read_valid.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def store_tiles(dut: Any) -> None:
    """Tile k holds elements 16k to 16k+15: bank k mod 4, range slot k div 4."""
    for tile in range(TILES):
        for _ in range(100):
            await FallingEdge(dut.clk)
            dut.s_first_element.value = 16 * tile
            dut.s_bits.value = tile_bits(tile)
            dut.s_keep.value = (1 << 64) - 1
            dut.s_valid.value = 1
            await ReadOnly()
            if int(dut.s_ready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError("the port never took a tile")
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(24):
        await RisingEdge(dut.clk)
    assert int(dut.m_arithmetic_fault.value) == 0


def lanes_of(dut: Any, first: int, count: int) -> tuple[ExactValue, ...]:
    width = len(dut.m_result_integers) // len(dut.m_result_present)
    tags = int(dut.m_result_tags.value)
    integers = int(dut.m_result_integers.value)
    return tuple(
        decode_kulisch(
            bytes((tags >> (lane * 8) & 0xFF,))
            + (integers >> (lane * width) & ((1 << width) - 1)).to_bytes(width // 8, "little"),
            width,
        )
        for lane in range(first, first + count)
    )


async def read(dut: Any, requests: list[tuple[int, bool]]) -> list[tuple[int, int, Any]]:
    """Issue the requests as fast as they are taken and collect every result.

    A request is (slot, wide). Returns, per result, the slot it reports, its
    presence bits and a function result captured while it was valid.
    """
    results: list[tuple[int, int, Any]] = []
    taken: list[int] = []
    pending = list(requests)
    for cycle in range(200):
        await FallingEdge(dut.clk)
        if pending:
            slot, wide = pending[0]
            dut.s_result_slot.value = slot
            dut.s_wide_result.value = int(wide)
            dut.s_result_read_valid.value = 1
        else:
            dut.s_result_read_valid.value = 0
        await ReadOnly()
        if pending and int(dut.s_result_read_ready.value):
            taken.append(cycle)
            pending.pop(0)
        if int(dut.m_result_valid.value):
            present = int(dut.m_result_present.value)
            results.append(
                (int(dut.m_result_slot.value), present, lanes_of(dut, 0, len(dut.m_result_present)))
            )
        if not pending and len(results) == len(requests):
            break
    assert not pending, "not every request was taken"
    # Once the banks read, a request is taken every cycle.
    assert taken[1:] == list(range(taken[1], taken[1] + len(taken) - 1))
    await FallingEdge(dut.clk)
    return results


@cocotb.test()
async def narrow_results_of_different_banks_on_consecutive_cycles(dut: Any) -> None:
    await initialize(dut)
    await store_tiles(dut)
    results = await read(dut, [(tile, False) for tile in range(TILES)])
    assert len(results) == TILES
    for tile, (slot, present, lanes) in enumerate(results):
        assert slot == tile
        assert present & 0xFFFF == 0xFFFF
        assert present >> 16 == 0
        assert lanes[:16] == expected_tile(tile), f"tile {tile}"


@cocotb.test()
async def wide_and_narrow_results_alternate_without_a_gap(dut: Any) -> None:
    """A wide result takes its low tile from bank 0 whatever was read before."""
    await initialize(dut)
    await store_tiles(dut)
    requests = [(1, False), (0, True), (6, False), (1, True), (11, False), (2, True), (4, False)]
    results = await read(dut, requests)
    assert len(results) == len(requests)
    for (slot, wide), (reported, present, lanes) in zip(requests, results, strict=True):
        if wide:
            assert reported == slot * BANKS
            assert present == (1 << (16 * BANKS)) - 1
            for bank in range(BANKS):
                assert lanes[16 * bank : 16 * bank + 16] == expected_tile(slot * BANKS + bank), (
                    f"wide {slot} bank {bank}"
                )
        else:
            assert reported == slot
            assert present == 0xFFFF
            assert lanes[:16] == expected_tile(slot), f"narrow {slot}"
