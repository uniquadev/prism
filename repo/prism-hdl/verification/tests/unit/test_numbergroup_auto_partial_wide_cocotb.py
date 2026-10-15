"""A wide source exercises the shared Auto partial packet path."""

from __future__ import annotations

import random
from fractions import Fraction
from typing import Any

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, decode_kulisch, decode_native, encode_kulisch
from prism_ccl.wire.data import NumberGroup, decode_data_frame

from .test_numbergroup_auto_partial_cocotb import initialize
from .test_numbergroup_mixed_tile_cocotb import frame, receive

# Cycles from the first input tile to the first output beat: a guard against
# latency growing unnoticed, not a rate.
FIRST_OUTPUT_LIMIT = 96


@cocotb.test()
async def uniform_wide_auto_partials_sustain_numeric_output_rate(dut: Any) -> None:
    total = 4096
    lanes = len(dut.s_tile_keep)
    tile_total = total // lanes
    cases = (
        ("int8", 7 << 149, ConcreteFormat.INT8, 7, 8),
        ("fp16", 3 << 148, ConcreteFormat.FP16, 0x3E00, 16),
        ("bf16", 1 << 169, ConcreteFormat.BF16, 0x4980, 16),
        ("fp32", (1 << 149) + (1 << 126), ConcreteFormat.FP32, 0x3F800001, 32),
        (
            "kulisch",
            (1 << 149) + 1,
            ConcreteFormat.KULISCH,
            encode_kulisch(ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320),
            320,
        ),
    )
    shortfalls: list[str] = []
    for case_index, (name, integer, wire_format, expected_value, bits) in enumerate(cases):
        if case_index:
            await FallingEdge(dut.clk)
        await initialize(dut, mtu=1500, total=total, start_clock=case_index == 0)
        packed = sum(integer << (320 * lane) for lane in range(lanes))
        metrics: dict[str, int] = {}
        receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
        accepted = 0
        first_ns = None
        last_input_ns = None
        input_stalls = 0
        for _ in range(5000):
            await FallingEdge(dut.clk)
            dut.s_tile_first_element.value = accepted * lanes
            dut.s_tile_keep.value = (1 << lanes) - 1
            dut.s_tile_tags.value = 0
            dut.s_tile_integers.value = packed
            dut.s_tile_valid.value = int(accepted < tile_total)
            await ReadOnly()
            if accepted < tile_total and int(dut.s_tile_ready.value):
                if first_ns is None:
                    first_ns = int(get_sim_time(unit="ns"))
                last_input_ns = int(get_sim_time(unit="ns"))
                accepted += 1
            elif accepted < tile_total:
                input_stalls += 1
            if accepted == tile_total:
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(
                f"{name}: only {accepted} of {tile_total} Auto tiles were accepted"
            )
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = 0
        frames = await receiver
        packets = []
        for frame_index, payload in enumerate(frames):
            try:
                packets.append(decode_data_frame(payload, mtu=1500, kulisch_bits=320))
            except ValueError:
                dut._log.error(
                    "invalid frame %d/%d length=%d header=%s body-prefix=%s",
                    frame_index,
                    len(frames),
                    len(payload),
                    payload[:56].hex(),
                    payload[56:104].hex(),
                )
                raise
        assert sum(packet.element_count for packet in packets) == total
        next_element = 0
        for packet in packets:
            assert packet.first_element == next_element
            next_element += packet.element_count
        assert packets[-1].last
        assert all(len(packet.groups) == 1 for packet in packets)
        assert all(
            group.format == wire_format and all(value == expected_value for value in group.values)
            for packet in packets
            for group in packet.groups
        )
        assert first_ns is not None and last_input_ns is not None
        cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
        burst_cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
        input_cycles = (last_input_ns - first_ns) // 4 + 1
        numeric_gbps = total * bits / (cycles * 4)
        burst_gbps = total * bits / (burst_cycles * 4)
        frame_gbps = sum(map(len, frames)) * 8 / (cycles * 4)
        frame_burst_gbps = sum(map(len, frames)) * 8 / (burst_cycles * 4)
        dut._log.info(
            "%d-lane AUTO partial %s input-to-last %.2f Gb/s; output burst %.2f Gb/s; "
            "AXI frame %.2f/%.2f Gb/s (total/burst); %.2f M elements/s; %d/%d/%d cycles "
            "(input/burst/total); %d input stalls",
            lanes,
            name,
            numeric_gbps,
            burst_gbps,
            frame_gbps,
            frame_burst_gbps,
            total * 250 / cycles,
            input_cycles,
            burst_cycles,
            cycles,
            input_stalls,
        )
        # The bound is the sustained rate of each stream: the output from its
        # first to its last beat, the input over the cycles it was offered.
        # The time to the first beat is latency and has its own limit.
        input_gbps = total * bits / (input_cycles * 4)
        if burst_gbps < 100:
            shortfalls.append(f"{name} output={burst_gbps:.2f} Gb/s")
        if lanes >= 128 and input_gbps < 100:
            shortfalls.append(f"{name} input={input_gbps:.2f} Gb/s")
        assert cycles - burst_cycles <= FIRST_OUTPUT_LIMIT, (name, cycles - burst_cycles)
    assert not shortfalls, "wide AUTO partial sustained rate: " + ", ".join(shortfalls)


