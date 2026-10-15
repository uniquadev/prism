"""Exact partial tiles use lossless Auto NumberGroups at streaming rate."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, encode_kulisch
from prism_ccl.wire.data import NumberGroup, decode_data_frame

from .numbergroup_frame_fixture import frame
from .test_numbergroup_mixed_tile_cocotb import receive


async def initialize(dut: Any, *, mtu: int, total: int, start_clock: bool = True) -> None:
    if start_clock:
        cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_header_beat.value = int.from_bytes(
        frame(90, 0, (NumberGroup(ConcreteFormat.FP32, (0,)),), last=False)[:64],
        "little",
    )
    dut.s_total_elements.value = total
    dut.s_mtu.value = mtu
    dut.s_kulisch_bits.value = 320
    dut.s_tile_first_element.value = 0
    dut.s_tile_keep.value = 0
    dut.s_native_input.value = 0
    dut.s_tile_native_bits.value = 0
    dut.s_tile_tags.value = 0
    dut.s_tile_integers.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


@cocotb.test()
async def mixed_exact_tile_selects_five_lossless_formats(dut: Any) -> None:
    await initialize(dut, mtu=576, total=5)
    integers = (
        7 << 149,
        3 << 148,
        1 << 169,
        (1 << 149) + (1 << 126),
        (1 << 149) + 1,
    )
    expected = (
        NumberGroup(ConcreteFormat.INT8, (7,)),
        NumberGroup(ConcreteFormat.FP16, (0x3E00,)),
        NumberGroup(ConcreteFormat.BF16, (0x4980,)),
        NumberGroup(ConcreteFormat.FP32, (0x3F800001,)),
        NumberGroup(
            ConcreteFormat.KULISCH,
            (
                encode_kulisch(
                    ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320
                ),
            ),
        ),
    )
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 0x1F
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = sum(
            value << (320 * lane) for lane, value in enumerate(integers)
        )
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("Auto partial sender did not accept the tile")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    actual = await receiver
    assert actual == [frame(90, 0, expected, last=True)]


@cocotb.test()
async def rounded_fp32_partial_auto_encodes_only_the_rounded_values(dut: Any) -> None:
    await initialize(dut, mtu=576, total=16)
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_native_input.value = 1
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 0xFFFF
        dut.s_tile_native_bits.value = sum(
            (0 if lane % 2 == 0 else 0x3FC00000) << (32 * lane) for lane in range(16)
        )
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = 0
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("rounded FP32 partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    actual = await receiver
    assert actual == [
        frame(
            90,
            0,
            tuple(
                NumberGroup(ConcreteFormat.INT8, (0,))
                if lane % 2 == 0
                else NumberGroup(ConcreteFormat.FP16, (0x3E00,))
                for lane in range(16)
            ),
            last=True,
        )
    ]


@cocotb.test()
async def wider_wire_sign_extends_a_representable_exact_partial(dut: Any) -> None:
    await initialize(dut, mtu=576, total=1)
    dut.s_kulisch_bits.value = 4096
    exact = (1 << 149) + 1
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 1
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = exact
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("wide partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    assert len(frames[0]) <= 576
    packet = decode_data_frame(frames[0], mtu=576, kulisch_bits=4096)
    assert packet.last and packet.element_count == 1
    assert packet.groups == (
        NumberGroup(
            ConcreteFormat.KULISCH,
            (
                encode_kulisch(
                    ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 4096
                ),
            ),
        ),
    )


@cocotb.test()
async def wider_wire_sign_extends_a_negative_exact_partial(dut: Any) -> None:
    await initialize(dut, mtu=576, total=1)
    dut.s_kulisch_bits.value = 4096
    exact = (1 << 149) + 1
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 1
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = (-exact) & ((1 << 320) - 1)
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("negative wide partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    packet = decode_data_frame(frames[0], mtu=576, kulisch_bits=4096)
    assert packet.last and packet.element_count == 1
    assert packet.groups == (
        NumberGroup(
            ConcreteFormat.KULISCH,
            (encode_kulisch(ExactValue("finite", True, -Fraction(exact, 1 << 149)), 4096),),
        ),
    )


@cocotb.test()
async def narrower_wire_preserves_both_signed_exact_partials(dut: Any) -> None:
    await initialize(dut, mtu=576, total=2)
    dut.s_kulisch_bits.value = 279
    exact = (1 << 149) + 1
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 3
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = exact | (((-exact) & ((1 << 320) - 1)) << 320)
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("narrow partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    packet = decode_data_frame(frames[0], mtu=576, kulisch_bits=279)
    assert packet.last and packet.element_count == 2
    assert packet.groups == (
        NumberGroup(
            ConcreteFormat.KULISCH,
            (
                encode_kulisch(ExactValue("finite", False, Fraction(exact, 1 << 149)), 279),
                encode_kulisch(ExactValue("finite", True, Fraction(-exact, 1 << 149)), 279),
            ),
        ),
    )


@cocotb.test()
async def narrow_wire_reports_an_unrepresentable_partial(dut: Any) -> None:
    await initialize(dut, mtu=576, total=1)
    dut.s_kulisch_bits.value = 279
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 1
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = 1 << 300
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(100):
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value):
            break
    else:
        raise AssertionError("arithmetic error did not produce a terminal DATA frame")
    snapshot = (
        int(dut.m_axis_tdata.value),
        int(dut.m_axis_tkeep.value),
        int(dut.m_packet_id.value),
    )
    for _ in range(4):
        await RisingEdge(dut.clk)
        assert int(dut.m_axis_tvalid.value)
        assert (
            int(dut.m_axis_tdata.value),
            int(dut.m_axis_tkeep.value),
            int(dut.m_packet_id.value),
        ) == snapshot
    await FallingEdge(dut.clk)
    dut.m_axis_tready.value = 1
    await ReadOnly()
    assert int(dut.m_last_frame_done.value)
    await RisingEdge(dut.clk)
    payload = snapshot[0].to_bytes(64, "little")[:60]
    packet = decode_data_frame(payload, mtu=576, kulisch_bits=279)
    assert packet.accumulation_inexact and packet.last and not packet.groups


@cocotb.test()
async def arithmetic_error_follows_an_already_transmitted_partial_frame(dut: Any) -> None:
    await initialize(dut, mtu=576, total=17)
    dut.s_kulisch_bits.value = 279
    dut.m_axis_tready.value = 1
    frames: list[bytes] = []
    pending = bytearray()
    accepted_beats = 0

    async def collect() -> None:
        nonlocal accepted_beats
        while len(frames) < 2:
            await RisingEdge(dut.clk)
            if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
                accepted_beats += 1
                keep = int(dut.m_axis_tkeep.value)
                pending.extend(
                    int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()]
                )
                if int(dut.m_axis_tlast.value):
                    frames.append(bytes(pending))
                    pending.clear()

    watcher = cocotb.start_soon(collect())
    exact = (1 << 149) + 1
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 0xFFFF
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = sum(exact << (320 * lane) for lane in range(16))
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("first partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(300):
        await RisingEdge(dut.clk)
        if accepted_beats:
            break
    else:
        raise AssertionError("first partial frame did not start transmission")
    assert not frames

    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 16
        dut.s_tile_keep.value = 1
        dut.s_tile_integers.value = 1 << 300
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("overflowing partial tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(300):
        await RisingEdge(dut.clk)
        if len(frames) == 2:
            break
    else:
        raise AssertionError("terminal error frame did not follow the partial")
    watcher.cancel()
    first, error = (decode_data_frame(data, mtu=576, kulisch_bits=279) for data in frames)
    assert first.element_count > 0 and not first.last
    assert error.accumulation_inexact and error.last and not error.groups
    assert error.packet_id == first.packet_id + 1


@cocotb.test()
async def descriptor_cost_coalesces_alternating_narrow_values(dut: Any) -> None:
    await initialize(dut, mtu=576, total=16)
    integers = tuple(1 << 149 if lane % 2 == 0 else 3 << 148 for lane in range(16))
    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = 0
        dut.s_tile_keep.value = 0xFFFF
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = sum(
            value << (320 * lane) for lane, value in enumerate(integers)
        )
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("coalescing tile was not accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    actual = await receiver
    expected = frame(
        90,
        0,
        (
            NumberGroup(
                ConcreteFormat.FP32,
                tuple(0x3F800000 if lane % 2 == 0 else 0x3FC00000 for lane in range(16)),
            ),
        ),
        last=True,
    )
    assert actual == [expected]


@cocotb.test()
async def fp32_auto_partials_sustain_numeric_line_rate(dut: Any) -> None:
    total = 4096
    await initialize(dut, mtu=1500, total=total)
    value = (1 << 149) + (1 << 126)
    tile = sum(value << (320 * lane) for lane in range(16))
    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, 12, stall=False, metrics=metrics))
    accepted = 0
    first_ns = None
    for _ in range(4000):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = accepted * 16
        dut.s_tile_keep.value = 0xFFFF
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = tile
        dut.s_tile_valid.value = int(accepted < 256)
        await ReadOnly()
        if accepted < 256 and int(dut.s_tile_ready.value):
            if first_ns is None:
                first_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted == 256:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"only {accepted} of 256 Auto tiles were accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
    assert sum(packet.element_count for packet in packets) == total
    assert all(len(packet.groups) == 1 for packet in packets)
    assert all(
        group.format == ConcreteFormat.FP32 and all(value == 0x3F800001 for value in group.values)
        for packet in packets
        for group in packet.groups
    )
    assert first_ns is not None
    # Sustained output rate from the first to the last beat. The cycles from
    # the first tile to the first beat are latency, limited separately.
    total_cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
    cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
    numeric_gbps = total * 32 * 0.25 / cycles
    frame_gbps = sum(map(len, frames)) * 8 * 0.25 / cycles
    dut._log.info(
        "AUTO partial FP32 numeric %.2f Gb/s; AXI frame %.2f Gb/s; "
        "%.2f M elements/s; %d beats in %d cycles, first beat after %d",
        numeric_gbps,
        frame_gbps,
        total * 250 / cycles,
        metrics["beats"],
        cycles,
        total_cycles - cycles,
    )
    assert numeric_gbps >= 100
    assert total_cycles - cycles <= 96


@cocotb.test()
async def uniform_auto_partial_formats_preserve_values_and_report_rates(dut: Any) -> None:
    total = 4096
    cases = (
        ("int8", 7 << 149, ConcreteFormat.INT8, 7, 8),
        ("fp16", 3 << 148, ConcreteFormat.FP16, 0x3E00, 16),
        ("bf16", 1 << 169, ConcreteFormat.BF16, 0x4980, 16),
        (
            "kulisch",
            (1 << 149) + 1,
            ConcreteFormat.KULISCH,
            encode_kulisch(ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320),
            320,
        ),
    )
    for case_index, (name, integer, wire_format, expected_value, bits) in enumerate(cases):
        if case_index:
            await FallingEdge(dut.clk)
        await initialize(dut, mtu=1500, total=total, start_clock=case_index == 0)
        tile = sum(integer << (320 * lane) for lane in range(16))
        metrics: dict[str, int] = {}
        receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
        accepted = 0
        first_ns = None
        for _ in range(12000):
            await FallingEdge(dut.clk)
            dut.s_tile_first_element.value = accepted * 16
            dut.s_tile_keep.value = 0xFFFF
            dut.s_tile_tags.value = 0
            dut.s_tile_integers.value = tile
            dut.s_tile_valid.value = int(accepted < 256)
            await ReadOnly()
            if accepted < 256 and int(dut.s_tile_ready.value):
                if first_ns is None:
                    first_ns = int(get_sim_time(unit="ns"))
                accepted += 1
            if accepted == 256:
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"{name}: only {accepted} of 256 Auto tiles were accepted")
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = 0
        frames = await receiver
        packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
        assert sum(packet.element_count for packet in packets) == total
        assert all(len(packet.groups) == 1 for packet in packets)
        assert all(
            group.format == wire_format and all(value == expected_value for value in group.values)
            for packet in packets
            for group in packet.groups
        )
        assert first_ns is not None
        cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
        numeric_gbps = total * bits * 0.25 / cycles
        frame_gbps = sum(map(len, frames)) * 8 * 0.25 / cycles
        dut._log.info(
            "AUTO partial %s numeric %.2f Gb/s; AXI frame %.2f Gb/s; %.2f M elements/s",
            name,
            numeric_gbps,
            frame_gbps,
            total * 250 / cycles,
        )
        # This 16-lane case checks lossless encoding. The sustained rate gate
        # uses the 128-lane sender fed by the exact-bank producer.


@cocotb.test()
async def mixed_auto_partials_keep_the_axi_frame_path_busy(dut: Any) -> None:
    total = 4096
    await initialize(dut, mtu=1500, total=total)
    fp32 = (1 << 149) + (1 << 126)
    exact = (1 << 149) + 1
    tile = sum((fp32 if lane % 2 == 0 else exact) << (320 * lane) for lane in range(16))
    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, 86, stall=False, metrics=metrics))
    accepted = 0
    first_ns = None
    for _ in range(12000):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = accepted * 16
        dut.s_tile_keep.value = 0xFFFF
        dut.s_tile_tags.value = 0
        dut.s_tile_integers.value = tile
        dut.s_tile_valid.value = int(accepted < 256)
        await ReadOnly()
        if accepted < 256 and int(dut.s_tile_ready.value):
            if first_ns is None:
                first_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted == 256:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"only {accepted} of 256 mixed Auto tiles were accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    packets = [decode_data_frame(payload, mtu=1500, kulisch_bits=320) for payload in frames]
    assert sum(packet.element_count for packet in packets) == total
    assert [packet.first_element for packet in packets] == list(range(0, total, 48))
    assert packets[-1].last
    for packet in packets:
        values = tuple((group.format, value) for group in packet.groups for value in group.values)
        assert len(values) == packet.element_count
        for offset, (fmt, value) in enumerate(values):
            if (packet.first_element + offset) % 2 == 0:
                assert fmt == ConcreteFormat.FP32 and value == 0x3F800001
            else:
                assert fmt == ConcreteFormat.KULISCH
                assert value == encode_kulisch(
                    ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320
                )
    assert first_ns is not None
    cycles = (metrics["last_output_ns"] - first_ns) // 4 + 1
    frame_gbps = sum(map(len, frames)) * 8 * 0.25 / cycles
    numeric_gbps = total * (32 + 320) // 2 * 0.25 / cycles
    dut._log.info(
        "AUTO mixed partial numeric %.2f Gb/s; AXI frame %.2f Gb/s; "
        "%.2f M elements/s; %d beats in %d cycles",
        numeric_gbps,
        frame_gbps,
        total * 250 / cycles,
        metrics["beats"],
        cycles,
    )
    assert frame_gbps >= 100
