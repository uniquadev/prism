"""Transactional in-band AM command and context-record codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from ..domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationKey,
    PartialWirePolicy,
    ResultWirePolicy,
)
from .data import ETHERTYPE, MIN_ETHERNET_FRAME_BYTES, VERSION_MAJOR, VERSION_MINOR, PacketClass

CONTROL_HEADER_BYTES = 32
CONTEXT_FIXED_BYTES = 48
ENDPOINT_BINDING_BYTES = 24
_ETHERNET = struct.Struct("!6s6sH")
_CONTROL = struct.Struct("!QHHHIIHHBBHBB")
_CONTEXT = struct.Struct("!BBBBHIHI IHHBBBBBBH")
_CONTEXT_EXTENSION = struct.Struct("!6sHI B3s")
_BINDING = struct.Struct("!HHHBB6sHIB3s")
assert _CONTROL.size == CONTROL_HEADER_BYTES
assert _CONTEXT.size == 32
assert _CONTEXT_EXTENSION.size == 16
assert _BINDING.size == ENDPOINT_BINDING_BYTES


class ControlCommand(IntEnum):
    STAGE = 0x01
    COMMIT = 0x02
    COMPLETE = 0x03
    RELEASE = 0x04
    ACK = 0x05
    ABORT = 0x06
    CAPS_QUERY = 0x07
    CAPS_RESPONSE = 0x08


class NodeRole(IntEnum):
    SINGLE = 0x01
    LEAF = 0x02
    INTERNAL = 0x03
    ROOT = 0x04


class ControlStatus(IntEnum):
    OK = 0
    INVALID = 1
    UNSUPPORTED = 2
    NO_RESOURCE = 3
    BAD_STATE = 4
    STALE_GENERATION = 5
    TRANSACTION_CONFLICT = 6
    BINDING_INVALID = 7


class PeerKind(IntEnum):
    RANK = 1
    PRISM = 2


_FORMAT_BIT = {
    ConcreteFormat.INT8: 1 << 0,
    ConcreteFormat.FP16: 1 << 1,
    ConcreteFormat.BF16: 1 << 2,
    ConcreteFormat.FP32: 1 << 3,
    ConcreteFormat.KULISCH: 1 << 4,
}


@dataclass(frozen=True, slots=True)
class EndpointBindingRecord:
    local_endpoint: int
    peer_endpoint: int
    local_port: int
    peer_kind: PeerKind
    peer_mac: bytes
    rank_id: int | None
    original_terms: int
    formats: frozenset[ConcreteFormat]
    result_enabled: bool = False

    def pack(self) -> bytes:
        if (
            not 0 <= self.local_endpoint < 0xFFFF
            or not 0 <= self.peer_endpoint < 0xFFFF
            or not 0 <= self.local_port < 1 << 16
            or len(self.peer_mac) != 6
            or not 0 <= self.original_terms < 1 << 32
            or not self.formats
        ):
            raise ValueError("invalid endpoint binding")
        if self.peer_kind == PeerKind.RANK:
            if self.rank_id is None or not 0 <= self.rank_id < 0xFFFF or self.original_terms != 1:
                raise ValueError("rank binding needs one identified original term")
            if len(self.formats) != 1 or ConcreteFormat.KULISCH in self.formats:
                raise ValueError("rank binding needs one native format")
        elif self.rank_id is not None:
            raise ValueError("PRISM binding cannot have a rank ID")
        return _BINDING.pack(
            self.local_endpoint,
            self.peer_endpoint,
            self.local_port,
            int(self.peer_kind),
            int(self.result_enabled),
            self.peer_mac,
            0xFFFF if self.rank_id is None else self.rank_id,
            self.original_terms,
            sum(_FORMAT_BIT[fmt] for fmt in self.formats),
            bytes(3),
        )

    @classmethod
    def unpack(cls, data: bytes) -> EndpointBindingRecord:
        if len(data) != ENDPOINT_BINDING_BYTES:
            raise ValueError("truncated endpoint binding")
        local, peer, port, kind, flags, mac, rank, terms, mask, reserved = _BINDING.unpack(data)
        if flags & ~1 or mask & ~0x1F or reserved != bytes(3):
            raise ValueError("noncanonical endpoint binding")
        binding = cls(
            local,
            peer,
            port,
            PeerKind(kind),
            mac,
            None if rank == 0xFFFF else rank,
            terms,
            frozenset(fmt for fmt, bit in _FORMAT_BIT.items() if mask & bit),
            bool(flags),
        )
        if binding.pack() != data:
            raise ValueError("noncanonical endpoint binding")
        return binding


@dataclass(frozen=True, slots=True)
class ContextRecord:
    role: NodeRole
    parent_endpoint: int | None
    child_endpoints: tuple[int, ...]
    result_endpoints: tuple[int, ...]
    original_terms: int
    window_intervals: int
    window_bytes: int
    element_count: int
    kulisch_bits: int
    mtu: int
    accumulator: AccumulatorPolicy
    partial_wire: PartialWirePolicy
    output_format: ResultWirePolicy
    accepted_formats: frozenset[ConcreteFormat]
    kind: CollectiveKind
    manager_mac: bytes
    manager_port: int
    maximum_original_terms: int
    rank_formats: frozenset[ConcreteFormat]
    bindings: tuple[EndpointBindingRecord, ...]

    def pack(self) -> bytes:
        if not 1 <= len(self.child_endpoints) <= 255 or len(self.result_endpoints) > 255:
            raise ValueError("context child/result counts exceed one-byte fields")
        if not self.accepted_formats:
            raise ValueError("context must advertise concrete accepted formats")
        for name, bits in (
            ("original_terms", 32),
            ("window_intervals", 16),
            ("window_bytes", 32),
            ("element_count", 32),
            ("kulisch_bits", 16),
            ("mtu", 16),
        ):
            if not 0 <= getattr(self, name) < 1 << bits:
                raise ValueError(f"context {name} exceeds {bits} bits")
        if (
            len(self.manager_mac) != 6
            or not 0 <= self.manager_port < 1 << 16
            or not 1 <= self.maximum_original_terms < 1 << 32
            or not self.rank_formats
            or ConcreteFormat.KULISCH in self.rank_formats
        ):
            raise ValueError("invalid context management or rank format fields")
        if len(set(self.child_endpoints)) != len(self.child_endpoints):
            raise ValueError("duplicate child endpoint")
        for endpoint in (*self.child_endpoints, *self.result_endpoints):
            if not 0 <= endpoint < 0xFFFF:
                raise ValueError("context endpoint exceeds 16-bit namespace")
        parent = 0xFFFF if self.parent_endpoint is None else self.parent_endpoint
        if not 0 <= parent <= 0xFFFF or (self.parent_endpoint is not None and parent == 0xFFFF):
            raise ValueError("invalid parent endpoint")
        fixed = _CONTEXT.pack(
            int(self.role),
            len(self.child_endpoints),
            len(self.result_endpoints),
            0,
            parent,
            self.original_terms,
            self.window_intervals,
            self.window_bytes,
            self.element_count,
            self.kulisch_bits,
            self.mtu,
            int(AccumulatorPolicy(self.accumulator)),
            int(self.partial_wire),
            int(self.output_format),
            sum(_FORMAT_BIT[fmt] for fmt in self.accepted_formats),
            int(self.kind),
            0,
            0,
        )
        expected = (
            *(() if self.parent_endpoint is None else (self.parent_endpoint,)),
            *self.child_endpoints,
        )
        if tuple(binding.local_endpoint for binding in self.bindings) != expected:
            raise ValueError("binding order must be parent then children")
        if tuple(endpoint for endpoint in self.result_endpoints) != tuple(
            binding.local_endpoint
            for binding in self.bindings
            if binding.result_enabled and binding.local_endpoint in self.child_endpoints
        ):
            raise ValueError("result endpoints disagree with bindings")
        extension = _CONTEXT_EXTENSION.pack(
            self.manager_mac,
            self.manager_port,
            self.maximum_original_terms,
            sum(_FORMAT_BIT[fmt] for fmt in self.rank_formats),
            b"\0\0\0",
        )
        return (
            fixed
            + extension
            + b"".join(
                endpoint.to_bytes(2, "big")
                for endpoint in (*self.child_endpoints, *self.result_endpoints)
            )
            + b"".join(binding.pack() for binding in self.bindings)
        )

    @classmethod
    def unpack(cls, data: bytes) -> ContextRecord:
        if len(data) < CONTEXT_FIXED_BYTES:
            raise ValueError("truncated context record")
        (
            role,
            child_count,
            result_count,
            flags,
            parent,
            original_terms,
            window_intervals,
            window_bytes,
            element_count,
            kulisch_bits,
            mtu,
            accumulator,
            partial_wire,
            output_format,
            accepted_mask,
            kind,
            reserved8,
            reserved16,
        ) = _CONTEXT.unpack_from(data)
        if flags or reserved8 or reserved16 or child_count == 0 or accepted_mask & ~0x1F:
            raise ValueError("invalid context reserved fields or child count")
        binding_count = child_count + int(parent != 0xFFFF)
        if (
            len(data)
            != CONTEXT_FIXED_BYTES
            + 2 * (child_count + result_count)
            + ENDPOINT_BINDING_BYTES * binding_count
        ):
            raise ValueError("context endpoint count disagrees with payload")
        manager_mac, manager_port, maximum_terms, rank_mask, extension_reserved = (
            _CONTEXT_EXTENSION.unpack_from(data, 32)
        )
        if rank_mask & ~0x0F or extension_reserved != b"\0\0\0":
            raise ValueError("invalid context extension")
        endpoint_end = CONTEXT_FIXED_BYTES + 2 * (child_count + result_count)
        endpoint_bytes = data[CONTEXT_FIXED_BYTES:endpoint_end]
        endpoints = tuple(
            int.from_bytes(endpoint_bytes[index : index + 2], "big")
            for index in range(0, len(endpoint_bytes), 2)
        )
        record = cls(
            NodeRole(role),
            None if parent == 0xFFFF else parent,
            endpoints[:child_count],
            endpoints[child_count:],
            original_terms,
            window_intervals,
            window_bytes,
            element_count,
            kulisch_bits,
            mtu,
            AccumulatorPolicy(accumulator),
            PartialWirePolicy(partial_wire),
            ResultWirePolicy(output_format),
            frozenset(fmt for fmt, bit in _FORMAT_BIT.items() if accepted_mask & bit),
            CollectiveKind(kind),
            manager_mac,
            manager_port,
            maximum_terms,
            frozenset(fmt for fmt, bit in _FORMAT_BIT.items() if rank_mask & bit),
            tuple(
                EndpointBindingRecord.unpack(data[offset : offset + ENDPOINT_BINDING_BYTES])
                for offset in range(endpoint_end, len(data), ENDPOINT_BINDING_BYTES)
            ),
        )
        if record.pack() != data:
            raise ValueError("noncanonical context record")
        return record


@dataclass(frozen=True, slots=True)
class ControlPacket:
    operation: OperationKey
    transaction_id: int
    source_endpoint: int
    destination_endpoint: int
    command: ControlCommand
    status: int = 0
    body: bytes = b""
    fragment_index: int = 0
    fragment_count: int = 1

    def __post_init__(self) -> None:
        for name, bits in (
            ("transaction_id", 32),
            ("source_endpoint", 16),
            ("destination_endpoint", 16),
            ("status", 8),
            ("fragment_index", 8),
            ("fragment_count", 8),
        ):
            value = getattr(self, name)
            if not 0 <= value < 1 << bits:
                raise ValueError(f"{name} exceeds {bits} bits")
        if len(self.body) >= 1 << 16:
            raise ValueError("control body exceeds 16-bit length")
        if self.fragment_count == 0 or self.fragment_index >= self.fragment_count:
            raise ValueError("invalid control fragment index/count")
        if self.command != ControlCommand.CAPS_RESPONSE and (
            self.fragment_index != 0 or self.fragment_count != 1
        ):
            raise ValueError("only capability responses can be fragmented")
        if self.command == ControlCommand.STAGE:
            ContextRecord.unpack(self.body)
        elif self.command == ControlCommand.CAPS_RESPONSE:
            from .capabilities import decode_capabilities

            decode_capabilities(self.body)
        elif self.body:
            raise ValueError("only STAGE and CAPS_RESPONSE carry a body")


def encode_control_frame(
    packet: ControlPacket, *, destination_mac: bytes, source_mac: bytes, mtu: int
) -> bytes:
    if len(destination_mac) != 6 or len(source_mac) != 6:
        raise ValueError("Ethernet MAC must be six bytes")
    if not 576 <= mtu <= 9216 or 2 + CONTROL_HEADER_BYTES + len(packet.body) > mtu:
        raise ValueError("control packet exceeds negotiated MTU")
    header = _CONTROL.pack(
        packet.operation.job_id,
        packet.operation.group_id,
        packet.operation.group_generation,
        packet.operation.operation_id,
        packet.operation.operation_generation,
        packet.transaction_id,
        packet.source_endpoint,
        packet.destination_endpoint,
        int(packet.command),
        packet.status,
        len(packet.body),
        packet.fragment_index,
        packet.fragment_count,
    )
    frame = (
        _ETHERNET.pack(destination_mac, source_mac, ETHERTYPE)
        + bytes([(VERSION_MAJOR << 4) | VERSION_MINOR, int(PacketClass.CONTROL)])
        + header
        + packet.body
    )
    return frame + bytes(max(0, MIN_ETHERNET_FRAME_BYTES - len(frame)))


def decode_control_frame(frame: bytes, *, mtu: int) -> ControlPacket:
    if len(frame) < max(MIN_ETHERNET_FRAME_BYTES, 14 + 2 + CONTROL_HEADER_BYTES):
        raise ValueError("truncated CONTROL frame")
    _dst, _src, ethertype = _ETHERNET.unpack_from(frame)
    if ethertype != ETHERTYPE or frame[14:16] != bytes(
        [(VERSION_MAJOR << 4) | VERSION_MINOR, int(PacketClass.CONTROL)]
    ):
        raise ValueError("invalid CONTROL frame type or version")
    (
        job_id,
        group_id,
        group_generation,
        operation_id,
        operation_generation,
        transaction_id,
        source_endpoint,
        destination_endpoint,
        command,
        status,
        body_bytes,
        fragment_index,
        fragment_count,
    ) = _CONTROL.unpack_from(frame, 16)
    end = 14 + 2 + CONTROL_HEADER_BYTES + body_bytes
    if 2 + CONTROL_HEADER_BYTES + body_bytes > mtu or len(frame) < end:
        raise ValueError("invalid CONTROL length")
    if len(frame) > max(MIN_ETHERNET_FRAME_BYTES, end) or any(frame[end:]):
        raise ValueError("invalid Ethernet padding")
    return ControlPacket(
        OperationKey(job_id, group_id, group_generation, operation_id, operation_generation),
        transaction_id,
        source_endpoint,
        destination_endpoint,
        ControlCommand(command),
        status,
        frame[48:end],
        fragment_index,
        fragment_count,
    )