@cocotb.test()
async def almost_uniform_native_auto_partials_sustain_axi_frame_rate(dut: Any) -> None:
    total = 4096
    lanes = len(dut.s_tile_keep)
    # The near-uniform rate target is defined for the 128-lane build only.
    if lanes != 128:
        return
    await initialize(dut, mtu=1500, total=total)
    int8_integer = 7 << 149
    fp16_integer = 3 << 148
    packed = sum(
        (fp16_integer if lane == lanes - 1 else int8_integer) << (320 * lane)
        for lane in range(lanes)
    )
    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
    accepted = 0
    first_input_ns = None
    for _ in range(5000):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = accepted * lanes
        dut.s_tile_keep.value = (1 << lanes) - 1
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = packed
        dut.s_tile_valid.value = int(accepted * lanes < total)
        await ReadOnly()
        if int(dut.s_tile_valid.value) and int(dut.s_tile_ready.value):
            if first_input_ns is None:
                first_input_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted * lanes == total:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"only {accepted} of {total // lanes} tiles accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
    values = [value for packet in packets for group in packet.groups for value in group.values]
    assert len(values) == total
    assert all(
        value == (0x3E00 if index % lanes == lanes - 1 else 7) for index, value in enumerate(values)
    )
    assert first_input_ns is not None
    cycles = (metrics["last_output_ns"] - first_input_ns) // 4 + 1
    burst_cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
    frame_gbps = sum(map(len, frames)) * 8 / (burst_cycles * 4)
    dut._log.info(
        "128-lane AUTO near-uniform INT8/FP16: AXI frame %.2f Gb/s; "
        "%d cycles, %d beats, frame sizes %s, first output +%d cycles",
        frame_gbps,
        cycles,
        metrics["beats"],
        [len(payload) for payload in frames],
        (metrics["first_output_ns"] - first_input_ns) // 4,
    )
    # Sustained output rate from the first to the last beat; the time to the
    # first beat is latency and has its own limit.
    assert frame_gbps >= 100
    assert cycles - burst_cycles <= FIRST_OUTPUT_LIMIT


