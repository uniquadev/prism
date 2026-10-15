"""Mixed NumberGroup tile sender preserves concrete values and packet boundaries."""

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


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_header_beat.value = 0
    dut.s_total_elements.value = 0
    dut.s_mtu.value = 576
    dut.s_kulisch_bits.value = 320
    dut.s_tile_first_element.value = 0
    dut.s_tile_count.value = 0
    dut.s_formats.value = 0
    dut.s_native_bits.value = 0
    dut.s_tags.value = 0
    dut.s_integers.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send_tile(
    dut: Any,
    values: tuple[tuple[ConcreteFormat, int | bytes], ...],
    first: int,
    total: int,
) -> int:
    template = frame(90, 0, (NumberGroup(ConcreteFormat.FP32, (0,)),), last=False)
    formats = 0
    natives = 0
    tags = 0
    integers = 0
    for lane, (fmt, value) in enumerate(values):
        formats |= int(fmt) << (lane * 8)
        if isinstance(value, bytes):
            tags |= value[0] << (lane * 8)
            integers |= int.from_bytes(value[1:], "little") << (lane * 320)
        else:
            natives |= value << (lane * 32)
    for _ in range(2000):
        await FallingEdge(dut.clk)
        dut.s_header_beat.value = int.from_bytes(template[:64], "little")
        dut.s_total_elements.value = total
        dut.s_tile_first_element.value = first
        dut.s_tile_count.value = len(values)
        dut.s_formats.value = formats
        dut.s_native_bits.value = natives
        dut.s_tags.value = tags
        dut.s_integers.value = integers
        dut.s_tile_valid.value = 1
        await ReadOnly()
        if int(dut.s_tile_ready.value):
            accepted_ns = int(get_sim_time(unit="ns"))
            await RisingEdge(dut.clk)
            break
    else:
        raise AssertionError("mixed tile sender did not accept input")
    await FallingEdge(dut.clk)
    dut.s_tile_valid.value = 0
    return accepted_ns


