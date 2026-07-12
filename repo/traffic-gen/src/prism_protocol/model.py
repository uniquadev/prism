"""Pure host-side PRISM descriptors, lifecycle, admission, and reliability models."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .constants import (
    BYTES_PER_ELEMENT,
    PARTIAL_BYTES_PER_ELEMENT,
    CHUNK_PAYLOAD_BYTES,
    MAX_BITMAP_BYTES,
    MAX_CHUNKS,
    AccumulatorMode,
    AllocationKey,
    AggregationSlotState,
    CapabilityKey,
    CollectiveSemantic,
    FeatureFlag,
    GroupState,
    NextHopType,
    NodeRole,
    OperationState,
    PartialWireFormat,
    ReductionOperator,
    ResourceKey,
    SecurityProfile,
    SessionState,
    Status,
    TlvType,
    WireFormat,
)
from .errors import GenerationWrapRequiresNewJob, InvalidHandleError, PrismError
from .wire import GroupHandleWire, OperationHandleWire, OperationIdentity, Tlv, expected_chunks


_CAPABILITY_ENTRY = struct.Struct("!HHQI")
_GROUP_DESCRIPTOR = struct.Struct("!BBHHH")
_CONTRIBUTOR_BINDING = struct.Struct("!HH6sH")
_UPSTREAM_ACTION = struct.Struct("!BBHH6sI")
_NEXT_HOP = struct.Struct("!HHBB6s")
_REPLICATION_HEADER = struct.Struct("!HHI")
_RESULT_ROUTE = struct.Struct("!3s3sH")
_OPERATION_PREFIX = struct.Struct("!BBBBBBBB")
_OPERATION_GEOMETRY = struct.Struct("!IHHII")
_OPERATION_RESOURCES = struct.Struct("!HHBBH")
_OPERATION_CHUNKS = struct.Struct("!IHH")


def _u24(value: int) -> bytes:
    if not 0 <= value < (1 << 24):
        raise ValueError("value does not fit in 24 bits")
    return value.to_bytes(3, "big")


def _mac(value: bytes) -> bytes:
    if len(value) != 6:
        raise ValueError("MAC address must be exactly 6 bytes")
    return value


@dataclass(frozen=True, slots=True)
class ArithmeticTuple:
    input_format: WireFormat
    accumulator_mode: AccumulatorMode
    partial_format: PartialWireFormat
    output_format: WireFormat

    def encode(self) -> int:
        return (
            int(self.input_format) << 56
            | int(self.accumulator_mode) << 48
            | int(self.partial_format) << 40
            | int(self.output_format) << 32
        )

    @classmethod
    def decode(cls, value: int) -> "ArithmeticTuple":
        if value & 0xFFFFFFFF:
            raise ValueError("non-zero arithmetic tuple reserved bits")
        return cls(
            WireFormat((value >> 56) & 0xFF),
            AccumulatorMode((value >> 48) & 0xFF),
            PartialWireFormat((value >> 40) & 0xFF),
            WireFormat((value >> 32) & 0xFF),
        )


@dataclass(frozen=True, slots=True)
class ContributorBinding:
    contributor_id: int
    ingress_port: int
    source_mac: bytes
    flags: int = 0

    def pack(self) -> bytes:
        if not 0 <= self.contributor_id < (1 << 16) or not 0 <= self.ingress_port < (1 << 16):
            raise ValueError("contributor or ingress port exceeds 16 bits")
        if self.flags:
            raise ValueError("contributor binding reserved flags must be zero")
        return _CONTRIBUTOR_BINDING.pack(self.contributor_id, self.ingress_port, _mac(self.source_mac), 0)

    @classmethod
    def unpack(cls, value: bytes) -> "ContributorBinding":
        if len(value) != _CONTRIBUTOR_BINDING.size:
            raise ValueError("invalid contributor binding length")
        contributor, port, mac, flags = _CONTRIBUTOR_BINDING.unpack(value)
        if flags:
            raise ValueError("non-zero contributor binding reserved flags")
        return cls(contributor, port, mac)


@dataclass(frozen=True, slots=True)
class UpstreamAction:
    has_parent: bool
    parent_contributor_id: int
    egress_port: int
    parent_mac: bytes

    def pack(self) -> bytes:
        return _UPSTREAM_ACTION.pack(
            int(self.has_parent),
            0,
            self.parent_contributor_id,
            self.egress_port,
            _mac(self.parent_mac),
            0,
        )

    @classmethod
    def unpack(cls, value: bytes) -> "UpstreamAction":
        if len(value) != _UPSTREAM_ACTION.size:
            raise ValueError("invalid upstream action length")
        has_parent, reserved8, contributor, port, mac, reserved16 = _UPSTREAM_ACTION.unpack(value)
        if has_parent not in (0, 1) or reserved8 or reserved16:
            raise ValueError("invalid upstream action reserved fields")
        return cls(bool(has_parent), contributor, port, mac)


@dataclass(frozen=True, slots=True)
class NextHopEntry:
    result_path_id: int
    egress_port: int
    next_hop_type: NextHopType
    dst_mac: bytes
    flags: int = 0

    def pack(self) -> bytes:
        if self.flags:
            raise ValueError("next-hop reserved flags must be zero")
        return _NEXT_HOP.pack(
            self.result_path_id,
            self.egress_port,
            int(self.next_hop_type),
            0,
            _mac(self.dst_mac),
        )

    @classmethod
    def unpack(cls, value: bytes) -> "NextHopEntry":
        if len(value) != _NEXT_HOP.size:
            raise ValueError("invalid next-hop entry length")
        path, port, type_value, flags, mac = _NEXT_HOP.unpack(value)
        if flags:
            raise ValueError("non-zero next-hop reserved flags")
        return cls(path, port, NextHopType(type_value), mac)


@dataclass(frozen=True, slots=True)
class ReplicationGroup:
    group_id: int
    entries: tuple[NextHopEntry, ...]

    def pack(self) -> bytes:
        if not self.entries:
            raise ValueError("replication group must contain at least one entry")
        paths = [entry.result_path_id for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("result_path_id must be unique in a replication group")
        pairs = [(entry.egress_port, entry.dst_mac) for entry in self.entries]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate egress-port/destination-MAC pair")
        return _REPLICATION_HEADER.pack(self.group_id, len(self.entries), 0) + b"".join(entry.pack() for entry in self.entries)

    @classmethod
    def unpack(cls, value: bytes) -> "ReplicationGroup":
        if len(value) < _REPLICATION_HEADER.size:
            raise ValueError("truncated replication group")
        group_id, count, reserved = _REPLICATION_HEADER.unpack_from(value)
        if reserved or count == 0 or len(value) != _REPLICATION_HEADER.size + count * _NEXT_HOP.size:
            raise ValueError("invalid replication group length or reserved field")
        entries = tuple(
            NextHopEntry.unpack(value[offset : offset + _NEXT_HOP.size])
            for offset in range(_REPLICATION_HEADER.size, len(value), _NEXT_HOP.size)
        )
        return cls(group_id, entries)


@dataclass(frozen=True, slots=True)
class GroupDescriptor:
    node_role: NodeRole
    expected_local_contributors: int
    max_replication_groups: int
    max_replication_entries: int
    contributors: tuple[ContributorBinding, ...]
    upstream: UpstreamAction
    replication_groups: tuple[ReplicationGroup, ...] = ()

    def validate(self) -> None:
        if self.node_role == NodeRole.INVALID:
            raise ValueError("invalid node role")
        if self.expected_local_contributors <= 0:
            raise ValueError("expected_local_contributors must be positive")
        ids = [binding.contributor_id for binding in self.contributors]
        if ids != list(range(self.expected_local_contributors)):
            raise ValueError("Contributor IDs must be dense and ordered from zero")
        bindings = [(item.ingress_port, item.source_mac) for item in self.contributors]
        if len(bindings) != len(set(bindings)):
            raise ValueError("contributor ingress/MAC bindings must be unique")
        if len(self.replication_groups) > self.max_replication_groups:
            raise ValueError("replication-group descriptor exceeds declared limit")
        group_ids = [group.group_id for group in self.replication_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("duplicate replication-group ID")
        if any(len(group.entries) > self.max_replication_entries for group in self.replication_groups):
            raise ValueError("replication group exceeds declared entry limit")

    def descriptor_tlv(self) -> Tlv:
        self.validate()
        value = _GROUP_DESCRIPTOR.pack(
            int(self.node_role),
            0,
            self.expected_local_contributors,
            self.max_replication_groups,
            self.max_replication_entries,
        )
        return Tlv(TlvType.GROUP_DESCRIPTOR, value)

    def management_tlvs(self) -> tuple[Tlv, ...]:
        return (
            self.descriptor_tlv(),
            *(Tlv(TlvType.CONTRIBUTOR_BINDING, binding.pack()) for binding in self.contributors),
            Tlv(TlvType.UPSTREAM_ACTION, self.upstream.pack()),
            *(Tlv(TlvType.REPLICATION_GROUP, group.pack()) for group in self.replication_groups),
        )

    @classmethod
    def unpack_descriptor(
        cls,
        value: bytes,
        contributors: Iterable[ContributorBinding],
        upstream: UpstreamAction,
        replication_groups: Iterable[ReplicationGroup] = (),
    ) -> "GroupDescriptor":
        if len(value) != _GROUP_DESCRIPTOR.size:
            raise ValueError("group descriptor must be 8 bytes")
        role, flags, expected, max_groups, max_entries = _GROUP_DESCRIPTOR.unpack(value)
        if flags:
            raise ValueError("non-zero group descriptor reserved flags")
        result = cls(
            NodeRole(role),
            expected,
            max_groups,
            max_entries,
            tuple(contributors),
            upstream,
            tuple(replication_groups),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class ResultRoute:
    chunk_first: int
    chunk_last: int
    replication_group_id: int

    def pack(self) -> bytes:
        if not 0 <= self.chunk_first <= self.chunk_last < MAX_CHUNKS:
            raise ValueError("invalid result-route range")
        return _RESULT_ROUTE.pack(_u24(self.chunk_first), _u24(self.chunk_last), self.replication_group_id)

    @classmethod
    def unpack(cls, value: bytes) -> "ResultRoute":
        if len(value) != _RESULT_ROUTE.size:
            raise ValueError("result route must be 8 bytes")
        first, last, group = _RESULT_ROUTE.unpack(value)
        return cls(int.from_bytes(first, "big"), int.from_bytes(last, "big"), group)


@dataclass(frozen=True, slots=True)
class OperationDescriptor:
    semantic: CollectiveSemantic
    reduction_operator: ReductionOperator
    input_format: WireFormat
    accumulator_mode: AccumulatorMode
    partial_format: PartialWireFormat
    output_format: WireFormat
    element_count: int
    elements_per_chunk: int
    max_reduction_terms: int
    requested_window_chunks: int
    requested_replay_slots: int
    timeout_ms: int
    retry_limit: int
    result_delivery_role: bool
    result_routes: tuple[ResultRoute, ...] = ()

    @property
    def expected_chunks(self) -> int:
        return expected_chunks(self.element_count, self.elements_per_chunk)

    @property
    def arithmetic_tuple(self) -> ArithmeticTuple:
        return ArithmeticTuple(self.input_format, self.accumulator_mode, self.partial_format, self.output_format)

    def validate(self) -> None:
        if self.semantic == CollectiveSemantic.INVALID or self.reduction_operator == ReductionOperator.INVALID:
            raise ValueError("invalid collective semantic or operator")
        if self.input_format not in BYTES_PER_ELEMENT or self.output_format not in BYTES_PER_ELEMENT:
            raise ValueError("invalid input/output format")
        if self.partial_format not in PARTIAL_BYTES_PER_ELEMENT:
            raise ValueError("invalid partial wire format")
        if self.accumulator_mode == AccumulatorMode.INVALID:
            raise ValueError("invalid accumulator mode")
        if self.element_count <= 0 or not 0 < self.elements_per_chunk < (1 << 16):
            raise ValueError("invalid operation geometry")
        if self.max_reduction_terms <= 0 or self.max_reduction_terms >= (1 << 32):
            raise ValueError("invalid max_reduction_terms")
        if self.requested_window_chunks <= 0 or self.requested_window_chunks >= (1 << 16):
            raise ValueError("invalid requested window")
        if self.requested_replay_slots <= 0 or self.requested_replay_slots >= (1 << 16):
            raise ValueError("invalid replay-slot request")
        if self.timeout_ms <= 0 or self.timeout_ms >= (1 << 32):
            raise ValueError("invalid timeout")
        count = self.expected_chunks
        max_element_bytes = max(
            BYTES_PER_ELEMENT[self.input_format],
            PARTIAL_BYTES_PER_ELEMENT[self.partial_format],
            BYTES_PER_ELEMENT[self.output_format],
        )
        if self.elements_per_chunk * max_element_bytes > CHUNK_PAYLOAD_BYTES:
            raise ValueError("chunk geometry exceeds PM_CHUNK_PAYLOAD_BYTES")
        previous_last = -1
        for route in sorted(self.result_routes, key=lambda route: route.chunk_first):
            if route.chunk_last >= count or route.chunk_first <= previous_last:
                raise ValueError("result-route ranges overlap or exceed expected chunks")
            previous_last = route.chunk_last
        if self.result_delivery_role:
            expected_first = 0
            for route in sorted(self.result_routes, key=lambda route: route.chunk_first):
                if route.chunk_first != expected_first:
                    raise ValueError("result routes do not cover every expected chunk")
                expected_first = route.chunk_last + 1
            if expected_first != count:
                raise ValueError("result routes do not cover every expected chunk")

    def pack(self) -> bytes:
        self.validate()
        flags = int(self.result_delivery_role)
        return b"".join(
            (
                _OPERATION_PREFIX.pack(
                    int(self.semantic),
                    int(self.reduction_operator),
                    int(self.input_format),
                    int(self.accumulator_mode),
                    int(self.partial_format),
                    int(self.output_format),
                    flags,
                    0,
                ),
                _OPERATION_GEOMETRY.pack(
                    self.element_count,
                    self.elements_per_chunk,
                    self.requested_window_chunks,
                    self.max_reduction_terms,
                    self.timeout_ms,
                ),
                _OPERATION_RESOURCES.pack(
                    self.requested_replay_slots,
                    len(self.result_routes),
                    int(self.result_delivery_role),
                    0,
                    0,
                ),
                _OPERATION_CHUNKS.pack(self.expected_chunks, self.retry_limit, 0),
            )
        )

    @classmethod
    def unpack(cls, value: bytes, result_routes: Iterable[ResultRoute] = ()) -> "OperationDescriptor":
        if len(value) != 40:
            raise ValueError("operation descriptor must be 40 bytes")
        semantic, operator, input_format, accumulator, partial_format, output_format, flags, reserved0 = _OPERATION_PREFIX.unpack_from(value, 0)
        element_count, elements_per_chunk, window, max_terms, timeout_ms = _OPERATION_GEOMETRY.unpack_from(value, 8)
        replay_slots, route_count, result_role, reserved1, reserved2 = _OPERATION_RESOURCES.unpack_from(value, 24)
        encoded_chunks, retry_limit, reserved3 = _OPERATION_CHUNKS.unpack_from(value, 32)
        if reserved0 or reserved1 or reserved2 or reserved3 or flags & ~0x01 or result_role not in (0, 1):
            raise ValueError("non-zero operation descriptor reserved fields")
        routes = tuple(result_routes)
        if route_count != len(routes) or bool(flags & 0x01) != bool(result_role):
            raise ValueError("operation descriptor route/result-role mismatch")
        result = cls(
            CollectiveSemantic(semantic),
            ReductionOperator(operator),
            WireFormat(input_format),
            AccumulatorMode(accumulator),
            PartialWireFormat(partial_format),
            WireFormat(output_format),
            element_count,
            elements_per_chunk,
            max_terms,
            window,
            replay_slots,
            timeout_ms,
            retry_limit,
            bool(result_role),
            routes,
        )
        result.validate()
        if encoded_chunks != result.expected_chunks:
            raise ValueError("encoded expected_chunks does not match operation geometry")
        return result

    def management_tlvs(self) -> tuple[Tlv, ...]:
        return (
            Tlv(TlvType.OPERATION_DESCRIPTOR, self.pack()),
            *(Tlv(TlvType.RESULT_ROUTE, route.pack()) for route in self.result_routes),
        )


@dataclass(frozen=True, slots=True)
class PhaseBitmapAllocation:
    expected_chunks: int
    result_delivery_role: bool
    aggregation_bitmap_bytes: int
    result_bitmap_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.aggregation_bitmap_bytes + self.result_bitmap_bytes

    @classmethod
    def calculate(cls, expected: int, result_delivery_role: bool) -> "PhaseBitmapAllocation":
        if not 0 <= expected <= MAX_CHUNKS:
            raise ValueError("expected chunk count exceeds 24-bit namespace")
        aggregation = (expected + 7) // 8
        result = aggregation if result_delivery_role else 0
        return cls(expected, result_delivery_role, aggregation, result)


class PhaseBitmap:
    def __init__(self, expected: int, result_delivery_role: bool) -> None:
        self.allocation = PhaseBitmapAllocation.calculate(expected, result_delivery_role)
        self.aggregation = bytearray(self.allocation.aggregation_bitmap_bytes)
        self.result = bytearray(self.allocation.result_bitmap_bytes)
        self.aggregation_done_count = 0
        self.result_done_count = 0

    @staticmethod
    def _set(bitmap: bytearray, chunk: int) -> bool:
        index, mask = divmod(chunk, 8)
        bit = 1 << mask
        if bitmap[index] & bit:
            return False
        bitmap[index] |= bit
        return True

    @staticmethod
    def _get(bitmap: bytearray, chunk: int) -> bool:
        index, mask = divmod(chunk, 8)
        return bool(bitmap[index] & (1 << mask))

    def aggregation_done(self, chunk: int) -> bool:
        self._validate_chunk(chunk)
        return self._get(self.aggregation, chunk)

    def result_done(self, chunk: int) -> bool:
        self._validate_chunk(chunk)
        return bool(self.result) and self._get(self.result, chunk)

    def mark_aggregation_done(self, chunk: int) -> bool:
        self._validate_chunk(chunk)
        changed = self._set(self.aggregation, chunk)
        if changed:
            self.aggregation_done_count += 1
        return changed

    def mark_result_done(self, chunk: int) -> bool:
        self._validate_chunk(chunk)
        if not self.result:
            raise ValueError("node has no result-delivery role")
        changed = self._set(self.result, chunk)
        if changed:
            self.result_done_count += 1
        return changed

    @property
    def complete(self) -> bool:
        aggregation_complete = self.aggregation_done_count == self.allocation.expected_chunks
        result_complete = not self.result or self.result_done_count == self.allocation.expected_chunks
        return aggregation_complete and result_complete

    def _validate_chunk(self, chunk: int) -> None:
        if not 0 <= chunk < self.allocation.expected_chunks:
            raise ValueError("chunk outside operation")


@dataclass(frozen=True, slots=True)
class Capabilities:
    device_boot_id: int
    feature_flags: FeatureFlag
    max_sessions: int
    max_installed_groups: int
    max_prepared_operations: int
    max_active_operations_global: int
    max_active_operations_per_group: int
    max_chunks_per_operation: int
    max_bitmap_bytes_per_operation: int
    total_phase_bitmap_pool_bytes: int
    max_active_aggregation_slots_global: int
    max_active_aggregation_slots_per_operation: int
    total_replay_output_slots: int
    max_local_contributors: int
    max_group_replication_groups: int
    max_entries_per_replication_group: int
    max_operation_result_routes: int
    max_management_staging_bytes: int
    max_selective_ack_window: int
    collective_semantics: frozenset[CollectiveSemantic]
    reduction_operators: frozenset[ReductionOperator]
    arithmetic_tuples: frozenset[ArithmeticTuple]
    mtu_bytes: int = 1500
    max_prism_payload_bytes: int = CHUNK_PAYLOAD_BYTES
    security_profiles: frozenset[SecurityProfile] = frozenset({SecurityProfile.LAB_UNAUTHENTICATED})
    replay_cache_depth: int = 64
    replay_cache_retention_ms: int = 10_000

    @classmethod
    def reference(cls, **overrides) -> "Capabilities":
        values = dict(
            device_boot_id=1,
            feature_flags=FeatureFlag.RELIABLE_HOP_BY_HOP | FeatureFlag.SELECTIVE_ACK | FeatureFlag.RESULT_ACK | FeatureFlag.LEASED_SESSIONS,
            max_sessions=8,
            max_installed_groups=64,
            max_prepared_operations=32,
            max_active_operations_global=16,
            max_active_operations_per_group=4,
            max_chunks_per_operation=MAX_CHUNKS,
            max_bitmap_bytes_per_operation=2 * MAX_BITMAP_BYTES,
            total_phase_bitmap_pool_bytes=16 * 1024 * 1024,
            max_active_aggregation_slots_global=256,
            max_active_aggregation_slots_per_operation=64,
            total_replay_output_slots=512,
            max_local_contributors=64,
            max_group_replication_groups=64,
            max_entries_per_replication_group=32,
            max_operation_result_routes=128,
            max_management_staging_bytes=64 * 1024,
            max_selective_ack_window=1024,
            collective_semantics=frozenset({CollectiveSemantic.REDUCE, CollectiveSemantic.ALLREDUCE}),
            reduction_operators=frozenset({ReductionOperator.SUM}),
            arithmetic_tuples=frozenset({ArithmeticTuple(WireFormat.FP32, AccumulatorMode.DETERMINISTIC_FP32, PartialWireFormat.FP32, WireFormat.FP32)}),
        )
        values.update(overrides)
        return cls(**values)

    def validate_operation(self, descriptor: OperationDescriptor) -> None:
        descriptor.validate()
        if descriptor.semantic not in self.collective_semantics:
            raise PrismError(Status.UNSUPPORTED_FEATURE, "collective semantic is not advertised")
        if descriptor.reduction_operator not in self.reduction_operators:
            raise PrismError(Status.UNSUPPORTED_FEATURE, "reduction operator is not advertised")
        expected = descriptor.expected_chunks
        allocation = PhaseBitmapAllocation.calculate(expected, descriptor.result_delivery_role)
        if expected > self.max_chunks_per_operation:
            raise PrismError(Status.NO_BITMAP_MEMORY, "operation exceeds maximum chunk count")
        if allocation.total_bytes > self.max_bitmap_bytes_per_operation:
            raise PrismError(Status.NO_BITMAP_MEMORY, "operation phase bitmap exceeds per-operation capability")
        if descriptor.requested_window_chunks > self.max_active_aggregation_slots_per_operation:
            # A smaller grant is allowed, so this is not itself an admission failure.
            pass
        if len(descriptor.result_routes) > self.max_operation_result_routes:
            raise PrismError(Status.NO_ROUTE_RESOURCE, "too many result routes")
        if descriptor.arithmetic_tuple not in self.arithmetic_tuples:
            raise PrismError(Status.UNSUPPORTED_ARITHMETIC_TUPLE, "arithmetic tuple is not advertised")

    def validate_group(self, descriptor: GroupDescriptor) -> None:
        descriptor.validate()
        if descriptor.expected_local_contributors > self.max_local_contributors:
            raise PrismError(Status.INVALID_RECORD, "local contributor capacity exceeded")
        if descriptor.max_replication_groups > self.max_group_replication_groups:
            raise PrismError(Status.NO_REPLICATION_RESOURCE, "replication-group capacity exceeded")
        if descriptor.max_replication_entries > self.max_entries_per_replication_group:
            raise PrismError(Status.NO_REPLICATION_RESOURCE, "replication-entry capacity exceeded")

    def capability_entries(self) -> tuple[tuple[CapabilityKey, int], ...]:
        semantics_mask = sum(1 << int(value) for value in self.collective_semantics)
        operators_mask = sum(1 << int(value) for value in self.reduction_operators)
        security_mask = sum(1 << int(value) for value in self.security_profiles)
        base = [
            (CapabilityKey.MAX_SESSIONS, self.max_sessions),
            (CapabilityKey.MAX_INSTALLED_GROUPS, self.max_installed_groups),
            (CapabilityKey.MAX_PREPARED_OPERATIONS, self.max_prepared_operations),
            (CapabilityKey.MAX_ACTIVE_OPERATIONS_GLOBAL, self.max_active_operations_global),
            (CapabilityKey.MAX_ACTIVE_OPERATIONS_PER_GROUP, self.max_active_operations_per_group),
            (CapabilityKey.MAX_CHUNKS_PER_OPERATION, self.max_chunks_per_operation),
            (CapabilityKey.MAX_BITMAP_BYTES_PER_OPERATION, self.max_bitmap_bytes_per_operation),
            (CapabilityKey.TOTAL_PHASE_BITMAP_POOL_BYTES, self.total_phase_bitmap_pool_bytes),
            (CapabilityKey.MAX_ACTIVE_AGGREGATION_SLOTS_GLOBAL, self.max_active_aggregation_slots_global),
            (CapabilityKey.MAX_ACTIVE_AGGREGATION_SLOTS_PER_OPERATION, self.max_active_aggregation_slots_per_operation),
            (CapabilityKey.TOTAL_REPLAY_OUTPUT_SLOTS, self.total_replay_output_slots),
            (CapabilityKey.MAX_LOCAL_CONTRIBUTORS, self.max_local_contributors),
            (CapabilityKey.MAX_GROUP_REPLICATION_GROUPS, self.max_group_replication_groups),
            (CapabilityKey.MAX_ENTRIES_PER_REPLICATION_GROUP, self.max_entries_per_replication_group),
            (CapabilityKey.MAX_OPERATION_RESULT_ROUTES, self.max_operation_result_routes),
            (CapabilityKey.MAX_MANAGEMENT_STAGING_BYTES, self.max_management_staging_bytes),
            (CapabilityKey.MAX_SELECTIVE_ACK_WINDOW, self.max_selective_ack_window),
            (CapabilityKey.SUPPORTED_COLLECTIVE_SEMANTICS, semantics_mask),
            (CapabilityKey.SUPPORTED_REDUCTION_OPERATORS, operators_mask),
            (CapabilityKey.MTU_BYTES, self.mtu_bytes),
            (CapabilityKey.MAX_PRISM_PAYLOAD_BYTES, self.max_prism_payload_bytes),
            (CapabilityKey.SUPPORTED_SECURITY_PROFILES, security_mask),
            (CapabilityKey.SUPPORTED_RELIABILITY_FEATURES, int(self.feature_flags)),
            (CapabilityKey.REPLAY_CACHE_DEPTH, self.replay_cache_depth),
            (CapabilityKey.REPLAY_CACHE_RETENTION_MS, self.replay_cache_retention_ms),
        ]
        base.extend((CapabilityKey.SUPPORTED_ARITHMETIC_TUPLE, value.encode()) for value in sorted(self.arithmetic_tuples, key=lambda item: item.encode()))
        return tuple(base)

    def to_tlv(self) -> Tlv:
        value = b"".join(_CAPABILITY_ENTRY.pack(int(key), 0, item, 0) for key, item in self.capability_entries())
        return Tlv(TlvType.CAPABILITIES, value)

    @classmethod
    def from_tlv(cls, device_boot_id: int, tlv: Tlv) -> "Capabilities":
        if tlv.type != TlvType.CAPABILITIES or len(tlv.value) % _CAPABILITY_ENTRY.size:
            raise ValueError("invalid capabilities TLV")
        values: dict[CapabilityKey, int] = {}
        tuples: set[ArithmeticTuple] = set()
        for offset in range(0, len(tlv.value), _CAPABILITY_ENTRY.size):
            key_value, flags, value, reserved = _CAPABILITY_ENTRY.unpack_from(tlv.value, offset)
            if flags or reserved:
                raise ValueError("non-zero capability entry reserved field")
            key = CapabilityKey(key_value)
            if key == CapabilityKey.SUPPORTED_ARITHMETIC_TUPLE:
                tuples.add(ArithmeticTuple.decode(value))
            elif key in values:
                raise ValueError(f"duplicate capability key {key.name}")
            else:
                values[key] = value
        required = set(CapabilityKey) - {CapabilityKey.INVALID, CapabilityKey.SUPPORTED_ARITHMETIC_TUPLE}
        missing = required - values.keys()
        if missing:
            raise ValueError(f"missing capability entries: {', '.join(key.name for key in sorted(missing, key=int))}")
        semantics = frozenset(
            value for value in CollectiveSemantic if value != CollectiveSemantic.INVALID and values[CapabilityKey.SUPPORTED_COLLECTIVE_SEMANTICS] & (1 << int(value))
        )
        operators = frozenset(
            value for value in ReductionOperator if value != ReductionOperator.INVALID and values[CapabilityKey.SUPPORTED_REDUCTION_OPERATORS] & (1 << int(value))
        )
        security = frozenset(
            value for value in SecurityProfile if values[CapabilityKey.SUPPORTED_SECURITY_PROFILES] & (1 << int(value))
        )
        known_feature_mask = sum(int(value) for value in FeatureFlag)
        feature_mask = values[CapabilityKey.SUPPORTED_RELIABILITY_FEATURES]
        if feature_mask & ~known_feature_mask:
            raise ValueError("capabilities contain reserved feature bits")
        return cls(
            device_boot_id=device_boot_id,
            feature_flags=FeatureFlag(feature_mask),
            max_sessions=values[CapabilityKey.MAX_SESSIONS],
            max_installed_groups=values[CapabilityKey.MAX_INSTALLED_GROUPS],
            max_prepared_operations=values[CapabilityKey.MAX_PREPARED_OPERATIONS],
            max_active_operations_global=values[CapabilityKey.MAX_ACTIVE_OPERATIONS_GLOBAL],
            max_active_operations_per_group=values[CapabilityKey.MAX_ACTIVE_OPERATIONS_PER_GROUP],
            max_chunks_per_operation=values[CapabilityKey.MAX_CHUNKS_PER_OPERATION],
            max_bitmap_bytes_per_operation=values[CapabilityKey.MAX_BITMAP_BYTES_PER_OPERATION],
            total_phase_bitmap_pool_bytes=values[CapabilityKey.TOTAL_PHASE_BITMAP_POOL_BYTES],
            max_active_aggregation_slots_global=values[CapabilityKey.MAX_ACTIVE_AGGREGATION_SLOTS_GLOBAL],
            max_active_aggregation_slots_per_operation=values[CapabilityKey.MAX_ACTIVE_AGGREGATION_SLOTS_PER_OPERATION],
            total_replay_output_slots=values[CapabilityKey.TOTAL_REPLAY_OUTPUT_SLOTS],
            max_local_contributors=values[CapabilityKey.MAX_LOCAL_CONTRIBUTORS],
            max_group_replication_groups=values[CapabilityKey.MAX_GROUP_REPLICATION_GROUPS],
            max_entries_per_replication_group=values[CapabilityKey.MAX_ENTRIES_PER_REPLICATION_GROUP],
            max_operation_result_routes=values[CapabilityKey.MAX_OPERATION_RESULT_ROUTES],
            max_management_staging_bytes=values[CapabilityKey.MAX_MANAGEMENT_STAGING_BYTES],
            max_selective_ack_window=values[CapabilityKey.MAX_SELECTIVE_ACK_WINDOW],
            collective_semantics=semantics,
            reduction_operators=operators,
            arithmetic_tuples=frozenset(tuples),
            mtu_bytes=values[CapabilityKey.MTU_BYTES],
            max_prism_payload_bytes=values[CapabilityKey.MAX_PRISM_PAYLOAD_BYTES],
            security_profiles=security,
            replay_cache_depth=values[CapabilityKey.REPLAY_CACHE_DEPTH],
            replay_cache_retention_ms=values[CapabilityKey.REPLAY_CACHE_RETENTION_MS],
        )


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    snapshot_id: int
    free_group_slots: int
    free_prepared_operation_slots: int
    free_active_operation_slots: int
    free_phase_bitmap_bytes: int
    free_aggregation_slots: int
    free_replay_output_slots: int
    free_route_entries: int
    free_replication_groups: int
    free_replication_entries: int
    session_group_usage: int = 0
    session_prepared_operation_usage: int = 0
    session_active_operation_usage: int = 0
    session_bitmap_usage_bytes: int = 0
    session_aggregation_slot_usage: int = 0

    def entries(self) -> tuple[tuple[ResourceKey, int], ...]:
        return tuple(
            (ResourceKey[name.upper()], value)
            for name, value in asdict(self).items()
            if name != "snapshot_id"
        )

    def to_tlvs(self) -> tuple[Tlv, Tlv]:
        value = b"".join(_CAPABILITY_ENTRY.pack(int(key), 0, item, 0) for key, item in self.entries())
        return Tlv.u64(TlvType.RESOURCE_SNAPSHOT_ID, self.snapshot_id), Tlv(TlvType.RESOURCE_SNAPSHOT, value)

    @classmethod
    def from_tlvs(cls, snapshot_id_tlv: Tlv, snapshot_tlv: Tlv) -> "ResourceSnapshot":
        if snapshot_id_tlv.type != TlvType.RESOURCE_SNAPSHOT_ID or snapshot_tlv.type != TlvType.RESOURCE_SNAPSHOT:
            raise ValueError("wrong resource snapshot TLV types")
        if len(snapshot_tlv.value) % _CAPABILITY_ENTRY.size:
            raise ValueError("invalid resource snapshot entry length")
        entries: dict[ResourceKey, int] = {}
        for offset in range(0, len(snapshot_tlv.value), _CAPABILITY_ENTRY.size):
            key_value, flags, value, reserved = _CAPABILITY_ENTRY.unpack_from(snapshot_tlv.value, offset)
            if flags or reserved:
                raise ValueError("non-zero resource entry reserved field")
            key = ResourceKey(key_value)
            if key in entries:
                raise ValueError(f"duplicate resource key {key.name}")
            entries[key] = value
        required = set(ResourceKey) - {ResourceKey.INVALID}
        missing = required - entries.keys()
        if missing:
            raise ValueError(f"missing resource entries: {', '.join(key.name for key in sorted(missing, key=int))}")
        values = {key.name.lower(): entries[key] for key in required}
        return cls(snapshot_id=snapshot_id_tlv.as_u64(), **values)


@dataclass(frozen=True, slots=True)
class ResourceAllocation:
    group_slots: int = 0
    operation_slots: int = 0
    phase_bitmap_bytes: int = 0
    aggregation_slots: int = 0
    replay_output_slots: int = 0
    route_entries: int = 0
    replication_groups: int = 0
    replication_entries: int = 0

    def entries(self) -> tuple[tuple[AllocationKey, int], ...]:
        return tuple(
            (AllocationKey[name.upper()], value)
            for name, value in asdict(self).items()
            if value
        )

    def to_tlv(self, type_: TlvType) -> Tlv:
        if type_ not in (TlvType.RESOURCE_RESERVATION, TlvType.GRANTED_RESOURCES, TlvType.RELEASED_RESOURCES):
            raise ValueError("invalid resource-allocation TLV type")
        value = b"".join(_CAPABILITY_ENTRY.pack(int(key), 0, item, 0) for key, item in self.entries())
        return Tlv(type_, value)

    @classmethod
    def from_tlv(cls, tlv: Tlv) -> "ResourceAllocation":
        if tlv.type not in (TlvType.RESOURCE_RESERVATION, TlvType.GRANTED_RESOURCES, TlvType.RELEASED_RESOURCES):
            raise ValueError("invalid resource-allocation TLV type")
        if len(tlv.value) % _CAPABILITY_ENTRY.size:
            raise ValueError("invalid resource-allocation entry length")
        values: dict[str, int] = {}
        for offset in range(0, len(tlv.value), _CAPABILITY_ENTRY.size):
            key_value, flags, value, reserved = _CAPABILITY_ENTRY.unpack_from(tlv.value, offset)
            if flags or reserved:
                raise ValueError("non-zero resource-allocation reserved field")
            key = AllocationKey(key_value)
            name = key.name.lower()
            if key == AllocationKey.INVALID or name in values:
                raise ValueError("invalid or duplicate resource-allocation key")
            values[name] = value
        return cls(**values)


@dataclass(frozen=True, slots=True)
class OperationReservation:
    key: tuple[int, int, int, int]
    bitmap_bytes: int
    aggregation_slots: int
    replay_slots: int
    route_entries: int
    state: OperationState = OperationState.PREPARED


@dataclass(frozen=True, slots=True)
class GroupReservation:
    key: tuple[int, int]
    replication_groups: int
    replication_entries: int


class ResourcePool:
    """Reference admission model; snapshots are advisory, prepare calls reserve."""

    def __init__(self, capabilities: Capabilities) -> None:
        self.capabilities = capabilities
        self.group_reservations: dict[tuple[int, int], GroupReservation] = {}
        self.operation_reservations: dict[tuple[int, int, int, int], OperationReservation] = {}
        self._snapshot_id = 0

    def snapshot(self) -> ResourceSnapshot:
        self._snapshot_id += 1
        prepared = sum(item.state in (OperationState.PREPARED, OperationState.ABORTED) for item in self.operation_reservations.values())
        active = sum(item.state in (OperationState.ACTIVE, OperationState.COMPLETE) for item in self.operation_reservations.values())
        bitmap = sum(item.bitmap_bytes for item in self.operation_reservations.values())
        slots = sum(item.aggregation_slots for item in self.operation_reservations.values())
        replay = sum(item.replay_slots for item in self.operation_reservations.values())
        routes = sum(item.route_entries for item in self.operation_reservations.values())
        replication_groups = sum(item.replication_groups for item in self.group_reservations.values())
        replication_entries = sum(item.replication_entries for item in self.group_reservations.values())
        total_replication_groups = self.capabilities.max_group_replication_groups * self.capabilities.max_installed_groups
        total_replication_entries = total_replication_groups * self.capabilities.max_entries_per_replication_group
        return ResourceSnapshot(
            snapshot_id=self._snapshot_id,
            free_group_slots=self.capabilities.max_installed_groups - len(self.group_reservations),
            free_prepared_operation_slots=self.capabilities.max_prepared_operations - prepared,
            free_active_operation_slots=self.capabilities.max_active_operations_global - active,
            free_phase_bitmap_bytes=self.capabilities.total_phase_bitmap_pool_bytes - bitmap,
            free_aggregation_slots=self.capabilities.max_active_aggregation_slots_global - slots,
            free_replay_output_slots=self.capabilities.total_replay_output_slots - replay,
            free_route_entries=self.capabilities.max_operation_result_routes * self.capabilities.max_prepared_operations - routes,
            free_replication_groups=total_replication_groups - replication_groups,
            free_replication_entries=total_replication_entries - replication_entries,
        )

    def stage_group(self, key: tuple[int, int], descriptor: GroupDescriptor | None = None) -> GroupReservation:
        if key in self.group_reservations:
            return self.group_reservations[key]
        if len(self.group_reservations) >= self.capabilities.max_installed_groups:
            raise PrismError(Status.NO_GROUP_SLOT, "no group slot available")
        if descriptor is not None:
            self.capabilities.validate_group(descriptor)
        groups = len(descriptor.replication_groups) if descriptor is not None else 0
        entries = sum(len(group.entries) for group in descriptor.replication_groups) if descriptor is not None else 0
        snapshot = self.snapshot()
        if groups > snapshot.free_replication_groups or entries > snapshot.free_replication_entries:
            raise PrismError(Status.NO_REPLICATION_RESOURCE, "insufficient replication resources")
        reservation = GroupReservation(key, groups, entries)
        self.group_reservations[key] = reservation
        return reservation

    def destroy_group(self, key: tuple[int, int]) -> None:
        if any(operation[:2] == key for operation in self.operation_reservations):
            raise PrismError(Status.GROUP_BUSY, "group still owns operations")
        self.group_reservations.pop(key, None)

    def prepare_operation(self, key: tuple[int, int, int, int], descriptor: OperationDescriptor) -> OperationReservation:
        existing = self.operation_reservations.get(key)
        if existing is not None:
            return existing
        self.capabilities.validate_operation(descriptor)
        snapshot = self.snapshot()
        allocation = PhaseBitmapAllocation.calculate(descriptor.expected_chunks, descriptor.result_delivery_role)
        if snapshot.free_prepared_operation_slots <= 0:
            raise PrismError(Status.NO_OPERATION_SLOT, "no prepared-operation slot")
        if allocation.total_bytes > snapshot.free_phase_bitmap_bytes:
            raise PrismError(Status.NO_BITMAP_MEMORY, "insufficient phase-bitmap pool")
        granted_slots = min(
            descriptor.requested_window_chunks,
            self.capabilities.max_active_aggregation_slots_per_operation,
            snapshot.free_aggregation_slots,
        )
        if granted_slots <= 0:
            raise PrismError(Status.NO_AGGREGATION_SLOT, "no aggregation slot available")
        if descriptor.requested_replay_slots > snapshot.free_replay_output_slots:
            raise PrismError(Status.NO_REPLAY_BUFFER, "insufficient replay/output buffers")
        if len(descriptor.result_routes) > snapshot.free_route_entries:
            raise PrismError(Status.NO_ROUTE_RESOURCE, "insufficient result-route entries")
        reservation = OperationReservation(
            key,
            allocation.total_bytes,
            granted_slots,
            descriptor.requested_replay_slots,
            len(descriptor.result_routes),
        )
        self.operation_reservations[key] = reservation
        return reservation

    def commit_operation(self, key: tuple[int, int, int, int]) -> OperationReservation:
        reservation = self.operation_reservations.get(key)
        if reservation is None:
            raise PrismError(Status.NOT_FOUND, "operation was not prepared")
        if reservation.state == OperationState.ACTIVE:
            return reservation
        active = sum(item.state in (OperationState.ACTIVE, OperationState.COMPLETE) for item in self.operation_reservations.values())
        if active >= self.capabilities.max_active_operations_global:
            raise PrismError(Status.NO_OPERATION_SLOT, "no active-operation slot")
        updated = OperationReservation(**{**asdict(reservation), "state": OperationState.ACTIVE})
        self.operation_reservations[key] = updated
        return updated

    def abort_operation(self, key: tuple[int, int, int, int]) -> OperationReservation:
        reservation = self.operation_reservations.get(key)
        if reservation is None:
            raise PrismError(Status.NOT_FOUND, "operation was not prepared")
        if reservation.state == OperationState.ABORTED:
            return reservation
        updated = OperationReservation(**{**asdict(reservation), "state": OperationState.ABORTED})
        self.operation_reservations[key] = updated
        return updated

    def release_operation(self, key: tuple[int, int, int, int]) -> OperationReservation | None:
        return self.operation_reservations.pop(key, None)


@dataclass(slots=True)
class AggregationSlot:
    identity: OperationIdentity
    chunk_index: int
    contributors: set[int] = field(default_factory=set)
    state: AggregationSlotState = AggregationSlotState.ACTIVE


class ReliableOperationModel:
    """Reference receive/ACK model, intentionally not a collective arithmetic engine."""

    def __init__(
        self,
        identity: OperationIdentity,
        expected_chunks: int,
        contributors: int,
        admitted_window_chunks: int,
        slot_count: int,
        result_paths: Iterable[int] = (),
    ) -> None:
        result_path_values = tuple(result_paths)
        identity.validate()
        self.identity = identity
        self.expected_chunks = expected_chunks
        self.contributors = contributors
        self.window_base = 0
        self.admitted_window_chunks = admitted_window_chunks
        self.slot_count = slot_count
        self.phase = PhaseBitmap(expected_chunks, bool(result_path_values))
        self.slots: dict[int, AggregationSlot] = {}
        self.result_paths = frozenset(result_path_values)
        self.result_acks: dict[int, set[int]] = {}
        self.outstanding_retries = 0

    def receive_data(self, identity: OperationIdentity, contributor: int, chunk: int) -> Status:
        if identity != self.identity:
            return Status.GENERATION_MISMATCH
        if not 0 <= chunk < self.expected_chunks or not 0 <= contributor < self.contributors:
            return Status.INVALID_REQUEST
        if self.phase.aggregation_done(chunk):
            return Status.ALREADY_EXISTS
        if not self.window_base <= chunk < self.window_base + self.admitted_window_chunks:
            return Status.OUT_OF_WINDOW
        slot = self.slots.get(chunk)
        if slot is None:
            if len(self.slots) >= self.slot_count:
                return Status.RETRY
            slot = AggregationSlot(identity, chunk)
            self.slots[chunk] = slot
        if contributor in slot.contributors:
            return Status.ALREADY_EXISTS
        slot.contributors.add(contributor)
        if len(slot.contributors) == self.contributors:
            slot.state = AggregationSlotState.OUTPUT_PENDING
        return Status.OK

    def acknowledge_upstream(self, chunk: int) -> None:
        slot = self.slots.get(chunk)
        if slot is None or slot.state != AggregationSlotState.OUTPUT_PENDING:
            raise PrismError(Status.INVALID_STATE, "chunk is not output-pending")
        self.phase.mark_aggregation_done(chunk)
        del self.slots[chunk]
        self._advance_window()

    def begin_result(self, chunk: int) -> None:
        if not self.result_paths:
            raise PrismError(Status.INVALID_STATE, "node has no result-delivery role")
        self.result_acks.setdefault(chunk, set())

    def acknowledge_result_path(self, chunk: int, result_path_id: int) -> bool:
        if result_path_id not in self.result_paths:
            raise PrismError(Status.NOT_FOUND, "unknown result path")
        if self.phase.result_done(chunk):
            return False
        acknowledgments = self.result_acks.setdefault(chunk, set())
        acknowledgments.add(result_path_id)
        if acknowledgments == self.result_paths:
            self.phase.mark_result_done(chunk)
            return True
        return False

    @property
    def complete(self) -> bool:
        return self.phase.complete and self.outstanding_retries == 0

    def _advance_window(self) -> None:
        while self.window_base < self.expected_chunks and self.phase.aggregation_done(self.window_base):
            self.window_base += 1


@dataclass(frozen=True, slots=True)
class PendingTransfer:
    peer_id: int
    chunk_index: int
    payload_digest: bytes
    last_sent: float
    retries: int = 0


class ReliableSender:
    def __init__(self, timeout_seconds: float, retry_limit: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_limit = retry_limit
        self.pending: dict[tuple[int, int], PendingTransfer] = {}

    def retain(self, peer_id: int, chunk: int, payload: bytes, now: float = 0.0) -> None:
        key = (peer_id, chunk)
        digest = hashlib.sha256(payload).digest()
        previous = self.pending.get(key)
        if previous and previous.payload_digest != digest:
            raise PrismError(Status.TXN_CONFLICT, "same peer/chunk retained with different payload")
        self.pending[key] = PendingTransfer(peer_id, chunk, digest, now, previous.retries if previous else 0)

    def acknowledge(self, peer_id: int, chunk: int) -> bool:
        return self.pending.pop((peer_id, chunk), None) is not None

    def due(self, now: float) -> tuple[PendingTransfer, ...]:
        due: list[PendingTransfer] = []
        for key, transfer in tuple(self.pending.items()):
            if now - transfer.last_sent < self.timeout_seconds:
                continue
            if transfer.retries >= self.retry_limit:
                raise PrismError(Status.TIMEOUT, f"retry limit exceeded for peer/chunk {key}")
            updated = PendingTransfer(
                transfer.peer_id,
                transfer.chunk_index,
                transfer.payload_digest,
                now,
                transfer.retries + 1,
            )
            self.pending[key] = updated
            due.append(updated)
        return tuple(due)


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    command: int
    digest: bytes
    response: bytes
    created_at: float


class ReplayCache:
    def __init__(self, depth: int, retention_seconds: float) -> None:
        self.depth = depth
        self.retention_seconds = retention_seconds
        self._entries: OrderedDict[tuple[int, int], ReplayOutcome] = OrderedDict()

    def execute(
        self,
        session_cookie: int,
        transaction_id: int,
        command: int,
        payload: bytes,
        action: Callable[[], bytes],
        now: float = 0.0,
    ) -> bytes:
        self.expire(now)
        key = (session_cookie, transaction_id)
        digest = hashlib.sha256(payload).digest()
        previous = self._entries.get(key)
        if previous is not None:
            if previous.command != command or previous.digest != digest:
                raise PrismError(Status.TXN_CONFLICT, "Transaction ID reused with different command or payload")
            return previous.response
        response = action()
        self._entries[key] = ReplayOutcome(command, digest, response, now)
        while len(self._entries) > self.depth:
            self._entries.popitem(last=False)
        return response

    def expire(self, now: float) -> None:
        for key, value in tuple(self._entries.items()):
            if now - value.created_at >= self.retention_seconds:
                del self._entries[key]


class GenerationStore:
    """Small durable generation allocator used by the AM-side manager."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._state: dict[str, dict[str, int | bool]] = {}
        if path is not None and path.exists():
            self._state = json.loads(path.read_text(encoding="utf-8"))

    def allocate(self, namespace: str, identifier: int, bits: int) -> int:
        key = f"{namespace}:{identifier}"
        entry = self._state.get(key)
        if entry and entry.get("in_use"):
            raise InvalidHandleError(f"{namespace} ID {identifier} is still in use")
        generation = 1 if entry is None else int(entry["generation"]) + 1
        if generation >= 1 << bits:
            raise GenerationWrapRequiresNewJob()
        self._state[key] = {"generation": generation, "in_use": True}
        self._persist()
        return generation

    def release(self, namespace: str, identifier: int) -> None:
        key = f"{namespace}:{identifier}"
        entry = self._state.get(key)
        if entry is None or not entry.get("in_use"):
            raise InvalidHandleError(f"{namespace} ID {identifier} is not in use")
        entry["in_use"] = False
        self._persist()

    def invalidate_namespace(self, namespace_prefix: str) -> None:
        for key, entry in self._state.items():
            if key.startswith(namespace_prefix):
                entry["in_use"] = False
        self._persist()

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._state, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)


def group_handle_tlv(handle: GroupHandleWire) -> Tlv:
    return Tlv(TlvType.GROUP_HANDLE, handle.pack())


def operation_handle_tlv(handle: OperationHandleWire) -> Tlv:
    return Tlv(TlvType.OPERATION_HANDLE, handle.pack())


assert _CAPABILITY_ENTRY.size == 16
assert _GROUP_DESCRIPTOR.size == 8
assert _CONTRIBUTOR_BINDING.size == 12
assert _UPSTREAM_ACTION.size == 16
assert _NEXT_HOP.size == 12
assert _REPLICATION_HEADER.size == 8
assert _RESULT_ROUTE.size == 8
assert _OPERATION_PREFIX.size + _OPERATION_GEOMETRY.size + _OPERATION_RESOURCES.size + _OPERATION_CHUNKS.size == 40
