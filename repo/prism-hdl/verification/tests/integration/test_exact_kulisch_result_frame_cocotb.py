"""An exact non-FP32 sum reaches RESULT as sustained Kulisch frames."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import ExactValue, decode_kulisch, encode_kulisch
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
SOURCE = bytes.fromhex("66778899aabb")
DESTINATION = bytes.fromhex("001122334455")
ELEMENTS = 4096
WIDTH = 320
VALUE = ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24))


def expected_frames() -> tuple[bytes, ...]:
    encoded = encode_kulisch(VALUE, WIDTH)
    frames = []
    # The two-value tile interface closes a frame at the last full pair.
    # With 320-bit values, 35 fit by bytes but only 34 fit in complete pairs.
    values_per_frame = 2 * (((1500 - 49) // (1 + WIDTH // 8)) // 2)
    for packet_id, first in enumerate(range(0, ELEMENTS, values_per_frame), start=0):
        count = min(values_per_frame, ELEMENTS - first)
        frames.append(
            encode_data_frame(
                DataPacket(
                    PacketClass.RESULT,
                    KEY,
                    10,
                    11,
                    12,
                    packet_id,
                    first,
                    (NumberGroup(ConcreteFormat.KULISCH, (encoded,) * count),),
                    last=first + count == ELEMENTS,
                ),
                destination_mac=DESTINATION,
                source_mac=SOURCE,
                mtu=1500,
                kulisch_bits=WIDTH,
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
async def exact_sum_streams_full_result_without_rounding(dut: Any) -> None:
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
    dut.s_total_elements.value = ELEMENTS
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    frames: list[bytes] = []
    cycles: list[int] = []
    observer = cocotb.start_soon(capture(dut, frames, cycles))

    one_tile = int.from_bytes((0x3F800000).to_bytes(4, "little") * 16, "little")
    epsilon_tile = int.from_bytes((0x33800000).to_bytes(4, "little") * 16, "little")
    sent = 0
    for _ in range(700):
        await FallingEdge(dut.clk)
        dut.s_valid.value = int(sent < 512)
        dut.s_slot.value = min(sent % 256, 255)
        dut.s_first_element.value = min(sent % 256, 255) * 16
        dut.s_element_bits.value = one_tile if sent < 256 else epsilon_tile
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
    for _ in range(7000):
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
    for _ in range(8000):
        await FallingEdge(dut.clk)
        if len(frames) == len(expected):
            break
    observer.cancel()
    assert len(frames) == len(expected), (len(frames), len(expected))
    for index, (actual, golden) in enumerate(zip(frames, expected, strict=True)):
        assert len(actual) == len(golden), (index, len(actual), len(golden))
        if actual != golden:
            first_diff = next(
                offset for offset, (a, b) in enumerate(zip(actual, golden, strict=True)) if a != b
            )
            raise AssertionError(
                f"frame {index} differs at byte {first_diff}: "
                f"actual={actual[first_diff]:02x} expected={golden[first_diff]:02x} "
                f"lengths={len(actual)}/{len(golden)}"
            )
    first = decode_data_frame(frames[0], mtu=1500, kulisch_bits=WIDTH)
    assert all(decode_kulisch(value, WIDTH) == VALUE for value in first.groups[0].values)
    elapsed = cycles[-1] - cycles[0] + 1
    numeric_gbps = ELEMENTS * WIDTH / (elapsed * 4)
    dut._log.info(
        "Kulisch RESULT numeric=%.2f Gb/s, %d frames, %d AXI beats, %d cycles",
        numeric_gbps,
        len(frames),
        len(cycles),
        elapsed,
    )
    assert numeric_gbps >= 100
