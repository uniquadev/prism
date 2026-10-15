"""Exact wide tiles become byte-checked, sustained FP32 RESULT frames."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
SOURCE = bytes.fromhex("66778899aabb")
DESTINATION = bytes.fromhex("001122334455")


def expected_frames() -> tuple[bytes, ...]:
    frames: list[bytes] = []
    for packet_id, first in enumerate(range(0, 4096, 352), start=17):
        count = min(352, 4096 - first)
        packet = DataPacket(
            PacketClass.RESULT,
            KEY,
            10,
            11,
            12,
            packet_id,
            first,
            (NumberGroup(ConcreteFormat.FP32, (0,) * count),),
            last=first + count == 4096,
        )
        frames.append(
            encode_data_frame(
                packet,
                destination_mac=DESTINATION,
                source_mac=SOURCE,
                mtu=1500,
                kulisch_bits=320,
            )
        )
    return tuple(frames)


async def capture(dut: Any, frames: list[bytes], cycles: list[int]) -> None:
    partial = bytearray()
    cycle = 0
    while True:
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_fault.value) == 0
        if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
            keep = int(dut.m_axis_tkeep.value)
            assert keep and keep == (1 << keep.bit_count()) - 1
            partial.extend(int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            cycles.append(cycle)
            if int(dut.m_axis_tlast.value):
                assert len(partial) == int(dut.m_frame_bytes.value)
                frames.append(bytes(partial))
                partial.clear()
        cycle += 1


@cocotb.test()
async def two_rank_exact_sum_sustains_multiframe_fp32_results(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    expected = expected_frames()
    dut.rst_n.value = 0
    dut.s_slot.value = 0
    dut.s_first_element.value = 0
    dut.s_format.value = 4
    dut.s_element_bits.value = 0
    dut.s_element_keep.value = 0
    dut.s_valid.value = 0
    dut.s_result_slot.value = 0
    dut.s_result_read_valid.value = 0
    dut.s_header.value = int.from_bytes(expected[0][:56], "big") << 17
    dut.s_total_elements.value = 4096
    dut.s_output_format.value = 4
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    frames: list[bytes] = []
    cycles: list[int] = []
    observer = cocotb.start_soon(capture(dut, frames, cycles))

    one_tile = int.from_bytes((0x3F800000).to_bytes(4, "little") * 16, "little")
    negative_tile = int.from_bytes((0xBF800000).to_bytes(4, "little") * 16, "little")
    sent = 0
    for _ in range(540):
        await FallingEdge(dut.clk)
        dut.s_valid.value = int(sent < 512)
        dut.s_slot.value = min(sent % 256, 255)
        dut.s_first_element.value = min(sent % 256, 255) * 16
        dut.s_element_bits.value = one_tile if sent < 256 else negative_tile
        dut.s_element_keep.value = 0xFFFF
        await ReadOnly()
        accepted = sent < 512 and int(dut.s_ready.value) == 1
        await RisingEdge(dut.clk)
        if accepted:
            sent += 1
        if sent == 512:
            break
    assert sent == 512
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    # The bank grants a read once its stages are empty; the first request
    # below waits for that.
    for _ in range(4):
        await FallingEdge(dut.clk)

    requested = 0
    for _ in range(600):
        await FallingEdge(dut.clk)
        dut.s_result_read_valid.value = int(requested < 256)
        dut.s_result_slot.value = min(requested, 255)
        await ReadOnly()
        accepted = requested < 256 and int(dut.s_result_read_ready.value) == 1
        await RisingEdge(dut.clk)
        if accepted:
            requested += 1
        if requested == 256:
            break
    assert requested == 256
    await FallingEdge(dut.clk)
    dut.s_result_read_valid.value = 0
    for _ in range(600):
        await FallingEdge(dut.clk)
        if len(frames) == len(expected):
            break
    observer.cancel()
    assert tuple(frames) == expected
    elapsed = cycles[-1] - cycles[0] + 1
    rate = 4096 * 32 / (elapsed * 4)
    dut._log.info("exact-to-RESULT FP32 payload %.2f Gb/s across 12 byte-checked AXI frames", rate)
    assert rate >= 100
