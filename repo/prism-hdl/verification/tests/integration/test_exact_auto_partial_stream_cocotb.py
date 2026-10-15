"""An exact bank, not an ideal tile source, feeds mixed AUTO partial DATA."""

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

from tests.unit.numbergroup_frame_fixture import frame
from tests.unit.test_numbergroup_mixed_tile_cocotb import receive


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_header_beat.value = int.from_bytes(
        frame(90, 0, (NumberGroup(ConcreteFormat.FP32, (0,)),), last=False)[:64],
        "little",
    )
    dut.s_total_elements.value = 4096
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = 320
    dut.s_first_element.value = 0
    dut.s_bits.value = 0
    dut.s_keep.value = 0
    dut.s_valid.value = 0
    dut.s_read_slot.value = 0
    dut.s_read_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def submit_tile(dut: Any, first: int, bits: int) -> None:
    for _ in range(1000):
        await FallingEdge(dut.clk)
        dut.s_first_element.value = first
        dut.s_bits.value = bits
        dut.s_keep.value = (1 << 64) - 1
        dut.s_valid.value = 1
        await ReadOnly()
        if int(dut.s_ready.value):
            await RisingEdge(dut.clk)
            return
    raise AssertionError(f"exact bank did not accept tile at {first}")


@cocotb.test()
async def real_exact_bank_sustains_mixed_auto_partial_frames(dut: Any) -> None:
    await initialize(dut)
    fp32_even = 0x3F800001  # 1 + 2^-23: FP32 but not FP16/BF16.
    fp32_odd = 0x3F800000
    min_subnormal = 0x00000001
    first_pass = sum(
        (fp32_even if lane % 2 == 0 else fp32_odd) << (lane * 32) for lane in range(16)
    )
    second_pass = sum((0 if lane % 2 == 0 else min_subnormal) << (lane * 32) for lane in range(16))
    for bits in (first_pass, second_pass):
        for tile in range(256):
            await submit_tile(dut, tile * 16, bits)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(48):
        await RisingEdge(dut.clk)

    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
    accepted = 0
    first_read_ns: int | None = None
    for _ in range(5000):
        await FallingEdge(dut.clk)
        dut.s_read_slot.value = accepted
        dut.s_read_valid.value = int(accepted < 32)
        await ReadOnly()
        if accepted < 32 and int(dut.s_read_ready.value):
            if first_read_ns is None:
                first_read_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted == 32:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"exact bank accepted only {accepted}/32 wide reads")
    await FallingEdge(dut.clk)
    dut.s_read_valid.value = 0
    frames = await receiver
    assert first_read_ns is not None

    expected_kulisch = encode_kulisch(
        ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320
    )
    next_element = 0
    for packet_index, raw in enumerate(frames):
        packet = decode_data_frame(raw, mtu=1500, kulisch_bits=320)
        assert packet.first_element == next_element
        assert packet.packet_id == 90 + packet_index
        for group in packet.groups:
            for value in group.values:
                if next_element % 2 == 0:
                    assert group.format == ConcreteFormat.FP32 and value == fp32_even
                else:
                    assert group.format == ConcreteFormat.KULISCH and value == expected_kulisch
                next_element += 1
    assert next_element == 4096
    assert decode_data_frame(frames[-1], mtu=1500, kulisch_bits=320).last
    assert all(not decode_data_frame(raw, mtu=1500, kulisch_bits=320).last for raw in frames[:-1])

    frame_bits = sum(len(raw) * 8 for raw in frames)
    numeric_bits = 4096 * (32 + 320) // 2
    cycles = (metrics["last_output_ns"] - first_read_ns) // 4 + 1
    frame_gbps = frame_bits / (cycles * 4)
    numeric_gbps = numeric_bits / (cycles * 4)
    numeric_ceiling = 128 * numeric_bits / frame_bits
    dut._log.info(
        "bank-to-partial mixed AUTO: AXI frame %.2f Gb/s, numeric %.2f Gb/s "
        "(ceiling %.2f), %.2f M elements/s, %d cycles",
        frame_gbps,
        numeric_gbps,
        numeric_ceiling,
        4096 * 250 / cycles,
        cycles,
    )
    assert frame_gbps >= 120
    assert numeric_gbps >= 0.95 * numeric_ceiling


