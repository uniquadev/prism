from __future__ import annotations

import random

import pytest

from prism_ccl.application.packing import (
    fixed_groups,
    group_cost,
    optimize_reference,
    optimize_reference_line_bytes,
    packetize,
    select_auto_groups,
)
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import decode_native
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)


def _cost(groups: object, width: int) -> int:
    return sum(group_cost(group.format, len(group.values), width) for group in groups)  # type: ignore[attr-defined]


def test_auto_coalesces_incomparable_native_formats() -> None:
    values = (
        decode_native(0x3C01, ConcreteFormat.FP16),
        decode_native(0x0001, ConcreteFormat.BF16),
    )
    groups = tuple(select_auto_groups(values, 279))
    assert len(groups) == 1
    assert groups[0].format == ConcreteFormat.FP32
    assert len(groups[0].values) == 2
    assert _cost(groups, 279) == 12


def test_bounded_auto_against_exact_reference_and_fixed_fp32() -> None:
    rng = random.Random(0xC011EC7)
    source = (
        (ConcreteFormat.INT8, 0x81),
        (ConcreteFormat.FP16, 0x3C01),
        (ConcreteFormat.BF16, 0x0001),
        (ConcreteFormat.FP32, 0x3F800001),
    )
    for length in range(1, 13):
        for _ in range(20):
            values = tuple(decode_native(*rng.choice(source)[::-1]) for _ in range(length))
            auto = tuple(select_auto_groups(values, 279))
            optimum = optimize_reference(values, 279)
            fixed = tuple(fixed_groups(values, ConcreteFormat.FP32, 279))
            assert _cost(auto, 279) >= _cost(optimum, 279)
            assert _cost(optimum, 279) <= _cost(fixed, 279)
            assert sum(len(group.values) for group in auto) == length


def test_packetizer_splits_long_group_without_preserving_input_chunks() -> None:
    values = tuple(decode_native(0x3F800000, ConcreteFormat.FP32) for _ in range(401))
    groups = fixed_groups(values, ConcreteFormat.FP32, 279)
    key = OperationKey(1, 2, 3, 4, 5)
    packets = tuple(
        packetize(
            groups,
            packet_class=PacketClass.DATA,
            operation=key,
            source_endpoint=1,
            destination_endpoint=2,
            stream_id=3,
            first_element=17,
            mtu=576,
            kulisch_bits=279,
        )
    )
    assert len(packets) >= 3
    assert sum(packet.element_count for packet in packets) == 401
    assert packets[0].first_element == 17
    assert packets[-1].first_element + packets[-1].element_count == 418
    assert [packet.last for packet in packets] == [False] * (len(packets) - 1) + [True]
    for packet in packets:
        frame = encode_data_frame(
            packet,
            destination_mac=bytes.fromhex("001122334455"),
            source_mac=bytes.fromhex("66778899aabb"),
            mtu=576,
            kulisch_bits=279,
        )
        assert len(frame) - 14 <= 576
        assert decode_data_frame(frame, mtu=576, kulisch_bits=279) == packet


@pytest.mark.parametrize("mtu,maximum", [(576, 528), (1500, 1452)])
def test_int8_group_maximum_is_set_by_mtu(mtu: int, maximum: int) -> None:
    key = OperationKey(1, 2, 3, 4, 5)
    group = NumberGroup(ConcreteFormat.INT8, (1,) * (maximum + 1))
    packets = tuple(
        packetize(
            (group,),
            packet_class=PacketClass.DATA,
            operation=key,
            source_endpoint=1,
            destination_endpoint=2,
            stream_id=3,
            first_element=0,
            mtu=mtu,
            kulisch_bits=279,
        )
    )
    assert [packet.element_count for packet in packets] == [maximum, 1]
    assert [packet.first_element for packet in packets] == [0, maximum]
    with pytest.raises(ValueError, match="exceed MTU"):
        encode_data_frame(
            DataPacket(PacketClass.DATA, key, 1, 2, 3, 0, 0, (group,), last=True),
            destination_mac=bytes.fromhex("001122334455"),
            source_mac=bytes.fromhex("66778899aabb"),
            mtu=mtu,
            kulisch_bits=279,
        )


def test_auto_total_line_cost_against_global_oracle_and_fixed_format() -> None:
    rng = random.Random(0x715EED)
    choices = (
        (ConcreteFormat.INT8, 0xFE),
        (ConcreteFormat.FP16, 0x3C01),
        (ConcreteFormat.BF16, 0x0001),
        (ConcreteFormat.FP32, 0x3F800001),
    )
    key = OperationKey(9, 8, 7, 6, 5)
    for mtu in (576, 1500):
        for length in (1, 2, 3, 5, 8, 9, 12):
            for _ in range(3):
                values = tuple(decode_native(*rng.choice(choices)[::-1]) for _ in range(length))
                auto_packets = tuple(
                    packetize(
                        select_auto_groups(values, 279),
                        packet_class=PacketClass.DATA,
                        operation=key,
                        source_endpoint=1,
                        destination_endpoint=2,
                        stream_id=3,
                        first_element=0,
                        mtu=mtu,
                        kulisch_bits=279,
                    )
                )
                fixed_packets = tuple(
                    packetize(
                        fixed_groups(values, ConcreteFormat.FP32, 279),
                        packet_class=PacketClass.DATA,
                        operation=key,
                        source_endpoint=1,
                        destination_endpoint=2,
                        stream_id=3,
                        first_element=0,
                        mtu=mtu,
                        kulisch_bits=279,
                    )
                )
                auto_cost = sum(
                    80 + sum(group_cost(g.format, len(g.values), 279) for g in p.groups)
                    for p in auto_packets
                )
                fixed_cost = sum(
                    80 + sum(group_cost(g.format, len(g.values), 279) for g in p.groups)
                    for p in fixed_packets
                )
                optimum = optimize_reference_line_bytes(values, 279, mtu)
                assert optimum <= auto_cost
                assert optimum <= fixed_cost
                assert sum(p.element_count for p in auto_packets) == length
