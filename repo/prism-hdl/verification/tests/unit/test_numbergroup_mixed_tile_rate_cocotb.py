"""Sustained beat-level gate for a wide partial tile source."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.wire.data import NumberGroup, decode_data_frame

from .numbergroup_frame_fixture import frame
from .test_numbergroup_mixed_tile_cocotb import initialize, receive


@cocotb.test()
async def sustained_fp32_tiles_reach_numeric_line_rate(dut: Any) -> None:
    await initialize(dut)
    dut.s_mtu.value = 1500
    total = 4096
    metrics: dict[str, int] = {}
    receiver = cocotb.start_soon(receive(dut, None, stall=False, metrics=metrics))
    template = frame(90, 0, (NumberGroup(ConcreteFormat.FP32, (0,)),), last=False)
    dut.s_header_beat.value = int.from_bytes(template[:64], "little")
    dut.s_total_elements.value = total
    dut.s_tile_count.value = 16
    dut.s_formats.value = sum(int(ConcreteFormat.FP32) << (8 * lane) for lane in range(16))
    dut.s_native_bits.value = sum(0x3F800000 << (32 * lane) for lane in range(16))
    first_input_ns = None
    accepted = 0
    for _ in range(4000):
        await FallingEdge(dut.clk)
        dut.s_tile_first_element.value = accepted * 16
        dut.s_tile_valid.value = int(accepted < 256)
        await ReadOnly()
        if accepted < 256 and int(dut.s_tile_ready.value):
            if first_input_ns is None:
                first_input_ns = int(get_sim_time(unit="ns"))
            accepted += 1
        if accepted == 256:
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError(f"only {accepted} of 256 tiles were accepted")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    frames = await receiver
    assert first_input_ns is not None
    packets = [decode_data_frame(data, mtu=1500, kulisch_bits=320) for data in frames]
    next_element = 0
    for packet_index, packet in enumerate(packets):
        assert packet.first_element == next_element
        assert packet.packet_id == 90 + packet_index
        assert all(
            group.format == ConcreteFormat.FP32
            and all(value == 0x3F800000 for value in group.values)
            for group in packet.groups
        )
        next_element += packet.element_count
    assert next_element == total
    assert packets[-1].last
    cycles = (metrics["last_output_ns"] - first_input_ns) // 4 + 1
    numeric_gbps = total * 32 * 0.25 / cycles
    frame_gbps = sum(map(len, frames)) * 8 * 0.25 / cycles
    element_rate = total * 250_000_000 / cycles
    dut._log.info(
        "mixed tile FP32 numeric %.2f Gb/s; AXI frame %.2f Gb/s; "
        "%.2f M elements/s; %d beats in %d cycles",
        numeric_gbps,
        frame_gbps,
        element_rate / 1_000_000,
        metrics["beats"],
        cycles,
    )
    assert numeric_gbps >= 100.0
