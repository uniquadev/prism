"""The segment reader cuts tiles to the Ethernet payload MTU and keeps their values."""

from __future__ import annotations

import random
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat


def segment_sizes(formats: list[Any], budget: int, widths: dict[int, int]) -> list[int]:
    """Lanes per segment of one tile.

    A segment takes every value that fits the packet body and stops before
    the first exact value that lies sixteen or more lanes after its start.
    """
    from itertools import groupby

    def body_bytes(values: list[Any]) -> int:
        return sum(
            4 + 4 * ((len(tuple(run)) * widths[int(fmt)] + 3) // 4) for fmt, run in groupby(values)
        )

    sizes = []
    cursor = 0
    while cursor < len(formats):
        remaining = formats[cursor:]
        size = max(n for n in range(1, len(remaining) + 1) if body_bytes(remaining[:n]) <= budget)
        far = [lane for lane in range(16, size) if remaining[lane] == ConcreteFormat.KULISCH]
        if far:
            size = far[0]
        sizes.append(size)
        cursor += size
    return sizes


async def segment(dut: Any, limit: int = 96) -> None:
    """Wait for the next segment: the reader schedules through registers."""
    for _ in range(limit):
        await ReadOnly()
        if int(dut.m_valid.value):
            return
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    raise AssertionError("reader produced no segment")


@cocotb.test()
async def legal_mixed_tile_uses_full_mtu_payload_budget(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_clear.value = 0
    dut.s_mtu.value = 576
    dut.s_kulisch_bits.value = 320
    dut.s_first_element.value = 0
    dut.s_keep.value = 0
    dut.s_formats.value = 0
    dut.s_native_bits.value = 0
    dut.s_fp32_bits.value = 0
    dut.s_fp32_eligible.value = 0
    dut.s_tags.value = 0
    dut.s_integers.value = 0
    dut.s_error.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    # 12 Kulisch-320 values and four one-value native groups occupy 528 body
    # bytes: legal below 576 - 2 - 40 = 534, but above the stale 520 limit.
    formats = (ConcreteFormat.KULISCH,) * 12 + (
        ConcreteFormat.INT8,
        ConcreteFormat.FP16,
        ConcreteFormat.BF16,
        ConcreteFormat.INT8,
    )
    encoded_formats = sum(int(fmt) << (lane * 8) for lane, fmt in enumerate(formats))
    dut.s_keep.value = (1 << 16) - 1
    dut.s_formats.value = encoded_formats
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    await segment(dut)
    assert not int(dut.m_fault.value)
    assert int(dut.m_count.value) == 16
    assert int(dut.m_first_element.value) == 0
    assert int(dut.m_formats.value) == encoded_formats


@cocotb.test()
async def mixed_prefixes_split_at_the_numbergroup_byte_boundary(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_clear.value = 0
    dut.s_mtu.value = 576
    dut.s_kulisch_bits.value = 320
    dut.s_first_element.value = 0
    dut.s_keep.value = 0
    dut.s_formats.value = 0
    dut.s_native_bits.value = 0
    dut.s_fp32_bits.value = 0
    dut.s_fp32_eligible.value = 0
    dut.s_tags.value = 0
    dut.s_integers.value = 0
    dut.s_error.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    widths = {
        ConcreteFormat.INT8: 1,
        ConcreteFormat.FP16: 2,
        ConcreteFormat.BF16: 2,
        ConcreteFormat.FP32: 4,
        ConcreteFormat.KULISCH: 41,
    }

    def body_bytes(formats: list[ConcreteFormat]) -> int:
        runs: list[tuple[ConcreteFormat, int]] = []
        for fmt in formats:
            if runs and runs[-1][0] == fmt:
                runs[-1] = (fmt, runs[-1][1] + 1)
            else:
                runs.append((fmt, 1))
        return sum(4 + 4 * ((count * widths[fmt] + 3) // 4) for fmt, count in runs)

    rng = random.Random(0x51E7)
    options = tuple(widths)
    cases = [[ConcreteFormat.KULISCH] * 16]
    cases.append(
        [ConcreteFormat.KULISCH] * 12
        + [ConcreteFormat.INT8, ConcreteFormat.FP16, ConcreteFormat.BF16, ConcreteFormat.FP32]
    )
    cases.extend([rng.choice(options) for _ in range(16)] for _ in range(32))
    for case_index, formats in enumerate(cases):
        encoded = sum(int(fmt) << (8 * lane) for lane, fmt in enumerate(formats))
        dut.s_first_element.value = case_index * 16
        dut.s_keep.value = (1 << 16) - 1
        dut.s_formats.value = encoded
        dut.s_valid.value = 1
        await ReadOnly()
        assert int(dut.s_ready.value)
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0

        cursor = 0
        while cursor < 16:
            await segment(dut)
            assert not int(dut.m_fault.value)
            expected = max(
                size
                for size in range(1, 17 - cursor)
                if body_bytes(formats[cursor : cursor + size]) <= 576 - 42
            )
            assert int(dut.m_count.value) == expected, (case_index, cursor)
            assert int(dut.m_first_element.value) == case_index * 16 + cursor
            for lane, fmt in enumerate(formats[cursor : cursor + expected]):
                assert (int(dut.m_formats.value) >> (lane * 8)) & 0xFF == int(fmt)
            cursor += expected
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)


@cocotb.test()
async def all_cursor_offsets_preserve_payload_under_backpressure(dut: Any) -> None:
    """Check re-alignment and all payload fields through arbitrary MTU splits.

    Lanes beyond the segment are not part of it, and exact integers travel
    only on the sixteen low lanes of a segment.
    """
    lanes = len(dut.s_keep)
    integer_width = len(dut.s_integers) // lanes
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    for name in (
        "s_clear",
        "s_first_element",
        "s_keep",
        "s_formats",
        "s_native_bits",
        "s_fp32_bits",
        "s_fp32_eligible",
        "s_tags",
        "s_integers",
        "s_error",
        "s_valid",
        "m_ready",
    ):
        getattr(dut, name).value = 0
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = integer_width
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    rng = random.Random(0xA119)
    widths = {
        int(ConcreteFormat.INT8): 1,
        int(ConcreteFormat.FP16): 2,
        int(ConcreteFormat.BF16): 2,
        int(ConcreteFormat.FP32): 4,
        int(ConcreteFormat.KULISCH): 1 + (integer_width + 7) // 8,
    }
    cases = [
        [ConcreteFormat.INT8] * offset
        + [ConcreteFormat.KULISCH]
        + [ConcreteFormat.INT8] * (lanes - offset - 1)
        for offset in range(lanes)
    ]
    cases.extend([[ConcreteFormat.KULISCH] * lanes, [ConcreteFormat.INT8]])
    options = (
        ConcreteFormat.INT8,
        ConcreteFormat.FP16,
        ConcreteFormat.BF16,
        ConcreteFormat.FP32,
        ConcreteFormat.KULISCH,
    )
    cases.extend([rng.choice(options) for _ in range(rng.randint(1, lanes))] for _ in range(128))
    # Exercise padding at every residue and adjacent groups with equal byte
    # widths but different types, including complete and partial source tiles.
    for run_length in (1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63):
        cases.append([options[(lane // run_length) % len(options)] for lane in range(lanes)])
    cases.extend([[fmt] * lanes for fmt in options])

    outputs = (
        "m_first_element",
        "m_count",
        "m_formats",
        "m_native_bits",
        "m_tags",
        "m_integers",
        "m_valid",
        "m_fault",
    )
    for case_index, formats in enumerate(cases):
        count = len(formats)
        native = [rng.getrandbits(32) for _ in formats]
        tags = [0 for _ in formats]
        integers = [rng.getrandbits(integer_width - 1) for _ in formats]
        mtu = 1500 if case_index < lanes else 576
        dut.s_mtu.value = mtu
        dut.s_first_element.value = case_index * lanes
        dut.s_keep.value = (1 << count) - 1
        for signal, values, bits in (
            ("s_formats", formats, 8),
            ("s_native_bits", native, 32),
            ("s_tags", tags, 8),
            ("s_integers", integers, integer_width),
        ):
            getattr(dut, signal).value = sum(int(v) << (i * bits) for i, v in enumerate(values))
        dut.s_valid.value = 1
        dut.m_ready.value = 0
        await ReadOnly()
        assert int(dut.s_ready.value)
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0
        cursor = 0
        sizes = segment_sizes(formats, mtu - 42, widths)
        while cursor < count:
            await segment(dut)
            assert not int(dut.m_fault.value)
            size = int(dut.m_count.value)
            assert 0 < size <= count - cursor
            expected = sizes.pop(0)
            assert size == expected, (case_index, cursor, formats, size, expected)
            assert int(dut.m_first_element.value) == case_index * lanes + cursor
            assert int(dut.m_formats.value) == sum(
                int(v) << (i * 8) for i, v in enumerate(formats[cursor : cursor + size])
            ), (case_index, cursor)
            for signal, values, bits, checked in (
                ("m_native_bits", native, 32, size),
                ("m_tags", tags, 8, min(size, 16)),
                ("m_integers", integers, integer_width, min(size, 16)),
            ):
                expected = sum(
                    int(v) << (i * bits) for i, v in enumerate(values[cursor : cursor + checked])
                )
                seen = int(getattr(dut, signal).value) & ((1 << (checked * bits)) - 1)
                assert seen == expected, (case_index, cursor, signal)
            groups: list[tuple[int, int]] = []
            for fmt in formats[cursor : cursor + size]:
                if groups and groups[-1][0] == int(fmt):
                    groups[-1] = (int(fmt), groups[-1][1] + 1)
                else:
                    groups.append((int(fmt), 1))
            cost = sum(4 + 4 * ((n * widths[fmt] + 3) // 4) for fmt, n in groups)
            assert cost <= mtu - 42
            held = tuple(int(getattr(dut, name).value) for name in outputs)
            for _ in range(rng.randrange(4)):
                await RisingEdge(dut.clk)
                await FallingEdge(dut.clk)
                await ReadOnly()
                assert tuple(int(getattr(dut, name).value) for name in outputs) == held
            await FallingEdge(dut.clk)
            dut.m_ready.value = 1
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            dut.m_ready.value = 0
            cursor += size


@cocotb.test()
async def fp32_group_replaces_lane_formats_only_when_cheaper(dut: Any) -> None:
    """An eligible tile is sent as one FP32 group exactly when that costs fewer bytes."""
    from itertools import groupby

    lanes = len(dut.s_keep)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    for name in (
        "s_clear",
        "s_first_element",
        "s_keep",
        "s_formats",
        "s_native_bits",
        "s_fp32_bits",
        "s_fp32_eligible",
        "s_tags",
        "s_integers",
        "s_error",
        "s_valid",
    ):
        getattr(dut, name).value = 0
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = len(dut.s_integers) // lanes
    dut.m_ready.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    rng = random.Random(0xF32)
    widths = {
        ConcreteFormat.INT8: 1,
        ConcreteFormat.FP16: 2,
        ConcreteFormat.BF16: 2,
        ConcreteFormat.FP32: 4,
    }
    options = tuple(widths)

    def body_bytes(values: list[ConcreteFormat]) -> int:
        return sum(
            4 + 4 * ((len(tuple(run)) * widths[fmt] + 3) // 4) for fmt, run in groupby(values)
        )

    grouped = kept = 0
    for case_index in range(240):
        count = rng.choice((lanes, rng.randint(1, lanes), rng.randint(1, 4)))
        run_length = rng.choice((1, 1, 2, 3, 5, lanes))
        formats = [options[rng.randrange(len(options))]] * count
        for start in range(0, count, run_length):
            formats[start : start + run_length] = [rng.choice(options)] * len(
                formats[start : start + run_length]
            )
        native = [rng.getrandbits(32) for _ in range(count)]
        fp32 = [rng.getrandbits(32) for _ in range(count)]
        eligible = rng.random() < 0.7
        dut.s_first_element.value = case_index * lanes
        dut.s_keep.value = (1 << count) - 1
        dut.s_formats.value = sum(int(fmt) << (i * 8) for i, fmt in enumerate(formats))
        dut.s_native_bits.value = sum(value << (i * 32) for i, value in enumerate(native))
        dut.s_fp32_bits.value = sum(value << (i * 32) for i, value in enumerate(fp32))
        dut.s_fp32_eligible.value = int(eligible)
        dut.s_valid.value = 1
        await ReadOnly()
        assert int(dut.s_ready.value)
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0
        await segment(dut)
        assert not int(dut.m_fault.value)
        use_group = eligible and 4 + 4 * count < body_bytes(formats)
        grouped += use_group
        kept += not use_group
        expected_formats = [ConcreteFormat.FP32] * count if use_group else formats
        expected_values = fp32 if use_group else native
        mask = (1 << (count * 32)) - 1
        assert int(dut.m_count.value) == count, case_index
        assert int(dut.m_first_element.value) == case_index * lanes
        assert int(dut.m_formats.value) == sum(
            int(fmt) << (i * 8) for i, fmt in enumerate(expected_formats)
        ), (case_index, use_group)
        assert int(dut.m_native_bits.value) & mask == sum(
            value << (i * 32) for i, value in enumerate(expected_values)
        ), (case_index, use_group)
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    assert grouped >= 20 and kept >= 20, (grouped, kept)


@cocotb.test()
async def tiles_offered_back_to_back_leave_in_order_at_one_segment_per_cycle(dut: Any) -> None:
    """Several tiles are cut at the same time; their segments still leave in tile order.

    The last tiles put exact values where a tile yields the most segments.
    They must leave at one segment per cycle, which is what the reader can read.
    """
    lanes = len(dut.s_keep)
    integer_width = len(dut.s_integers) // lanes
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    for name in (
        "s_clear",
        "s_first_element",
        "s_keep",
        "s_formats",
        "s_native_bits",
        "s_fp32_bits",
        "s_fp32_eligible",
        "s_tags",
        "s_integers",
        "s_error",
        "s_valid",
        "m_ready",
    ):
        getattr(dut, name).value = 0
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = integer_width
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    rng = random.Random(0x0DE2)
    widths = {
        int(ConcreteFormat.INT8): 1,
        int(ConcreteFormat.FP16): 2,
        int(ConcreteFormat.BF16): 2,
        int(ConcreteFormat.FP32): 4,
        int(ConcreteFormat.KULISCH): 1 + (integer_width + 7) // 8,
    }
    narrow = (ConcreteFormat.INT8, ConcreteFormat.FP16, ConcreteFormat.BF16, ConcreteFormat.FP32)
    tiles: list[list[ConcreteFormat]] = []
    for _ in range(160):
        count = rng.choice((lanes, lanes, lanes, rng.randint(1, lanes)))
        exact_share = rng.choice((0.0, 0.02, 0.05, 0.2, 1.0))
        tiles.append(
            [
                ConcreteFormat.KULISCH if rng.random() < exact_share else rng.choice(narrow)
                for _ in range(count)
            ]
        )
    steady = 96
    tiles.extend(
        [
            ConcreteFormat.KULISCH if lane and lane % 16 == 0 else ConcreteFormat.INT8
            for lane in range(lanes)
        ]
        for _ in range(steady)
    )
    natives = [[rng.getrandbits(32) for _ in tile] for tile in tiles]
    integers = [[rng.getrandbits(integer_width - 1) for _ in tile] for tile in tiles]
    expected = []
    for index, tile in enumerate(tiles):
        cursor = 0
        for size in segment_sizes(tile, 1500 - 42, widths):
            expected.append((index, cursor, size))
            cursor += size
    steady_segments = steady * len(segment_sizes(tiles[-1], 1500 - 42, widths))

    async def drive() -> None:
        for index, tile in enumerate(tiles):
            await FallingEdge(dut.clk)
            dut.s_first_element.value = index * lanes
            dut.s_keep.value = (1 << len(tile)) - 1
            for signal, values, bits in (
                ("s_formats", tile, 8),
                ("s_native_bits", natives[index], 32),
                ("s_integers", integers[index], integer_width),
            ):
                getattr(dut, signal).value = sum(int(v) << (i * bits) for i, v in enumerate(values))
            dut.s_valid.value = 1
            while True:
                await ReadOnly()
                ready = int(dut.s_ready.value)
                await RisingEdge(dut.clk)
                if ready:
                    break
                await FallingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_valid.value = 0

    cocotb.start_soon(drive())
    seen = 0
    cycle = 0
    steady_start = len(expected) - steady_segments
    steady_first = None
    while seen < len(expected):
        await FallingEdge(dut.clk)
        # The first tiles meet a consumer that stalls, the steady ones do not.
        dut.m_ready.value = int(seen >= steady_start - 64 or rng.random() < 0.7)
        await ReadOnly()
        cycle += 1
        assert cycle < 40000, f"only {seen} of {len(expected)} segments"
        assert not int(dut.m_fault.value)
        if int(dut.m_valid.value) and int(dut.m_ready.value):
            index, cursor, size = expected[seen]
            assert int(dut.m_count.value) == size, (seen, index, cursor, tiles[index])
            assert int(dut.m_first_element.value) == index * lanes + cursor, (seen, index)
            assert int(dut.m_formats.value) == sum(
                int(v) << (i * 8) for i, v in enumerate(tiles[index][cursor : cursor + size])
            ), (seen, index, cursor)
            assert int(dut.m_native_bits.value) & ((1 << (size * 32)) - 1) == sum(
                v << (i * 32) for i, v in enumerate(natives[index][cursor : cursor + size])
            ), (seen, index, cursor)
            checked = min(size, 16)
            assert int(dut.m_integers.value) & ((1 << (checked * integer_width)) - 1) == sum(
                v << (i * integer_width)
                for i, v in enumerate(integers[index][cursor : cursor + checked])
            ), (seen, index, cursor)
            if seen == steady_start + 32:
                steady_first = cycle
            seen += 1
        await RisingEdge(dut.clk)
    assert steady_first is not None
    steady_cycles = cycle - steady_first
    measured = steady_segments - 32 - 1
    dut._log.info(
        "%d lanes: %d segments of %d tiles; steady part %d segments in %d cycles",
        lanes,
        len(expected),
        len(tiles),
        measured,
        steady_cycles,
    )
    if lanes > 16:
        assert steady_cycles <= measured + 2, (measured, steady_cycles)