@cocotb.test()
async def mixed_wide_auto_partials_sustain_axi_frame_rate(dut: Any) -> None:
    total = 4096
    lanes = len(dut.s_tile_keep)
    tile_total = total // lanes
    await initialize(dut, mtu=1500, total=total)
    fp32 = (1 << 149) + (1 << 126)
    exact = (1 << 149) + 1
    packed = sum((fp32 if lane % 2 == 0 else exact) << (320 * lane) for lane in range(lanes))
    expected_exact = encode_kulisch(
        ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320
    )
    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
    accepted = 0
    first_ns = None
    for _ in range(5000):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = accepted * lanes
        dut.s_tile_keep.value = (1 << lanes) - 1
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = packed
        dut.s_tile_valid.value = int(accepted < tile_total)
        await ReadOnly()
        if accepted < tile_total and int(dut.s_tile_ready.value):
            if first_ns is None:
                first_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted == tile_total:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"only {accepted} of {tile_total} mixed Auto tiles were accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
    assert sum(packet.element_count for packet in packets) == total
    assert packets[-1].last
    numeric_bits = 0
    next_element = 0
    for packet in packets:
        assert packet.first_element == next_element
        next_element += packet.element_count
        for offset, (fmt, value) in enumerate(
            (group.format, value) for group in packet.groups for value in group.values
        ):
            if (packet.first_element + offset) % 2 == 0:
                assert (fmt, value) == (ConcreteFormat.FP32, 0x3F800001)
                numeric_bits += 32
            else:
                assert (fmt, value) == (ConcreteFormat.KULISCH, expected_exact)
                numeric_bits += 320
    assert first_ns is not None
    total_cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
    burst_cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
    numeric_gbps = numeric_bits / (burst_cycles * 4)
    frame_gbps = sum(map(len, frames)) * 8 / (burst_cycles * 4)
    dut._log.info(
        "%d-lane AUTO mixed partial numeric %.2f Gb/s; AXI frame %.2f Gb/s; "
        "%.2f M elements/s; %d/%d cycles (burst/total)",
        lanes,
        numeric_gbps,
        frame_gbps,
        total * 250 / burst_cycles,
        burst_cycles,
        total_cycles,
    )
    assert frame_gbps >= 120


@cocotb.test()
async def wide_auto_partials_preserve_frames_under_output_backpressure(dut: Any) -> None:
    lanes = len(dut.s_tile_keep)
    await initialize(dut, mtu=1500, total=2 * lanes)
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    cases = (
        (7 << 149, 0),
        (3 << 148, lanes),
    )
    for integer, first in cases:
        for _ in range(300):
            await FallingEdge(dut.clk)
            dut.s_tile_first_element.value = first
            dut.s_tile_keep.value = (1 << lanes) - 1
            dut.s_tile_tags.value = 0
            dut.s_tile_integers.value = sum(integer << (320 * lane) for lane in range(lanes))
            dut.s_tile_valid.value = 1
            await ReadOnly()
            if int(dut.s_tile_ready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"{lanes}-lane tile at {first} was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    assert await receiver == [
        frame(
            90,
            0,
            (
                NumberGroup(ConcreteFormat.INT8, (7,) * lanes),
                NumberGroup(ConcreteFormat.FP16, (0x3E00,) * lanes),
            ),
            last=True,
        )
    ]


@cocotb.test()
async def wide_native_run_adjacent_to_kulisch_preserves_every_element(dut: Any) -> None:
    lanes = len(dut.s_tile_keep)
    if lanes != 128:
        return
    native = 7 << 149
    exact = (1 << 149) + 1
    exact_wire = encode_kulisch(
        ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320
    )
    for case_index, exact_index in enumerate((127, 0)):
        if case_index:
            await FallingEdge(dut.clk)
        await initialize(dut, mtu=1500, total=lanes, start_clock=case_index == 0)
        receiver = cocotb.start_soon(receive(dut, None, stall=False))
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = (1 << lanes) - 1
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = sum(
            (exact if lane == exact_index else native) << (320 * lane) for lane in range(lanes)
        )
        for _ in range(300):
            await FallingEdge(dut.clk)
            dut.s_tile_valid.value = 1
            await ReadOnly()
            if int(dut.s_tile_ready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"tile with Kulisch at {exact_index} was not accepted")
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = 0
        frames = await receiver
        packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
        assert packets[-1].last
        next_element = 0
        values = []
        for packet in packets:
            assert packet.first_element == next_element
            next_element += packet.element_count
            values.extend(
                (group.format, value) for group in packet.groups for value in group.values
            )
        assert next_element == lanes
        assert values == [
            (ConcreteFormat.KULISCH, exact_wire)
            if lane == exact_index
            else (ConcreteFormat.INT8, 7)
            for lane in range(lanes)
        ]


