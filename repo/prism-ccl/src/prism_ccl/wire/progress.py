"""Hop-local ACK, gap and byte/interval credit frames."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from ..domain.model import OperationKey
from .data import ETHERTYPE, MIN_ETHERNET_FRAME_BYTES, VERSION_MAJOR, VERSION_MINOR, PacketClass

PROGRESS_HEADER_BYTES = 44
_ETHERNET = struct.Struct("!6s6sH")
_PROGRESS = struct.Struct("!QHHHI HHH II HI BB HH")
_HOLE = struct.Struct("!II")
assert _PROGRESS.size == PROGRESS_HEADER_BYTES


class ProgressStatus(IntEnum):
    ACCEPTED = 0
    DUPLICATE = 1
    RETRY = 2
    OUT_OF_WINDOW = 3
    REJECTED = 4


@dataclass(frozen=True, slots=True)
class ProgressPacket:
    operation: OperationKey
    source_endpoint: int
    destination_endpoint: int
    stream_id: int
    packet_id: int
    cumulative_element: int
    credit_intervals: int
    credit_bytes: int
    status: ProgressStatus
    complete: bool = False
    holes: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        for name, bits in (
            ("source_endpoint", 16),
            ("destination_endpoint", 16),
            ("stream_id", 16),
            ("packet_id", 32),
            ("cumulative_element", 32),
            ("credit_intervals", 16),
            ("credit_bytes", 32),
        ):
            if not 0 <= getattr(self, name) < 1 << bits:
                raise ValueError(f"{name} exceeds {bits} bits")
        if len(self.holes) > 32 or any(
            not 0 <= first < last < 1 << 32 for first, last in self.holes
        ):
            raise ValueError("invalid selective gap intervals")
        if tuple(sorted(self.holes)) != self.holes:
            raise ValueError("gap intervals must be sorted")


def encode_progress_frame(
    packet: ProgressPacket, *, destination_mac: bytes, source_mac: bytes, mtu: int
) -> bytes:
    if len(destination_mac) != 6 or len(source_mac) != 6:
        raise ValueError("Ethernet MAC must be six bytes")
    body = b"".join(_HOLE.pack(first, last) for first, last in packet.holes)
    if not 576 <= mtu <= 9216 or 2 + PROGRESS_HEADER_BYTES + len(body) > mtu:
        raise ValueError("PROGRESS exceeds negotiated MTU")
    header = _PROGRESS.pack(
        packet.operation.job_id,
        packet.operation.group_id,
        packet.operation.group_generation,
        packet.operation.operation_id,
        packet.operation.operation_generation,
        packet.source_endpoint,
        packet.destination_endpoint,
        packet.stream_id,
        packet.packet_id,
        packet.cumulative_element,
        packet.credit_intervals,
        packet.credit_bytes,
        int(packet.status),
        int(packet.complete),
        len(packet.holes),
        0,
    )
    frame = (
        _ETHERNET.pack(destination_mac, source_mac, ETHERTYPE)
        + bytes([(VERSION_MAJOR << 4) | VERSION_MINOR, int(PacketClass.PROGRESS)])
        + header
        + body
    )
    return frame + bytes(max(0, MIN_ETHERNET_FRAME_BYTES - len(frame)))


def decode_progress_frame(frame: bytes, *, mtu: int) -> ProgressPacket:
    if len(frame) < max(MIN_ETHERNET_FRAME_BYTES, 14 + 2 + PROGRESS_HEADER_BYTES):
        raise ValueError("truncated PROGRESS frame")
    _dst, _src, ethertype = _ETHERNET.unpack_from(frame)
    if ethertype != ETHERTYPE or frame[14:16] != bytes(
        [(VERSION_MAJOR << 4) | VERSION_MINOR, int(PacketClass.PROGRESS)]
    ):
        raise ValueError("invalid PROGRESS frame type or version")
    (
        job_id,
        group_id,
        group_generation,
        operation_id,
        operation_generation,
        source_endpoint,
        destination_endpoint,
        stream_id,
        packet_id,
        cumulative_element,
        credit_intervals,
        credit_bytes,
        status,
        flags,
        hole_count,
        reserved,
    ) = _PROGRESS.unpack_from(frame, 16)
    end = 14 + 2 + PROGRESS_HEADER_BYTES + hole_count * _HOLE.size
    if (
        reserved
        or flags & ~1
        or hole_count > 32
        or 2 + PROGRESS_HEADER_BYTES + hole_count * _HOLE.size > mtu
        or len(frame) < end
    ):
        raise ValueError("invalid PROGRESS length or reserved field")
    if len(frame) > max(MIN_ETHERNET_FRAME_BYTES, end) or any(frame[end:]):
        raise ValueError("invalid Ethernet padding")
    holes = tuple(
        _HOLE.unpack_from(frame, 14 + 2 + PROGRESS_HEADER_BYTES + index * 8)
        for index in range(hole_count)
    )
    return ProgressPacket(
        OperationKey(job_id, group_id, group_generation, operation_id, operation_generation),
        source_endpoint,
        destination_endpoint,
        stream_id,
        packet_id,
        cumulative_element,
        credit_intervals,
        credit_bytes,
        ProgressStatus(status),
        bool(flags),
        holes,
    )
