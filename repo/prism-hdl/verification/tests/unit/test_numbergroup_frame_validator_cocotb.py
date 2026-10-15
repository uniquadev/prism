"""Complete in-band NumberGroup admission before arithmetic-side visibility."""

from __future__ import annotations

import random
from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import ExactValue, decode_native, encode_kulisch
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 02 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0102 0304 0a0b0c0d 00000009 0003 02 01 0010 0f10 0000 "
    "01 00 0002 7f80 0000 "
    "02 00 0001 003c 0000"
)
KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
DST = bytes.fromhex("001122334455")
SRC = bytes.fromhex("66778899aabb")


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = 279
    dut.m_ready.value = 0
    dut.m_read_address.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(
    dut: Any, frame: bytes, *, bad_keep: int | None = None, user_error: bool = False
) -> None:
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        await FallingEdge(dut.clk)
        dut.s_axis_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
        dut.s_axis_tkeep.value = (
            bad_keep if bad_keep is not None and offset == 0 else (1 << len(beat)) - 1
        )
        dut.s_axis_tlast.value = int(offset + len(beat) == len(frame))
        dut.s_axis_tuser.value = int(user_error)
        dut.s_axis_tvalid.value = 1
        await ReadOnly()
        assert int(dut.s_axis_tready.value) == 1
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0


async def report(
    dut: Any,
    *,
    accepted: bool,
    frame: bytes | None = None,
    format_mask: int | None = None,
) -> None:
    for _ in range(4000):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            break
    else:
        raise AssertionError("validator did not terminate within bounded cycles")
    assert bool(int(dut.m_accept.value)) == accepted
    assert (int(dut.m_error_code.value) == 0) == accepted
    if format_mask is not None:
        assert int(dut.m_format_mask.value) == format_mask
    if not accepted:
        await FallingEdge(dut.clk)
        dut.m_read_address.value = 0
        await ReadOnly()
        assert int(dut.m_read_data.value) == 0
    if accepted and frame is not None:
        assert int(dut.m_frame_bytes.value) == len(frame)
        assert int(dut.m_first_element.value) == 9
        assert int(dut.m_element_count.value) == 3
        assert int(dut.m_group_count.value) == 2
        assert int(dut.m_body_bytes.value) == 16
        assert int(dut.m_packet_id.value) == 0x0A0B0C0D
        for offset in range(len(frame)):
            await FallingEdge(dut.clk)
            dut.m_read_address.value = offset
            await ReadOnly()
            assert int(dut.m_read_data.value) == frame[offset], offset
        await FallingEdge(dut.clk)
        dut.m_read_address.value = len(frame)
        await ReadOnly()
        assert int(dut.m_read_data.value) == 0
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0


@cocotb.test()
async def golden_frame_is_committed_only_after_complete_validation(dut: Any) -> None:
    await initialize(dut)
    await send(dut, GOLDEN)
    await report(dut, accepted=True, frame=GOLDEN, format_mask=0b00011)


@cocotb.test()
async def terminal_arithmetic_error_is_validated_without_a_numbergroup(dut: Any) -> None:
    await initialize(dut)
    error_frame = encode_data_frame(
        DataPacket(
            PacketClass.DATA,
            KEY,
            0x0102,
            0x0304,
            0x0F10,
            55,
            7,
            (),
            last=True,
            accumulation_inexact=True,
        ),
        destination_mac=DST,
        source_mac=SRC,
        mtu=1500,
        kulisch_bits=279,
    )
    assert len(error_frame) == 60
    await send(dut, error_frame)
    for _ in range(80):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            break
    else:
        raise AssertionError("terminal error frame was not reported")
    assert int(dut.m_accept.value) == 1
    assert int(dut.m_format_mask.value) == 0
    assert int(dut.m_flags.value) == 3
    assert int(dut.m_element_count.value) == 0
    assert int(dut.m_group_count.value) == 0
    assert int(dut.m_body_bytes.value) == 0
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0

    for offset, value in ((49, 2), (46, 1), (48, 1), (50, 1), (54, 1), (56, 1)):
        malformed = bytearray(error_frame)
        malformed[offset] = value
        await send(dut, bytes(malformed))
        await report(dut, accepted=False)