@cocotb.test()
async def sparse_exact_values_among_narrow_values_sustain_axi_frame_rate(dut: Any) -> None:
    """A few values per tile need the exact format; the frames still fill the link.

    Every tile holds INT8 values except at the listed lanes, whose values are
    exact in no narrower format. The last case is the tile with the fewest
    bytes per segment of all: four segments, the first without an exact value
    and the last with nothing else.
    """
    total = 4096
    lanes = len(dut.s_tile_keep)
    if lanes < 64:
        return
    tile_total = total // lanes
    narrow = 7 << 149
    exact = (1 << 149) + 1
    exact_wire = encode_kulisch(
        ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320
    )
    cases = (
        ("lane 0", (0,)),
        ("lane 17", (17,)),
        ("lane 40", (40,)),
        ("lanes 16, 33, 50", (16, 33, 50)),
        ("lanes 15, 16, 47, 48", (15, 16, 47, 48)),
        ("lanes 0, 16, 32, 48", (0, 16, 32, 48)),
        ("lanes 16, 32, 48", (16, 32, 48)),
        ("lanes 16, 32, 63", (16, 32, 63)),
    )
    shortfalls: list[str] = []
    for case_index, (name, exact_lanes) in enumerate(cases):
        if case_index:
            await FallingEdge(dut.clk)
        await initialize(dut, mtu=1500, total=total, start_clock=case_index == 0)
        packed = sum(
            (exact if lane in exact_lanes else narrow) << (320 * lane) for lane in range(lanes)
        )
        metrics: dict[str, int] = {}
        receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
        accepted = 0
        first_ns = None
        for _ in range(5000):
            await FallingEdge(dut.clk)
            dut.s_tile_first_element.value = accepted * lanes
            dut.s_tile_keep.value = (1 << lanes) - 1
            dut.s_tile_tags.value = 0
            dut.s_tile_integers.value = packed
            dut.s_tile_valid.value = int(accepted < tile_total)
            await ReadOnly()
            if accepted < tile_total and int(dut.s_tile_ready.value):
                if first_ns is None:
                    first_ns = int(get_sim_time(unit="ns"))
                accepted += 1
            if accepted == tile_total:
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"{name}: only {accepted} of {tile_total} tiles were accepted")
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = 0
        frames = await receiver
        packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
        assert packets[-1].last
        values = []
        next_element = 0
        for packet in packets:
            assert packet.first_element == next_element, name
            next_element += packet.element_count
            values.extend(
                (group.format, value) for group in packet.groups for value in group.values
            )
        assert values == [
            (ConcreteFormat.KULISCH, exact_wire)
            if index % lanes in exact_lanes
            else (ConcreteFormat.INT8, 7)
            for index in range(total)
        ], name
        assert first_ns is not None
        cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
        burst_cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
        frame_gbps = sum(map(len, frames)) * 8 / (burst_cycles * 4)
        dut._log.info(
            "%d-lane AUTO partial, exact values at %s: AXI frame %.2f Gb/s; %d frames, "
            "%d bytes, %d/%d cycles (burst/total)",
            lanes,
            name,
            frame_gbps,
            len(frames),
            sum(map(len, frames)),
            burst_cycles,
            cycles,
        )
        if frame_gbps < 100:
            shortfalls.append(f"{name}: {frame_gbps:.2f} Gb/s")
        if cycles - burst_cycles > FIRST_OUTPUT_LIMIT:
            shortfalls.append(f"{name}: first beat after {cycles - burst_cycles} cycles")
    assert not shortfalls, "sparse exact values: " + "; ".join(shortfalls)


