"""Independent ABI bytes and adversarial NumberGroup parser checks."""

from __future__ import annotations

from fractions import Fraction

import pytest

from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import (
    ExactValue,
    decode_kulisch,
    decode_native,
    encode_kulisch,
    encode_native_lossless,
    required_kulisch_bits,
)
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)

KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
DST = bytes.fromhex("001122334455")
SRC = bytes.fromhex("66778899aabb")

# Independently transcribed from the field table, not produced by either codec.
GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 02 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0102 0304 0a0b0c0d 00000009 0003 02 01 0010 0f10 0000 "
    "01 00 0002 7f80 0000 "
    "02 00 0001 003c 0000"
)

ERROR_RESULT_GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 03 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0102 0304 0a0b0c0d 00000009 0000 00 03 0000 0f10 0000 "
    "00000000"
)


def _packet() -> DataPacket:
    return DataPacket(
        PacketClass.DATA,
        KEY,
        0x0102,
        0x0304,
        0x0F10,
        0x0A0B0C0D,
        9,
        (
            NumberGroup(ConcreteFormat.INT8, (0x7F, 0x80)),
            NumberGroup(ConcreteFormat.FP16, (0x3C00,)),
        ),
        last=True,
    )


def test_golden_bytes_independent_of_round_trip() -> None:
    assert (
        encode_data_frame(
            _packet(), destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
        )
        == GOLDEN
    )
    assert decode_data_frame(GOLDEN, mtu=1500, kulisch_bits=279) == _packet()


def test_terminal_accumulation_error_is_distinct_from_delivery_ack() -> None:
    error = DataPacket(
        PacketClass.RESULT,
        KEY,
        0x0102,
        0x0304,
        0x0F10,
        0x0A0B0C0D,
        9,
        (),
        last=True,
        accumulation_inexact=True,
    )
    assert (
        encode_data_frame(error, destination_mac=DST, source_mac=SRC, mtu=576, kulisch_bits=279)
        == ERROR_RESULT_GOLDEN
    )
    assert decode_data_frame(ERROR_RESULT_GOLDEN, mtu=576, kulisch_bits=279) == error
    corrupted = bytearray(GOLDEN)
    corrupted[49] |= 0x02
    with pytest.raises(ValueError, match="ACCUMULATION_INEXACT"):
        decode_data_frame(bytes(corrupted), mtu=1500, kulisch_bits=279)
    with pytest.raises(ValueError, match="terminal"):
        DataPacket(PacketClass.DATA, KEY, 1, 2, 3, 4, 0, (), accumulation_inexact=True)


@pytest.mark.parametrize("offset", [0, 13, 15, 28, 55, 59, 65, 70])
def test_truncated_frame_rejected(offset: int) -> None:
    with pytest.raises(ValueError):
        decode_data_frame(GOLDEN[:offset], mtu=1500, kulisch_bits=279)


def test_invalid_counts_padding_and_boundaries() -> None:
    bad_count = bytearray(GOLDEN)
    bad_count[46:48] = (4).to_bytes(2, "big")  # header element count
    with pytest.raises(ValueError, match="counts"):
        decode_data_frame(bytes(bad_count), mtu=1500, kulisch_bits=279)
    bad_padding = bytearray(GOLDEN)
    bad_padding[-1] = 1
    with pytest.raises(ValueError, match="padding"):
        decode_data_frame(bytes(bad_padding), mtu=1500, kulisch_bits=279)
    with pytest.raises(ValueError, match="MTU"):
        decode_data_frame(GOLDEN, mtu=576, kulisch_bits=279) if len(
            GOLDEN
        ) > 576 else decode_data_frame(GOLDEN, mtu=575, kulisch_bits=279)
    with pytest.raises(ValueError, match="interval"):
        DataPacket(
            PacketClass.DATA,
            KEY,
            1,
            2,
            0,
            0,
            (1 << 32) - 1,
            (NumberGroup(ConcreteFormat.INT8, (1, 2)),),
        )
    with pytest.raises(ValueError, match="count"):
        NumberGroup(ConcreteFormat.INT8, ())


def test_exact_subnormal_and_kulisch_specials() -> None:
    subnormal = decode_native(1, ConcreteFormat.FP32)
    assert subnormal.value == Fraction(1, 1 << 149)
    width = required_kulisch_bits(4)
    assert width == 280
    encoded = encode_kulisch(subnormal, width)
    assert len(encoded) == 36
    assert encoded[:3] == b"\x00\x01\x00"
    assert decode_kulisch(encoded, width) == subnormal
    negative_zero = ExactValue("zero", True, Fraction(0))
    assert encode_native_lossless(negative_zero, ConcreteFormat.FP16) == 0x8000
    assert decode_kulisch(encode_kulisch(negative_zero, width), width) == negative_zero
    with pytest.raises(ValueError, match="INT8"):
        encode_native_lossless(ExactValue("finite", False, Fraction(128)), ConcreteFormat.INT8)


def test_one_widest_element_fits_minimum_mtu() -> None:
    value = encode_kulisch(ExactValue("finite", False, Fraction(1)), 4096)
    packet = DataPacket(
        PacketClass.RESULT,
        KEY,
        1,
        2,
        3,
        4,
        0,
        (NumberGroup(ConcreteFormat.KULISCH, (value,)),),
        last=True,
    )
    frame = encode_data_frame(
        packet, destination_mac=DST, source_mac=SRC, mtu=576, kulisch_bits=4096
    )
    assert len(frame) - 14 <= 576
    assert decode_data_frame(frame, mtu=576, kulisch_bits=4096) == packet