async def check_uniform_bank_to_partial_rate(
    dut: Any,
    fp32_bits: int,
    wire_format: ConcreteFormat,
    expected_value: int,
    bits: int,
    second_fp32_bits: int | None = None,
) -> None:
    await initialize(dut)
    contributions = (fp32_bits,) if second_fp32_bits is None else (fp32_bits, second_fp32_bits)
    for contribution in contributions:
        tile_bits = sum(contribution << (lane * 32) for lane in range(16))
        for tile in range(256):
            await submit_tile(dut, tile * 16, tile_bits)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(48):
        await RisingEdge(dut.clk)

    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
    accepted = 0
    first_read_ns: int | None = None
    for _ in range(5000):
        await FallingEdge(dut.clk)
        dut.s_read_slot.value = accepted
        dut.s_read_valid.value = int(accepted < 32)
        await ReadOnly()
        if accepted < 32 and int(dut.s_read_ready.value):
            if first_read_ns is None:
                first_read_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted == 32:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"exact bank accepted only {accepted}/32 wide reads")
    await FallingEdge(dut.clk)
    dut.s_read_valid.value = 0
    frames = await receiver
    assert first_read_ns is not None

    next_element = 0
    for packet_index, raw in enumerate(frames):
        packet = decode_data_frame(raw, mtu=1500, kulisch_bits=320)
        assert packet.first_element == next_element
        assert packet.packet_id == 90 + packet_index
        assert all(
            group.format == wire_format and all(value == expected_value for value in group.values)
            for group in packet.groups
        )
        next_element += packet.element_count
        assert packet.last == (next_element == 4096)
    assert next_element == 4096

    # Sustained output rate from the first to the last beat. The cycles from
    # the first read to the first beat are latency, limited separately.
    cycles = (metrics["last_output_ns"] - first_read_ns) // 4 + 1
    burst_cycles = (metrics["last_output_ns"] - metrics["first_output_ns"]) // 4 + 1
    numeric_gbps = 4096 * bits / (burst_cycles * 4)
    frame_gbps = sum(len(raw) * 8 for raw in frames) / (burst_cycles * 4)
    dut._log.info(
        "bank-to-partial uniform %s: numeric %.2f Gb/s, AXI frame %.2f Gb/s, "
        "%.2f M elements/s, %d cycles; first-output +%d cycles, %d frames, %d beats",
        wire_format.name,
        numeric_gbps,
        frame_gbps,
        4096 * 250 / cycles,
        cycles,
        (metrics["first_output_ns"] - first_read_ns) // 4,
        len(frames),
        metrics["beats"],
    )
    assert numeric_gbps >= 100
    assert cycles - burst_cycles <= 96


@cocotb.test()
async def exact_bank_sustains_uniform_int8_auto_partial(dut: Any) -> None:
    await check_uniform_bank_to_partial_rate(dut, 0x40E00000, ConcreteFormat.INT8, 7, 8)


@cocotb.test()
async def exact_bank_sustains_uniform_fp16_auto_partial(dut: Any) -> None:
    await check_uniform_bank_to_partial_rate(dut, 0x3F802000, ConcreteFormat.FP16, 0x3C01, 16)


@cocotb.test()
async def exact_bank_sustains_uniform_bf16_auto_partial(dut: Any) -> None:
    await check_uniform_bank_to_partial_rate(dut, 0x47800000, ConcreteFormat.BF16, 0x4780, 16)


@cocotb.test()
async def exact_bank_sustains_uniform_fp32_auto_partial(dut: Any) -> None:
    await check_uniform_bank_to_partial_rate(dut, 0x3F800001, ConcreteFormat.FP32, 0x3F800001, 32)


@cocotb.test()
async def exact_bank_sustains_uniform_kulisch_auto_partial(dut: Any) -> None:
    exact = encode_kulisch(ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 149)), 320)
    await check_uniform_bank_to_partial_rate(
        dut, 0x3F800000, ConcreteFormat.KULISCH, exact, 320, 0x00000001
    )


@cocotb.test()
async def exact_bank_to_partial_sender_survives_output_backpressure(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 128
    one_tile = sum(0x3F800000 << (lane * 32) for lane in range(16))
    for tile in range(8):
        await submit_tile(dut, tile * 16, one_tile)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(48):
        await RisingEdge(dut.clk)

    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_read_slot.value = 0
        dut.s_read_valid.value = 1
        await ReadOnly()
        if int(dut.s_read_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("exact bank did not accept wide read")
    await FallingEdge(dut.clk)
    dut.s_read_valid.value = 0
    assert await receiver == [
        frame(90, 0, (NumberGroup(ConcreteFormat.INT8, (1,) * 128),), last=True)
    ]


@cocotb.test()
async def narrow_wire_width_reports_exact_bank_overflow_as_terminal_data(dut: Any) -> None:
    await initialize(dut)
    dut.s_total_elements.value = 16
    dut.s_kulisch_bits.value = 279
    maximal = sum(0x7F7FFFFF << (lane * 32) for lane in range(16))
    for _ in range(3):
        await submit_tile(dut, 0, maximal)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(48):
        await RisingEdge(dut.clk)

    receiver = cocotb.start_soon(receive(dut, 1, stall=True))
    for _ in range(100):
        await FallingEdge(dut.clk)
        dut.s_read_slot.value = 0
        dut.s_read_valid.value = 1
        await ReadOnly()
        if int(dut.s_read_ready.value):
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("exact bank did not accept overflow read")
    await FallingEdge(dut.clk)
    dut.s_read_valid.value = 0
    frames = await receiver
    assert len(frames) == 1
    packet = decode_data_frame(frames[0], mtu=1500, kulisch_bits=279)
    assert packet.accumulation_inexact and packet.last
    assert packet.element_count == 0 and not packet.groups
