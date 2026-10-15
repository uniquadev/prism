"""Canonical NumberGroup DATA/RES Ethernet codec (no legacy decoding)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from ..domain.model import FORMAT_BYTES, ConcreteFormat, OperationKey
from ..domain.numbers import kulisch_element_bytes

ETHERTYPE = 0x88B5
VERSION_MAJOR = 2
VERSION_MINOR = 0
ETHERNET_HEADER_BYTES = 14
CONTROL_WORD_BYTES = 2
DATA_HEADER_BYTES = 40
GROUP_DESCRIPTOR_BYTES = 4
ACCUMULATION_INEXACT_FLAG = 0x02
MIN_ETHERNET_FRAME_BYTES = 60  # excludes FCS

_ETHERNET = struct.Struct("!6s6sH")
_DATA_HEADER = struct.Struct("!QHHHIHHIIHBBHHH")
_GROUP_HEADER = struct.Struct("!BBH")
assert _DATA_HEADER.size == DATA_HEADER_BYTES


class PacketClass(IntEnum):
    CONTROL = 0x01
    DATA = 0x02
    RESULT = 0x03
    PROGRESS = 0x04


def _unsigned(name: str, value: int, bits: int) -> None:
    if not 0 <= value < 1 << bits:
        raise ValueError(f"{name} exceeds {bits} bits")


def _element_width(fmt: ConcreteFormat, kulisch_bits: int) -> int:
    return (
        kulisch_element_bytes(kulisch_bits) if fmt == ConcreteFormat.KULISCH else FORMAT_BYTES[fmt]
    )


@dataclass(frozen=True, slots=True)
class NumberGroup:
    format: ConcreteFormat
    values: tuple[int | bytes, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.values) <= 65535:
            raise ValueError("NumberGroup count must be in 1..65535")
        if self.format == ConcreteFormat.KULISCH:
            if any(not isinstance(value, bytes) for value in self.values):
                raise ValueError("Kulisch values must be canonical element bytes")
        else:
            width = FORMAT_BYTES[self.format]
            if any(
                not isinstance(value, int) or not 0 <= value < 1 << (8 * width)
                for value in self.values
            ):
                raise ValueError("native value exceeds its concrete format")

    def pack(self, kulisch_bits: int) -> bytes:
        width = _element_width(self.format, kulisch_bits)
        if self.format == ConcreteFormat.KULISCH:
            from ..domain.numbers import decode_kulisch

            if any(len(value) != width for value in self.values if isinstance(value, bytes)):
                raise ValueError("Kulisch element width differs from operation configuration")
            for value in self.values:
                assert isinstance(value, bytes)
                decode_kulisch(value, kulisch_bits)
            payload = b"".join(value for value in self.values if isinstance(value, bytes))
        else:
            payload = b"".join(
                value.to_bytes(width, "little") for value in self.values if isinstance(value, int)
            )
        padding = bytes((-len(payload)) % 4)
        return _GROUP_HEADER.pack(int(self.format), 0, len(self.values)) + payload + padding


@dataclass(frozen=True, slots=True)
class DataPacket:
    packet_class: PacketClass
    operation: OperationKey
    source_endpoint: int
    destination_endpoint: int
    stream_id: int  # DATA contributor ID, RESULT result-path ID
    packet_id: int
    first_element: int
    groups: tuple[NumberGroup, ...]
    last: bool = False
    accumulation_inexact: bool = False

    def __post_init__(self) -> None:
        if self.packet_class not in (PacketClass.DATA, PacketClass.RESULT):
            raise ValueError("DataPacket class must be DATA or RESULT")
        for name, bits in (
            ("source_endpoint", 16),
            ("destination_endpoint", 16),
            ("stream_id", 16),
            ("packet_id", 32),
            ("first_element", 32),
        ):
            _unsigned(name, getattr(self, name), bits)
        if self.accumulation_inexact:
            if not self.last or self.groups:
                raise ValueError("ACCUMULATION_INEXACT is terminal and carries no values")
        else:
            if not 1 <= len(self.groups) <= 255:
                raise ValueError("DATA/RES packet must contain 1..255 NumberGroups")
            if not 1 <= self.element_count <= 65535:
                raise ValueError("packet element count must be in 1..65535")
        if self.first_element + self.element_count > 1 << 32:
            raise ValueError("packet element interval exceeds 32-bit vector space")

    @property
    def element_count(self) -> int:
        return sum(len(group.values) for group in self.groups)


def encode_data_frame(
    packet: DataPacket,
    *,
    destination_mac: bytes,
    source_mac: bytes,
    mtu: int,
    kulisch_bits: int,
) -> bytes:
    if len(destination_mac) != 6 or len(source_mac) != 6:
        raise ValueError("Ethernet MAC must be six bytes")
    if not 576 <= mtu <= 9216:
        raise ValueError("unsupported Ethernet payload MTU")
    body = b"".join(group.pack(kulisch_bits) for group in packet.groups)
    _unsigned("body_bytes", len(body), 16)
    if CONTROL_WORD_BYTES + DATA_HEADER_BYTES + len(body) > mtu:
        raise ValueError("header + groups + values + padding exceed MTU")
    flags = int(packet.last) | (ACCUMULATION_INEXACT_FLAG if packet.accumulation_inexact else 0)
    header = _DATA_HEADER.pack(
        packet.operation.job_id,
        packet.operation.group_id,
        packet.operation.group_generation,
        packet.operation.operation_id,
        packet.operation.operation_generation,
        packet.source_endpoint,
        packet.destination_endpoint,
        packet.packet_id,
        packet.first_element,
        packet.element_count,
        len(packet.groups),
        flags,
        len(body),
        packet.stream_id,
        0,
    )
    control = bytes([(VERSION_MAJOR << 4) | VERSION_MINOR, int(packet.packet_class)])
    frame = _ETHERNET.pack(destination_mac, source_mac, ETHERTYPE) + control + header + body
    return frame + bytes(max(0, MIN_ETHERNET_FRAME_BYTES - len(frame)))


def decode_data_frame(frame: bytes, *, mtu: int, kulisch_bits: int) -> DataPacket:
    if len(frame) < max(
        MIN_ETHERNET_FRAME_BYTES, ETHERNET_HEADER_BYTES + CONTROL_WORD_BYTES + DATA_HEADER_BYTES
    ):
        raise ValueError("truncated DATA/RES frame")
    if not 576 <= mtu <= 9216:
        raise ValueError("unsupported Ethernet payload MTU")
    _dst, _src, ethertype = _ETHERNET.unpack_from(frame)
    if ethertype != ETHERTYPE:
        raise ValueError("not a PRISM Ethernet frame")
    offset = ETHERNET_HEADER_BYTES
    if frame[offset] != (VERSION_MAJOR << 4) | VERSION_MINOR:
        raise ValueError("incompatible PRISM version")
    try:
        packet_class = PacketClass(frame[offset + 1])
    except ValueError as error:
        raise ValueError("unknown PRISM packet class") from error
    if packet_class not in (PacketClass.DATA, PacketClass.RESULT):
        raise ValueError("not a DATA/RES frame")
    (
        job_id,
        group_id,
        group_generation,
        operation_id,
        operation_generation,
        source_endpoint,
        destination_endpoint,
        packet_id,
        first_element,
        element_count,
        group_count,
        flags,
        body_bytes,
        stream_id,
        reserved,
    ) = _DATA_HEADER.unpack_from(frame, offset + CONTROL_WORD_BYTES)
    if reserved or flags & ~(0x01 | ACCUMULATION_INEXACT_FLAG):
        raise ValueError("invalid DATA/RES header")
    if CONTROL_WORD_BYTES + DATA_HEADER_BYTES + body_bytes > mtu:
        raise ValueError("declared packet body exceeds MTU")
    body_offset = offset + CONTROL_WORD_BYTES + DATA_HEADER_BYTES
    body_end = body_offset + body_bytes
    if len(frame) < body_end:
        raise ValueError("truncated NumberGroup body")
    if len(frame) > max(MIN_ETHERNET_FRAME_BYTES, body_end) or any(frame[body_end:]):
        raise ValueError("nonzero or excessive Ethernet padding")
    if flags & ACCUMULATION_INEXACT_FLAG:
        if flags != 0x03 or element_count or group_count or body_bytes:
            raise ValueError("invalid ACCUMULATION_INEXACT frame")
        return DataPacket(
            packet_class,
            OperationKey(job_id, group_id, group_generation, operation_id, operation_generation),
            source_endpoint,
            destination_endpoint,
            stream_id,
            packet_id,
            first_element,
            (),
            last=True,
            accumulation_inexact=True,
        )
    if not element_count or not group_count:
        raise ValueError("invalid DATA/RES header")
    groups: list[NumberGroup] = []
    cursor = body_offset
    for _ in range(group_count):
        if cursor + GROUP_DESCRIPTOR_BYTES > body_end:
            raise ValueError("truncated NumberGroup descriptor")
        raw_format, group_flags, count = _GROUP_HEADER.unpack_from(frame, cursor)
        cursor += GROUP_DESCRIPTOR_BYTES
        if group_flags or count == 0:
            raise ValueError("invalid NumberGroup descriptor")
        try:
            fmt = ConcreteFormat(raw_format)
        except ValueError as error:
            raise ValueError("unknown concrete NumberGroup format") from error
        width = _element_width(fmt, kulisch_bits)
        payload_bytes = count * width
        pad_bytes = (-payload_bytes) % 4
        if cursor + payload_bytes + pad_bytes > body_end:
            raise ValueError("truncated NumberGroup values or padding")
        payload = frame[cursor : cursor + payload_bytes]
        cursor += payload_bytes
        if any(frame[cursor : cursor + pad_bytes]):
            raise ValueError("nonzero NumberGroup padding")
        cursor += pad_bytes
        if fmt == ConcreteFormat.KULISCH:
            from ..domain.numbers import decode_kulisch

            values: tuple[int | bytes, ...] = tuple(
                payload[index : index + width] for index in range(0, len(payload), width)
            )
            for value in values:
                assert isinstance(value, bytes)
                decode_kulisch(value, kulisch_bits)
        else:
            values = tuple(
                int.from_bytes(payload[index : index + width], "little")
                for index in range(0, len(payload), width)
            )
        groups.append(NumberGroup(fmt, values))
    if cursor != body_end or sum(len(group.values) for group in groups) != element_count:
        raise ValueError("NumberGroup counts do not match packet header")
    return DataPacket(
        packet_class,
        OperationKey(job_id, group_id, group_generation, operation_id, operation_generation),
        source_endpoint,
        destination_endpoint,
        stream_id,
        packet_id,
        first_element,
        tuple(groups),
        bool(flags & 1),
    )
