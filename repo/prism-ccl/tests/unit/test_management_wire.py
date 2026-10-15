from __future__ import annotations

import pytest

from prism_ccl.domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationKey,
    PartialWirePolicy,
)
from prism_ccl.wire.control import (
    ContextRecord,
    ControlCommand,
    ControlPacket,
    EndpointBindingRecord,
    NodeRole,
    PeerKind,
    decode_control_frame,
    encode_control_frame,
)
from prism_ccl.wire.progress import (
    ProgressPacket,
    ProgressStatus,
    decode_progress_frame,
    encode_progress_frame,
)

KEY = OperationKey(1, 2, 3, 4, 5)
DST = bytes.fromhex("001122334455")
SRC = bytes.fromhex("66778899aabb")


def test_stage_context_is_canonical_and_atomic() -> None:
    record = ContextRecord(
        NodeRole.ROOT,
        None,
        (10, 11),
        (10,),
        4,
        8,
        8192,
        16,
        280,
        1500,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.AUTO,
        ConcreteFormat.FP32,
        frozenset({ConcreteFormat.FP16, ConcreteFormat.KULISCH}),
        CollectiveKind.REDUCE,
        SRC,
        1,
        4,
        frozenset({ConcreteFormat.FP16}),
        (
            EndpointBindingRecord(
                10,
                1,
                2,
                PeerKind.RANK,
                bytes.fromhex("020000000001"),
                0,
                1,
                frozenset({ConcreteFormat.FP16}),
                True,
            ),
            EndpointBindingRecord(
                11,
                1,
                3,
                PeerKind.PRISM,
                bytes.fromhex("020000000002"),
                None,
                3,
                frozenset({ConcreteFormat.KULISCH}),
            ),
        ),
    )
    packet = ControlPacket(KEY, 99, 1, 2, ControlCommand.STAGE, body=record.pack())
    frame = encode_control_frame(packet, destination_mac=DST, source_mac=SRC, mtu=1500)
    assert decode_control_frame(frame, mtu=1500) == packet
    assert ContextRecord.unpack(packet.body) == record
    invalid = bytearray(frame)
    invalid[48 + 3] = 1  # context reserved flags
    with pytest.raises(ValueError):
        decode_control_frame(bytes(invalid), mtu=1500)


def test_progress_acks_holes_and_credits() -> None:
    packet = ProgressPacket(
        KEY, 2, 1, 3, 7, 100, 4, 4096, ProgressStatus.RETRY, holes=((100, 110), (120, 130))
    )
    frame = encode_progress_frame(packet, destination_mac=DST, source_mac=SRC, mtu=1500)
    assert decode_progress_frame(frame, mtu=1500) == packet
    bad = bytearray(frame)
    bad[59] = 1  # PROGRESS reserved header byte, not a hole byte
    with pytest.raises(ValueError, match="reserved"):
        decode_progress_frame(bytes(bad), mtu=1500)


def test_control_ethernet_padding_must_be_zero() -> None:
    packet = ControlPacket(KEY, 99, 1, 2, ControlCommand.ACK)
    frame = bytearray(encode_control_frame(packet, destination_mac=DST, source_mac=SRC, mtu=1500))
    assert len(frame) == 60
    frame[-1] = 1
    with pytest.raises(ValueError, match="padding"):
        decode_control_frame(bytes(frame), mtu=1500)
    with pytest.raises(ValueError, match="truncated"):
        decode_control_frame(bytes(frame[:59]), mtu=1500)


def test_progress_requires_complete_minimum_frame_and_encodable_holes() -> None:
    packet = ProgressPacket(KEY, 2, 1, 3, 7, 0, 1, 1500, ProgressStatus.ACCEPTED)
    frame = encode_progress_frame(packet, destination_mac=DST, source_mac=SRC, mtu=1500)
    with pytest.raises(ValueError, match="truncated"):
        decode_progress_frame(frame[:59], mtu=1500)
    with pytest.raises(ValueError, match="gap"):
        ProgressPacket(KEY, 2, 1, 3, 7, 0, 1, 1500, ProgressStatus.ACCEPTED, holes=((0, 1 << 32),))
