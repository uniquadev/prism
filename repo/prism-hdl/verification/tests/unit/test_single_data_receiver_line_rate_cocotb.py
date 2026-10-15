"""Sustained DATA receive rate for each native NumberGroup format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.wire.data import NumberGroup

from tests.unit import test_single_data_receiver_cocotb as receiver

ELEMENTS = 4096
CLOCK_NS = 4
TARGET_GBPS = 100.0


@dataclass
class ReceiveProbe:
    expected_frames: int
    cycle: int = 0
    first_input: int | None = None
    last_input: int | None = None
    first_tile: int | None = None
    last_tile: int | None = None
    input_beats: int = 0
    input_stalls: int = 0
    source_gaps: int = 0
    accepted_frames: int = 0
    frame_events: list[int] = field(default_factory=list)
    tiles: list[tuple[int, int, int, int, int]] = field(default_factory=list)

    async def run(self, dut: Any) -> None:
        while True:
            await FallingEdge(dut.clk)
            await ReadOnly()
            self.cycle += 1
            valid = bool(int(dut.s_axis_tvalid.value))
            ready = bool(int(dut.s_axis_tready.value))
            if self.first_input is not None and self.last_input is None and not valid:
                self.source_gaps += 1
            if valid and not ready:
                self.input_stalls += 1
            if valid and ready:
                if self.first_input is None:
                    self.first_input = self.cycle
                self.input_beats += 1
                if int(dut.s_axis_tlast.value):
                    self.accepted_frames += 1
                    if self.accepted_frames == self.expected_frames:
                        self.last_input = self.cycle
            if int(dut.m_tile_valid.value) and int(dut.m_tile_ready.value):
                if self.first_tile is None:
                    self.first_tile = self.cycle
                self.last_tile = self.cycle
                self.tiles.append(
                    (
                        int(dut.m_tile_first_element.value),
                        int(dut.m_tile_format.value),
                        int(dut.m_tile_count.value),
                        int(dut.m_tile_keep.value),
                        int(dut.m_tile_bits.value),
                    )
                )
            if int(dut.m_frame_event_valid.value):
                self.frame_events.append(int(dut.m_frame_event_status.value))


def window_cycles(first: int | None, last: int | None) -> int:
    assert first is not None and last is not None and last >= first
    return last - first + 1


async def check_format(
    dut: Any,
    fmt: ConcreteFormat,
    value_bits: int,
    width: int,
    max_group: int,
) -> None:
    await receiver.initialize(dut)
    dut.s_total_elements.value = ELEMENTS
    dut.s_native_masks.value = (4 << 8) | (1 << (int(fmt) - 1))
    frames = tuple(
        receiver.frame(
            0,
            packet_id=packet_id,
            first_element=first,
            groups=(NumberGroup(fmt, (value_bits,) * min(max_group, ELEMENTS - first)),),
            last=first + max_group >= ELEMENTS,
        )
        for packet_id, first in enumerate(range(0, ELEMENTS, max_group))
    )
    probe = ReceiveProbe(expected_frames=len(frames))
    observer = cocotb.start_soon(probe.run(dut))
    try:
        await receiver.send_contiguous(dut, frames)
        for _ in range(20_000):
            await FallingEdge(dut.clk)
            if (
                len(probe.frame_events) == len(frames)
                and sum(tile[2] for tile in probe.tiles) == ELEMENTS
            ):
                break
        else:
            raise AssertionError(f"{fmt.name}: DATA receive stream did not complete")
    finally:
        observer.cancel()

    assert probe.frame_events == [0] * len(frames)
    assert int(dut.m_receive_complete.value) & 1
    assert probe.source_gaps == 0, "the test sender must offer consecutive DATA beats"
    positions: list[int] = []
    for first, tile_format, count, keep, bits in probe.tiles:
        assert tile_format == int(fmt) and count == keep.bit_count()
        for lane in range(512 // width):
            if keep & (1 << lane):
                assert (bits >> (lane * width)) & ((1 << width) - 1) == value_bits
                positions.append(first + lane)
    assert sorted(positions) == list(range(ELEMENTS))

    input_cycles = window_cycles(probe.first_input, probe.last_input)
    tile_cycles = window_cycles(probe.first_tile, probe.last_tile)
    input_gbps = ELEMENTS * width / (input_cycles * CLOCK_NS)
    tile_gbps = ELEMENTS * width / (tile_cycles * CLOCK_NS)
    dut._log.info(
        "%s DATA payload: input %.2f Gb/s over %d cycles, native tiles %.2f Gb/s "
        "over %d cycles; %d frames, %d AXI beats, %d input stalls",
        fmt.name,
        input_gbps,
        input_cycles,
        tile_gbps,
        tile_cycles,
        len(frames),
        probe.input_beats,
        probe.input_stalls,
    )
    assert input_gbps >= TARGET_GBPS and tile_gbps >= TARGET_GBPS, (
        f"{fmt.name}: DATA input {input_gbps:.2f} Gb/s, native tiles "
        f"{tile_gbps:.2f} Gb/s; both must reach {TARGET_GBPS:.0f} Gb/s"
    )


@cocotb.test()
async def int8_receiver_reaches_100_gbps(dut: Any) -> None:
    await check_format(dut, ConcreteFormat.INT8, 1, 8, 1452)


@cocotb.test()
async def fp16_receiver_reaches_100_gbps(dut: Any) -> None:
    await check_format(dut, ConcreteFormat.FP16, 0x3C00, 16, 726)


@cocotb.test()
async def bf16_receiver_reaches_100_gbps(dut: Any) -> None:
    await check_format(dut, ConcreteFormat.BF16, 0x3F80, 16, 726)


@cocotb.test()
async def fp32_receiver_reaches_100_gbps(dut: Any) -> None:
    await check_format(dut, ConcreteFormat.FP32, 0x3F800000, 32, 363)
