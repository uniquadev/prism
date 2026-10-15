"""Packed native partial tiles sustain one AXI beat per cycle."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
SOURCE = bytes.fromhex("66778899aabb")
DESTINATION = bytes.fromhex("001122334455")
VALUES = {
    ConcreteFormat.INT8: (0x7F, 1),
    ConcreteFormat.FP16: (0x3C00, 2),
    ConcreteFormat.BF16: (0x3F80, 2),
    ConcreteFormat.FP32: (0x3F800000, 4),
}
TARGET_GBPS = 120.0


async def exercise(dut: Any, *, stall_period: int = 0) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await Timer(1, unit="ps")
    wire_format = ConcreteFormat(int(dut.m_format.value))
    value, width = VALUES[wire_format]
    values_per_tile = 64 // width
    elements_per_frame = 22 * values_per_tile
    total_elements = 12 * elements_per_frame
    expected = tuple(
        encode_data_frame(
            DataPacket(
                PacketClass.DATA,
                KEY,
                10,
                11,
                12,
                17 + frame_index,
                frame_index * elements_per_frame,
                (NumberGroup(wire_format, (value,) * elements_per_frame),),
                last=frame_index == 11,
            ),
            destination_mac=DESTINATION,
            source_mac=SOURCE,
            mtu=1500,
            kulisch_bits=320,
        )
        for frame_index in range(12)
    )
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(expected[0][:56], "big") << 17
    dut.s_total_elements.value = total_elements
    dut.s_mtu.value = 1500
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = values_per_tile
    dut.s_tile_bits.value = int.from_bytes(
        value.to_bytes(width, "little") * values_per_tile, "little"
    )
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    frames: list[bytes] = []
    partial = bytearray()
    accepted_cycles: list[int] = []
    input_cycles: list[int] = []
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
    for _ in range(1200):
        await FallingEdge(dut.clk)
        dut.s_tile_valid.value = int(sent < total_elements)
        dut.s_tile_first_element.value = min(sent, total_elements - values_per_tile)
        await ReadOnly()
        accepted = sent < total_elements and int(dut.s_tile_ready.value)
        if accepted:
            input_cycles.append(cycle)
        await RisingEdge(dut.clk)
        if accepted:
            sent += values_per_tile
        if sent == total_elements:
            break
    assert sent == total_elements
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    for _ in range(1200):
        await FallingEdge(dut.clk)
        if len(frames) == len(expected):
            break
    observer.cancel()

    assert frames == list(expected)
    assert len(accepted_cycles) == 23 * len(expected)
    output_window = accepted_cycles[-1] - accepted_cycles[0] + 1
    input_window = input_cycles[-1] - input_cycles[0] + 1
    numeric_gbps = total_elements * width * 8 * 0.25 / output_window
    frame_gbps = axi_bytes * 8 * 0.25 / output_window
    input_gbps = total_elements * width * 8 * 0.25 / input_window
    dut._log.info(
        "%s native partials input=%.2f, numeric=%.2f, AXI frame=%.2f Gb/s; "
        "%d frames, %d beats, %d cycles",
        wire_format.name,
        input_gbps,
        numeric_gbps,
        frame_gbps,
        len(frames),
        len(accepted_cycles),
        output_window,
    )
    if stall_period:
        assert stalled_beats > 0
    else:
        assert input_gbps >= TARGET_GBPS
        assert numeric_gbps >= TARGET_GBPS
        assert frame_gbps >= TARGET_GBPS


@cocotb.test()
async def native_partials_emit_at_120_gbps(dut: Any) -> None:
    await exercise(dut)


@cocotb.test()
async def native_partial_frames_hold_during_backpressure(dut: Any) -> None:
    await exercise(dut, stall_period=7)


@cocotb.test()
async def native_tail_masks_unused_bytes_and_pads_group(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await Timer(1, unit="ps")
    wire_format = ConcreteFormat(int(dut.m_format.value))
    value, width = VALUES[wire_format]
    values_per_tile = 64 // width
    total_elements = values_per_tile + 1
    expected = encode_data_frame(
        DataPacket(
            PacketClass.DATA,
            KEY,
            10,
            11,
            12,
            17,
            0,
            (NumberGroup(wire_format, (value,) * total_elements),),
            last=True,
        ),
        destination_mac=DESTINATION,
        source_mac=SOURCE,
        mtu=576,
        kulisch_bits=320,
    )
    dut.rst_n.value = 0
    dut.s_reset.value = 0
    dut.s_header.value = int.from_bytes(expected[:56], "big") << 17
    dut.s_total_elements.value = total_elements
    dut.s_mtu.value = 576
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = values_per_tile
    dut.s_tile_bits.value = int.from_bytes(
        value.to_bytes(width, "little") * values_per_tile, "little"
    )
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    for first, count in ((0, values_per_tile), (values_per_tile, 1)):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = first
        dut.s_tile_count.value = count
        dut.s_tile_valid.value = 1
        await ReadOnly()
        assert int(dut.s_tile_ready.value)
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0

    frame = bytearray()
    for _ in range(20):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert not int(dut.m_fault.value)
        if int(dut.m_axis_tvalid.value):
            keep = int(dut.m_axis_tkeep.value)
            frame.extend(int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            if int(dut.m_axis_tlast.value):
                assert int(dut.m_frame_bytes.value) == len(expected)
                break
    assert bytes(frame) == expected