@cocotb.test()
async def one_beat_frame_holds_under_backpressure_after_bad_descriptor(dut: Any) -> None:
    await initialize(dut)
    one_beat = encode_data_frame(
        DataPacket(
            PacketClass.DATA,
            KEY,
            0x0102,
            0x0304,
            0x0F10,
            55,
            7,
            (NumberGroup(ConcreteFormat.INT8, (7,)),),
            last=True,
        ),
        destination_mac=DST,
        source_mac=SRC,
        mtu=1500,
        kulisch_bits=279,
    )
    assert len(one_beat) == 64
    malformed = bytearray(one_beat)
    malformed[59] = 2  # Descriptor count disagrees with the header's one element.
    await send(dut, bytes(malformed))
    await report(dut, accepted=False)
    await send(dut, one_beat)
    for _ in range(4000):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            break
    else:
        raise AssertionError("one-beat frame did not validate")
    for _ in range(5):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_accept.value) == 1
        assert int(dut.m_frame_bytes.value) == len(one_beat)
        assert int(dut.m_first_element.value) == 7
        assert int(dut.m_element_count.value) == 1
        assert int(dut.m_group_count.value) == 1
        assert int(dut.m_packet_id.value) == 55
    for address, byte in enumerate(one_beat):
        await FallingEdge(dut.clk)
        dut.m_read_address.value = address
        await ReadOnly()
        assert int(dut.m_read_data.value) == byte
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def reset_discards_an_incomplete_multibeat_frame(dut: Any) -> None:
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.s_axis_tdata.value = int.from_bytes(GOLDEN[:64], "little")
    dut.s_axis_tkeep.value = (1 << 64) - 1
    dut.s_axis_tlast.value = 0
    dut.s_axis_tvalid.value = 1
    await ReadOnly()
    assert int(dut.s_axis_tready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await send(dut, GOLDEN)
    await report(dut, accepted=True, frame=GOLDEN, format_mask=0b00011)


@cocotb.test()
async def malformed_lengths_counts_padding_and_axis_are_rejected(dut: Any) -> None:
    await initialize(dut)
    mutations: list[tuple[bytes, int | None, bool]] = []
    for offset, value in ((46, 4), (48, 0), (56, 0xFF), (57, 1), (63, 1), (55, 1)):
        corrupted = bytearray(GOLDEN)
        corrupted[offset] = value
        mutations.append((bytes(corrupted), None, False))
    mutations.append((GOLDEN[:-1], None, False))
    mutations.append((GOLDEN, ((1 << 64) - 1) ^ (1 << 31), False))
    mutations.append((GOLDEN, None, True))
    for frame, bad_keep, user_error in mutations:
        await send(dut, frame, bad_keep=bad_keep, user_error=user_error)
        await report(dut, accepted=False)


@cocotb.test()
async def mixed_native_and_kulisch_generated_frames(dut: Any) -> None:
    await initialize(dut)
    rng = random.Random(19)
    choices = (
        (ConcreteFormat.INT8, 0x7F),
        (ConcreteFormat.FP16, 0x3C00),
        (ConcreteFormat.BF16, 0x3F80),
        (ConcreteFormat.FP32, 0x3F800000),
        (
            ConcreteFormat.KULISCH,
            encode_kulisch(decode_native(0x3F800000, ConcreteFormat.FP32), 279),
        ),
    )
    for packet_id in range(24):
        groups = tuple(
            NumberGroup(fmt, tuple(value for _ in range(rng.randint(1, 3))))
            for fmt, value in (rng.choice(choices) for _ in range(rng.randint(1, 5)))
        )
        packet = DataPacket(
            PacketClass.DATA,
            KEY,
            0x0102,
            0x0304,
            0x0F10,
            packet_id,
            packet_id * 16,
            groups,
            last=False,
        )
        frame = encode_data_frame(
            packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
        )
        await send(dut, frame)
        expected_mask = 0
        for group in groups:
            bit_index = 4 if group.format == ConcreteFormat.KULISCH else int(group.format) - 1
            expected_mask |= 1 << bit_index
        await report(dut, accepted=True, format_mask=expected_mask)
    kulisch = encode_kulisch(decode_native(0x3F800000, ConcreteFormat.FP32), 279)
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        0x0102,
        0x0304,
        0x0F10,
        50,
        0,
        (NumberGroup(ConcreteFormat.KULISCH, (kulisch,)),),
    )
    valid = encode_data_frame(
        packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
    )
    for offset, value in ((60, 6), (60, 4), (95, valid[95] ^ 0x80)):
        corrupted = bytearray(valid)
        corrupted[offset] = value
        await send(dut, bytes(corrupted))
        await report(dut, accepted=False)
    for special_value in (
        ExactValue("nan", False),
        ExactValue("infinity", False),
        ExactValue("infinity", True),
        ExactValue("zero", False, Fraction(0)),
        ExactValue("zero", True, Fraction(0)),
        decode_native(0x80000001, ConcreteFormat.FP32),
    ):
        encoded = encode_kulisch(special_value, 279)
        special_packet = DataPacket(
            PacketClass.DATA,
            KEY,
            0x0102,
            0x0304,
            0x0F10,
            51,
            0,
            (NumberGroup(ConcreteFormat.KULISCH, (encoded,)),),
        )
        await send(
            dut,
            encode_data_frame(
                special_packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
            ),
        )
        await report(dut, accepted=True)


@cocotb.test()
async def widest_kulisch_element_fits_minimum_mtu(dut: Any) -> None:
    await initialize(dut)
    dut.s_mtu.value = 576
    dut.s_kulisch_bits.value = 4096
    encoded = encode_kulisch(decode_native(0x3F800000, ConcreteFormat.FP32), 4096)
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        0x0102,
        0x0304,
        0x0F10,
        7,
        0,
        (NumberGroup(ConcreteFormat.KULISCH, (encoded,)),),
        True,
    )
    frame = encode_data_frame(
        packet, destination_mac=DST, source_mac=SRC, mtu=576, kulisch_bits=4096
    )
    assert len(frame) == 576
    await send(dut, frame)
    await report(dut, accepted=True)
    corrupted = bytearray(frame)
    corrupted[-1] = 1  # final value-padding byte
    await send(dut, bytes(corrupted))
    await report(dut, accepted=False)


@cocotb.test()
async def frame_longer_than_the_largest_frame_is_a_receive_error(dut: Any) -> None:
    """Six bytes too many still fit the frame buffer; the length check must catch them."""
    await initialize(dut)
    await send(dut, GOLDEN.ljust(1520, b"\0"))
    for _ in range(4000):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            break
    else:
        raise AssertionError("validator did not terminate within bounded cycles")
    assert int(dut.m_accept.value) == 0
    assert int(dut.m_error_code.value) == 1