async def receive(
    dut: Any,
    expected: int | None,
    *,
    stall: bool = True,
    metrics: dict[str, int] | None = None,
) -> list[bytes]:
    frames: list[bytes] = []
    partial = bytearray()
    for cycle in range(10000):
        await FallingEdge(dut.clk)
        dut.m_axis_tready.value = int(not stall or cycle % 7 not in (2, 3))
        await ReadOnly()
        assert not int(dut.m_fault.value)
        if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
            if metrics is not None:
                metrics.setdefault("first_output_ns", int(get_sim_time(unit="ns")))
                metrics["last_output_ns"] = int(get_sim_time(unit="ns"))
                metrics["beats"] = metrics.get("beats", 0) + 1
            keep = int(dut.m_axis_tkeep.value)
            assert keep == (1 << keep.bit_count()) - 1
            partial.extend(int(dut.m_axis_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            if int(dut.m_axis_tlast.value):
                assert len(partial) == int(dut.m_frame_bytes.value)
                frames.append(bytes(partial))
                partial.clear()
                if (expected is None and frames[-1][49] & 0x01) or len(frames) == expected:
                    return frames
    raise AssertionError(f"received {len(frames)} of {expected} frames")


async def fault_without_output(dut: Any, case: Any, limit: int = 8) -> None:
    """A rejected tile raises the fault within the encoder steps and never reaches the output."""
    held = 0
    for cycle in range(limit + 16):
        await ReadOnly()
        assert not int(dut.m_axis_tvalid.value), case
        if int(dut.m_fault.value):
            held += 1
        else:
            assert held == 0 and cycle < limit, case
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    assert held >= 16, case


@cocotb.test()
async def adjacent_groups_patch_a_descriptor_still_in_the_stage(dut: Any) -> None:
    await initialize(dut)
    receiver = cocotb.start_soon(receive(dut, 1))
    await send_tile(dut, ((ConcreteFormat.INT8, 7),) * 16, 0, 32)
    await send_tile(dut, ((ConcreteFormat.FP16, 0x3C00),) * 16, 16, 32)
    assert await receiver == [
        frame(
            90,
            0,
            (
                NumberGroup(ConcreteFormat.INT8, (7,) * 16),
                NumberGroup(ConcreteFormat.FP16, (0x3C00,) * 16),
            ),
            last=True,
        )
    ]


@cocotb.test()
async def adjacent_groups_patch_a_descriptor_already_in_the_frame(dut: Any) -> None:
    await initialize(dut)
    receiver = cocotb.start_soon(receive(dut, 1))
    await send_tile(dut, ((ConcreteFormat.FP32, 0x3F800000),) * 16, 0, 32)
    await send_tile(dut, ((ConcreteFormat.INT8, 7),) * 16, 16, 32)
    assert await receiver == [
        frame(
            90,
            0,
            (
                NumberGroup(ConcreteFormat.FP32, (0x3F800000,) * 16),
                NumberGroup(ConcreteFormat.INT8, (7,) * 16),
            ),
            last=True,
        )
    ]


@cocotb.test()
async def a_group_that_ends_with_padding_is_not_extended(dut: Any) -> None:
    """Values of the same format after a padded group start a group of their own."""
    await initialize(dut)
    receiver = cocotb.start_soon(receive(dut, 1))
    await send_tile(dut, ((ConcreteFormat.FP16, 0x3C00),) * 14, 0, 77)
    await send_tile(dut, ((ConcreteFormat.FP16, 0x3C00),) * 16, 14, 77)
    await send_tile(dut, ((ConcreteFormat.FP16, 0x3C00),) * 15, 30, 77)
    await send_tile(dut, ((ConcreteFormat.FP16, 0x3C00),) * 1, 45, 77)
    await send_tile(dut, ((ConcreteFormat.INT8, 7),) * 15, 46, 77)
    await send_tile(dut, ((ConcreteFormat.INT8, 7),) * 16, 61, 77)
    assert await receiver == [
        frame(
            90,
            0,
            (
                NumberGroup(ConcreteFormat.FP16, (0x3C00,) * 45),
                NumberGroup(ConcreteFormat.FP16, (0x3C00,) * 1),
                NumberGroup(ConcreteFormat.INT8, (7,) * 15),
                NumberGroup(ConcreteFormat.INT8, (7,) * 16),
            ),
            last=True,
        )
    ]


@cocotb.test()
async def a_group_after_mixed_values_can_extend_and_then_close(dut: Any) -> None:
    await initialize(dut)
    receiver = cocotb.start_soon(receive(dut, 1))
    await send_tile(
        dut,
        ((ConcreteFormat.INT8, 7),) * 8 + ((ConcreteFormat.FP16, 0x3C00),) * 8,
        0,
        64,
    )
    await send_tile(dut, ((ConcreteFormat.INT8, 3),) * 16, 16, 64)
    await send_tile(dut, ((ConcreteFormat.INT8, 3),) * 16, 32, 64)
    await send_tile(dut, ((ConcreteFormat.BF16, 0x3F80),) * 16, 48, 64)
    assert await receiver == [
        frame(
            90,
            0,
            (
                NumberGroup(ConcreteFormat.INT8, (7,) * 8),
                NumberGroup(ConcreteFormat.FP16, (0x3C00,) * 8),
                NumberGroup(ConcreteFormat.INT8, (3,) * 32),
                NumberGroup(ConcreteFormat.BF16, (0x3F80,) * 16),
            ),
            last=True,
        )
    ]


@cocotb.test()
async def one_tile_with_five_concrete_formats(dut: Any) -> None:
    await initialize(dut)
    kulisch = encode_kulisch(ExactValue("finite", False, Fraction(1, 1 << 149)), 320)
    values = (
        (ConcreteFormat.INT8, 7),
        (ConcreteFormat.FP16, 0x3C00),
        (ConcreteFormat.BF16, 0x3F80),
        (ConcreteFormat.FP32, 0x3F800000),
        (ConcreteFormat.KULISCH, kulisch),
    )
    receiver = cocotb.start_soon(receive(dut, 1))
    await send_tile(dut, values, 0, len(values))
    actual = await receiver
    expected = frame(90, 0, tuple(NumberGroup(fmt, (value,)) for fmt, value in values), last=True)
    assert actual == [expected]
    decoded = decode_data_frame(actual[0], mtu=576, kulisch_bits=320)
    assert decoded.element_count == len(values)


@cocotb.test()
async def long_fp32_vector_uses_legal_frames(dut: Any) -> None:
    await initialize(dut)
    total = 256
    values = ((ConcreteFormat.FP32, 0x3F800000),) * 16
    receiver = cocotb.start_soon(receive(dut, 2))
    for first in range(0, total, 16):
        await send_tile(dut, values, first, total)
    frames = await receiver
    packets = [decode_data_frame(data, mtu=576, kulisch_bits=320) for data in frames]
    assert [packet.packet_id for packet in packets] == [90, 91]
    assert [packet.first_element for packet in packets] == [0, 128]
    assert [packet.element_count for packet in packets] == [128, 128]
    assert [packet.last for packet in packets] == [False, True]
    assert all(len(packet.groups) == 1 for packet in packets)
    assert all(
        value == 0x3F800000
        for packet in packets
        for group in packet.groups
        for value in group.values
    )


@cocotb.test()
async def run_geometry_preserves_each_descriptor_payload_and_padding(dut: Any) -> None:
    """Build group bodies independently, covering every native padding residue."""
    from itertools import groupby

    await initialize(dut)
    exact = b"\x00" + (1).to_bytes(40, "little")
    values_by_format = {
        ConcreteFormat.INT8: 0xA5,
        ConcreteFormat.FP16: 0xBC01,
        ConcreteFormat.BF16: 0x3F81,
        ConcreteFormat.FP32: 0x80000001,
        ConcreteFormat.KULISCH: exact,
    }
    widths = {fmt: width for fmt, width in zip(values_by_format, (1, 2, 2, 4, 41), strict=True)}
    options = tuple(values_by_format)
    cases = [
        tuple(options[(lane // run) % len(options)] for lane in range(count))
        for run in (1, 2, 3, 4, 5, 7)
        for count in range(1, 17)
    ]
    cases.extend(
        (ConcreteFormat.INT8,) * native + (ConcreteFormat.KULISCH,) * (16 - native)
        for native in range(4, 16)
    )
    for formats in cases:
        dut.rst_n.value = 0
        dut.s_tile_valid.value = 0
        for _ in range(2):
            await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        values = tuple((fmt, values_by_format[fmt]) for fmt in formats)
        groups = []
        body = bytearray()
        for fmt, run in groupby(formats):
            count = len(tuple(run))
            value = values_by_format[fmt]
            groups.append(NumberGroup(fmt, (value,) * count))
            body.extend(bytes((int(fmt), 0)) + count.to_bytes(2, "big"))
            encoded = value if isinstance(value, bytes) else value.to_bytes(widths[fmt], "little")
            payload = encoded * count
            body.extend(payload)
            body.extend(bytes((-len(payload)) % 4))
        expected_header = frame(90, 0, tuple(groups), last=True)[:56]
        receiver = cocotb.start_soon(receive(dut, 1, stall=True))
        await send_tile(dut, values, 0, len(values))
        actual = await receiver
        assert actual == [expected_header + body], formats
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)


@cocotb.test()
async def every_lane_preserves_validation_and_sign_extension(dut: Any) -> None:
    """Invalid lanes never commit a frame; signed boundaries retain exact bytes."""
    from itertools import groupby

    await initialize(dut)
    template = frame(90, 0, (NumberGroup(ConcreteFormat.FP32, (0,)),), last=False)
    # (format, native bits, tag, exact integer, wire width, accepted)
    cases = [
        (0xFF, 0, 0, 0, 320, False),
        (int(ConcreteFormat.INT8), 0x100, 0, 0, 320, False),
        (int(ConcreteFormat.FP16), 0x10000, 0, 0, 320, False),
        (int(ConcreteFormat.BF16), 0x10000, 0, 0, 320, False),
        (int(ConcreteFormat.FP32), 0xFFFFFFFF, 0, 0, 320, True),
    ]
    for tag in range(7):
        for integer in (0, 1):
            cases.append(
                (
                    int(ConcreteFormat.KULISCH),
                    0,
                    tag,
                    integer,
                    320,
                    tag <= 5 and ((tag == 0) == (integer != 0)),
                )
            )
    for width in (278, 279, 319, 320):
        for integer in (-(1 << (width - 1)), (1 << (width - 1)) - 1):
            cases.append((int(ConcreteFormat.KULISCH), 0, 0, integer, width, True))
        if width < 320:
            for integer in (-(1 << (width - 1)) - 1, 1 << (width - 1)):
                cases.append((int(ConcreteFormat.KULISCH), 0, 0, integer, width, False))

    for lane in range(16):
        for fmt, native, tag, integer, wire_width, accepted in cases:
            dut.rst_n.value = 0
            dut.s_tile_valid.value = 0
            dut.m_axis_tready.value = 1
            for _ in range(2):
                await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            dut.rst_n.value = 1
            formats = [int(ConcreteFormat.INT8)] * 16
            formats[lane] = fmt
            dut.s_header_beat.value = int.from_bytes(template[:64], "little")
            dut.s_total_elements.value = 16
            dut.s_tile_first_element.value = 0
            dut.s_tile_count.value = 16
            dut.s_kulisch_bits.value = wire_width
            dut.s_formats.value = sum(value << (8 * i) for i, value in enumerate(formats))
            dut.s_native_bits.value = native << (32 * lane)
            dut.s_tags.value = tag << (8 * lane)
            dut.s_integers.value = (integer & ((1 << 320) - 1)) << (320 * lane)
            receiver = cocotb.start_soon(receive(dut, 1, stall=True)) if accepted else None
            dut.s_tile_valid.value = 1
            await ReadOnly()
            assert int(dut.s_tile_ready.value), (lane, fmt, wire_width)
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            dut.s_tile_valid.value = 0
            if receiver is None:
                await fault_without_output(dut, (lane, fmt, tag, integer, wire_width))
            else:
                actual = await receiver
                body = bytearray()
                for group_format, indices in groupby(range(16), key=lambda i: formats[i]):
                    positions = tuple(indices)
                    body.extend(bytes((group_format, 0)) + len(positions).to_bytes(2, "big"))
                    payload = bytearray()
                    for i in positions:
                        if i != lane:
                            payload.extend(b"\x00")
                        elif group_format == int(ConcreteFormat.KULISCH):
                            nbytes = (wire_width + 7) // 8
                            payload.extend(bytes((tag,)))
                            payload.extend(
                                (integer & ((1 << (nbytes * 8)) - 1)).to_bytes(nbytes, "little")
                            )
                        else:
                            payload.extend(native.to_bytes(4, "little"))
                    body.extend(payload)
                    body.extend(bytes((-len(payload)) % 4))
                assert actual[0][56:] == body, (lane, fmt, tag, integer, wire_width)
                await RisingEdge(dut.clk)
                await FallingEdge(dut.clk)


@cocotb.test()
async def native_runs_ignore_wide_width_and_keep_exact_bytes(dut: Any) -> None:
    from itertools import groupby

    await initialize(dut)
    formats = (ConcreteFormat.INT8, ConcreteFormat.FP16, ConcreteFormat.BF16, ConcreteFormat.FP32)
    widths = dict(zip(formats, (1, 2, 2, 4), strict=True))
    patterns = {
        ConcreteFormat.INT8: (0, 127, 128, 255),
        ConcreteFormat.FP16: (1, 0x8000, 0x7C00, 0x7E01),
        ConcreteFormat.BF16: (1, 0x8000, 0x7F80, 0x7FC1),
        ConcreteFormat.FP32: (1, 0x80000000, 0x7F800000, 0x7FC00001),
    }
    for wire_width in (278, 279, 280, 320, 512, 4096):
        for run in (1, 2, 3, 4, 7, 16):
            for count in (1, 7, 16):
                dut.rst_n.value = 0
                dut.s_tile_valid.value = 0
                for _ in range(2):
                    await RisingEdge(dut.clk)
                await FallingEdge(dut.clk)
                dut.rst_n.value = 1
                dut.s_kulisch_bits.value = wire_width
                values = tuple(
                    (formats[(lane // run) % 4], patterns[formats[(lane // run) % 4]][lane % 4])
                    for lane in range(count)
                )
                groups = []
                body = bytearray()
                for fmt, members in groupby(values, key=lambda pair: pair[0]):
                    numbers = tuple(value for _, value in members)
                    groups.append(NumberGroup(fmt, numbers))
                    body.extend(bytes((int(fmt), 0)) + len(numbers).to_bytes(2, "big"))
                    payload = b"".join(value.to_bytes(widths[fmt], "little") for value in numbers)
                    body.extend(payload)
                    body.extend(bytes(-len(payload) % 4))
                expected = frame(90, 0, tuple(groups), last=True)[:56] + body
                receiver = cocotb.start_soon(receive(dut, 1, stall=True))
                await send_tile(dut, values, 0, count)
                assert await receiver == [expected], (wire_width, run, count)
                await RisingEdge(dut.clk)
                await FallingEdge(dut.clk)


@cocotb.test()
async def invalid_configured_width_rejects_native_tile(dut: Any) -> None:
    await initialize(dut)
    for wire_width in (0, 277, 4097):
        dut.rst_n.value = 0
        dut.s_tile_valid.value = 0
        dut.m_axis_tready.value = 1
        for _ in range(2):
            await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        dut.s_kulisch_bits.value = wire_width
        await send_tile(dut, ((ConcreteFormat.INT8, 7),), 0, 1)
        await fault_without_output(dut, wire_width)


@cocotb.test()
async def a_count_is_patched_wherever_the_word_of_its_descriptor_is(dut: Any) -> None:
    """A group is extended and closed for every position of its descriptor in a store word.

    The values in front move the descriptor through a 64-byte word, and the
    idle cycles between the tiles decide whether the word is still filling,
    has just been completed or is already in the frame memory when the count
    is patched.
    """
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    template = frame(90, 0, (NumberGroup(ConcreteFormat.FP32, (0,)),), last=False)
    for prefix in range(1, 16):
        for gap in (0, 1, 2, 5):
            dut.rst_n.value = 0
            dut.s_tile_valid.value = 0
            dut.m_axis_tready.value = 0
            dut.s_mtu.value = 576
            dut.s_kulisch_bits.value = 320
            dut.s_tags.value = 0
            dut.s_integers.value = 0
            dut.s_header_beat.value = int.from_bytes(template[:64], "little")
            dut.s_total_elements.value = prefix + 64
            for _ in range(4):
                await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            dut.rst_n.value = 1
            receiver = cocotb.start_soon(receive(dut, 1, stall=False))
            tiles = (
                (ConcreteFormat.FP32, 0x3F800000, prefix),
                (ConcreteFormat.INT8, 7, 16),
                (ConcreteFormat.INT8, 7, 16),
                (ConcreteFormat.INT8, 7, 16),
                (ConcreteFormat.FP16, 0x3C00, 16),
            )
            first = 0
            for fmt, value, count in tiles:
                await FallingEdge(dut.clk)
                dut.s_tile_first_element.value = first
                dut.s_tile_count.value = count
                dut.s_formats.value = sum(int(fmt) << (lane * 8) for lane in range(count))
                dut.s_native_bits.value = sum(value << (lane * 32) for lane in range(count))
                dut.s_tile_valid.value = 1
                await ReadOnly()
                assert int(dut.s_tile_ready.value), (prefix, gap, first)
                await RisingEdge(dut.clk)
                first += count
                if gap:
                    await FallingEdge(dut.clk)
                    dut.s_tile_valid.value = 0
                    for _ in range(gap - 1):
                        await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            dut.s_tile_valid.value = 0
            assert await receiver == [
                frame(
                    90,
                    0,
                    (
                        NumberGroup(ConcreteFormat.FP32, (0x3F800000,) * prefix),
                        NumberGroup(ConcreteFormat.INT8, (7,) * 48),
                        NumberGroup(ConcreteFormat.FP16, (0x3C00,) * 16),
                    ),
                    last=True,
                )
            ], (prefix, gap)
            await FallingEdge(dut.clk)
