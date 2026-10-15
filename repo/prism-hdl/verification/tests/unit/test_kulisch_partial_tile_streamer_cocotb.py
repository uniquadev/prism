"""Two-lane Kulisch partials sustain complete DATA frames at the AXI boundary."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import ExactValue, encode_kulisch
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
SOURCE = bytes.fromhex("66778899aabb")
DESTINATION = bytes.fromhex("001122334455")
WIDTH = 320
ELEMENTS = 4080
ELEMENTS_PER_FRAME = 12
TARGET_GBPS = 120.0
VALUE = encode_kulisch(ExactValue("finite", False, Fraction(1)), WIDTH)


def expected_frames() -> tuple[bytes, ...]:
    frames: list[bytes] = []
    for packet_id, first in enumerate(range(0, ELEMENTS, ELEMENTS_PER_FRAME), start=17):
        frames.append(
            encode_data_frame(
                DataPacket(
                    PacketClass.DATA,
                    KEY,
                    10,
                    11,
                    12,
                    packet_id,
                    first,
                    (NumberGroup(ConcreteFormat.KULISCH, (VALUE,) * ELEMENTS_PER_FRAME),),
                    last=first + ELEMENTS_PER_FRAME == ELEMENTS,
                ),
                destination_mac=DESTINATION,
                source_mac=SOURCE,
                mtu=576,
                kulisch_bits=WIDTH,
            )
        )
    return tuple(frames)


async def exercise(dut: Any, *, stall_period: int = 0) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    expected = expected_frames()
    integer = int.from_bytes(VALUE[1:], "little")
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(expected[0][:56], "big") << 17
    dut.s_total_elements.value = ELEMENTS
    dut.s_mtu.value = 576
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = 2
    dut.s_tags.value = 0
    dut.s_integers.value = integer | (integer << WIDTH)
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    frames: list[bytes] = []
    partial = bytearray()
    accepted_cycles: list[int] = []
    cycle = 0
    axi_bytes = 0
    stalled_beats = 0
    held: tuple[int, int, int, int, int] | None = None

    async def observe() -> None:
        nonlocal cycle, axi_bytes, stalled_beats, held
        while True:
            await FallingEdge(dut.clk)
            dut.m_axis_tready.value = int(not stall_period or cycle % stall_period != 3)
            await ReadOnly()
            assert int(dut.m_fault.value) == 0
            valid = int(dut.m_axis_tvalid.value)
            ready = int(dut.m_axis_tready.value)
            current = (
                int(dut.m_axis_tdata.value),
                int(dut.m_axis_tkeep.value),
                int(dut.m_axis_tlast.value),
                int(dut.m_frame_bytes.value),
                int(dut.m_packet_id.value),
            )
            if held is not None:
                assert valid and current == held
            held = current if valid and not ready else None
            stalled_beats += int(bool(valid and not ready))
            if valid and ready:
                keep = int(dut.m_axis_tkeep.value)
                assert keep and keep == (1 << keep.bit_count()) - 1
                axi_bytes += keep.bit_count()
                partial.extend(
                    int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()]
                )
                accepted_cycles.append(cycle)
                if int(dut.m_axis_tlast.value):
                    assert len(partial) == int(dut.m_frame_bytes.value)
                    frames.append(bytes(partial))
                    partial.clear()
            cycle += 1

    observer = cocotb.start_soon(observe())
    sent = 0
    for _ in range(10000):
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = int(sent < ELEMENTS)
        dut.s_tile_first_element.value = min(sent, ELEMENTS - 2)
        await ReadOnly()
        accepted = sent < ELEMENTS and int(dut.s_tile_ready.value)
        await RisingEdge(dut.clk)
        if accepted:
            sent += 2
        if sent == ELEMENTS:
            break
    assert sent == ELEMENTS
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(10000):
        await FallingEdge(dut.clk)
        if len(frames) == len(expected):
            break
    observer.cancel()

    assert frames == list(expected)
    assert axi_bytes == sum(map(len, expected))
    assert len(accepted_cycles) == 9 * len(expected)
    output_window = accepted_cycles[-1] - accepted_cycles[0] + 1
    frame_gbps = axi_bytes * 8 * 0.25 / output_window
    dut._log.info(
        "Kulisch partials AXI frame=%.2f Gb/s; %d frames, %d beats, %d cycles",
        frame_gbps,
        len(frames),
        len(accepted_cycles),
        output_window,
    )
    if stall_period:
        assert stalled_beats > 0
    else:
        assert frame_gbps >= TARGET_GBPS


@cocotb.test()
async def kulisch_partials_emit_at_120_gbps(dut: Any) -> None:
    await exercise(dut)


@cocotb.test()
async def kulisch_partial_frames_hold_during_backpressure(dut: Any) -> None:
    await exercise(dut, stall_period=7)