@cocotb.test()
async def random_mixes_keep_every_value_through_every_segment_shape(dut: Any) -> None:
    """Tiles with any mix of the five formats arrive whole, at both MTU limits.

    Values are compared as numbers: a tile whose values are all exact in FP32
    may be sent as one FP32 group.
    """
    lanes = len(dut.s_tile_keep)
    if lanes < 64:
        return
    rng = random.Random(0x5EED + lanes)
    classes = (
        lambda: rng.randint(1, 100) << 149,
        lambda: 3 << 148,
        lambda: 1 << 169,
        lambda: (1 << 149) + (1 << 126),
    )
    for case_index, mtu in enumerate((1500, 576, 1500, 576)):
        tiles = []
        for _ in range(40):
            exact_share = rng.choice((0.0, 0.02, 0.05, 0.3, 1.0))
            run_length = rng.choice((1, 2, 3, 5, 17, lanes))
            tile = []
            while len(tile) < lanes:
                if rng.random() < exact_share:
                    tile.append((1 << 149) + rng.choice((1, 3)))
                else:
                    make = rng.choice(classes)
                    tile.extend(make() for _ in range(rng.randint(1, run_length)))
            tiles.append(tile[:lanes])
        tiles[-1] = tiles[-1][: rng.randint(1, lanes)]
        total = sum(map(len, tiles))
        if case_index:
            await FallingEdge(dut.clk)
        await initialize(dut, mtu=mtu, total=total, start_clock=case_index == 0)
        receiver = cocotb.start_soon(receive(dut, None, stall=case_index >= 2))
        first = 0
        for tile in tiles:
            for _ in range(2000):
                await FallingEdge(dut.clk)
                dut.s_tile_first_element.value = first
                dut.s_tile_keep.value = (1 << len(tile)) - 1
                dut.s_tile_tags.value = 0
                dut.s_tile_integers.value = sum(
                    value << (320 * lane) for lane, value in enumerate(tile)
                )
                dut.s_tile_valid.value = 1
                await ReadOnly()
                if int(dut.s_tile_ready.value):
                    await RisingEdge(dut.clk)
                    break
            else:
                raise AssertionError(f"tile at {first} was not accepted")
            first += len(tile)
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = 0
        frames = await receiver
        seen = []
        next_element = 0
        exact_groups = 0
        for payload in frames:
            assert len(payload) <= mtu + 14, (mtu, len(payload))
            packet = decode_data_frame(payload, mtu=mtu, kulisch_bits=320)
            assert packet.first_element == next_element, (case_index, next_element)
            next_element += packet.element_count
            for group in packet.groups:
                exact_groups += group.format == ConcreteFormat.KULISCH
                seen.extend(
                    decode_kulisch(value, 320)
                    if group.format == ConcreteFormat.KULISCH
                    else decode_native(value, group.format)
                    for value in group.values
                )
        expected = [
            ExactValue("finite", False, Fraction(value, 1 << 149))
            for tile in tiles
            for value in tile
        ]
        assert len(seen) == total, (case_index, len(seen), total)
        for index, (got, wanted) in enumerate(zip(seen, expected, strict=True)):
            assert got == wanted, (case_index, mtu, index, index % lanes)
        assert exact_groups > 0
        dut._log.info(
            "%d-lane AUTO partial, random mix %d at MTU %d: %d values in %d frames",
            lanes,
            case_index,
            mtu,
            total,
            len(frames),
        )


@cocotb.test()
async def tile_that_fits_only_without_its_descriptor_stays_in_the_frame(dut: Any) -> None:
    lanes = len(dut.s_tile_keep)
    if lanes != 64:
        return
    # At an MTU of 576 a frame body holds 534 bytes. Eight tiles of 64 INT8
    # values in one group take 4 + 512 of them; a ninth tile of 16 values
    # is 20 bytes with a descriptor of its own and 16 as part of the group.
    total = 8 * lanes + 16
    await initialize(dut, mtu=576, total=total)
    receiver = cocotb.start_soon(receive(dut, None, stall=False))
    dut.s_tile_tags.value = 0
    for tile in range(9):
        count = lanes if tile < 8 else 16
        dut.s_tile_first_element.value = tile * lanes
        dut.s_tile_keep.value = (1 << count) - 1
        dut.s_tile_integers.value = sum(
            ((tile + 1) << 149) << (320 * lane) for lane in range(count)
        )
        for _ in range(300):
            await FallingEdge(dut.clk)
            dut.s_tile_valid.value = 1
            await ReadOnly()
            if int(dut.s_tile_ready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"tile {tile} was not accepted")
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = 0
    frames = await receiver
    packets = [decode_data_frame(payload, mtu=576, kulisch_bits=320) for payload in frames]
    assert len(packets) == 1
    assert len(frames[0]) == 56 + 4 + total
    assert [(group.format, len(group.values)) for group in packets[0].groups] == [
        (ConcreteFormat.INT8, total)
    ]
    assert list(packets[0].groups[0].values) == [index // lanes + 1 for index in range(total)]
