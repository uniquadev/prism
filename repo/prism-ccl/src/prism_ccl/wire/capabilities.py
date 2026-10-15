"""Capability response records: exact arithmetic tuples and bounded resources."""

from __future__ import annotations

import struct

from ..domain.capabilities import CapabilityCatalog, CapabilityRecord
from ..domain.model import AccumulatorPolicy, ConcreteFormat, PartialWirePolicy, ResultWirePolicy
from ..domain.topology import PrismCapacity

_HEADER = struct.Struct("!HH")
_RECORD = struct.Struct("!BBBBIIHHHHIHHI")
assert _RECORD.size == 32
_MTU_BIT = {576: 1 << 0, 1500: 1 << 1, 9000: 1 << 2}


def encode_capabilities(catalog: CapabilityCatalog, capacity: PrismCapacity) -> bytes:
    if len(catalog.records) > 65535:
        raise ValueError("too many capability records")
    entries: list[bytes] = []
    for record in catalog.records:
        try:
            mtu_mask = sum(_MTU_BIT[mtu] for mtu in record.mtus)
        except KeyError as error:
            raise ValueError("MTU has no assigned capability bit") from error
        flags = int(capacity.shared_port_demux) | (int(capacity.multi_node_roles) << 1)
        entries.append(
            _RECORD.pack(
                int(record.input_format),
                int(record.accumulator),
                int(record.partial_wire),
                int(record.output_format),
                record.maximum_original_terms,
                record.maximum_vector_elements,
                record.maximum_kulisch_bits,
                mtu_mask,
                min(record.maximum_window_intervals, capacity.window_intervals),
                min(
                    record.maximum_replay_frames_per_binding,
                    record.maximum_window_intervals,
                    capacity.window_intervals,
                ),
                min(record.maximum_window_bytes, capacity.window_bytes),
                capacity.max_children,
                capacity.max_endpoints,
                flags,
            )
        )
    return _HEADER.pack(len(entries), 0) + b"".join(entries)


def encode_capability_pages(
    catalog: CapabilityCatalog, capacity: PrismCapacity, *, mtu: int
) -> tuple[bytes, ...]:
    maximum_records = (mtu - 2 - 32 - _HEADER.size) // _RECORD.size
    if maximum_records <= 0:
        raise ValueError("MTU cannot carry one capability record")
    pages = tuple(
        encode_capabilities(
            CapabilityCatalog(catalog.records[index : index + maximum_records]), capacity
        )
        for index in range(0, len(catalog.records), maximum_records)
    )
    if len(pages) > 255:
        raise ValueError("capability response exceeds fragment namespace")
    return pages


def decode_capabilities(data: bytes) -> tuple[CapabilityCatalog, PrismCapacity]:
    if len(data) < _HEADER.size:
        raise ValueError("truncated capability response")
    count, reserved = _HEADER.unpack_from(data)
    if reserved or count == 0 or len(data) != _HEADER.size + count * _RECORD.size:
        raise ValueError("invalid capability response count or length")
    records: list[CapabilityRecord] = []
    capacity: PrismCapacity | None = None
    for index in range(count):
        (
            input_format,
            accumulator,
            partial_wire,
            output_format,
            max_terms,
            max_elements,
            max_bits,
            mtu_mask,
            max_intervals,
            max_replay_frames,
            max_bytes,
            max_children,
            max_endpoints,
            flags,
        ) = _RECORD.unpack_from(data, _HEADER.size + index * _RECORD.size)
        if (
            not 0 < max_replay_frames <= max_intervals
            or flags & ~0x03
            or mtu_mask & ~0x07
            or not mtu_mask
        ):
            raise ValueError("invalid capability replay depth, flags or MTU mask")
        record_capacity = PrismCapacity(
            max_children,
            max_endpoints,
            max_intervals,
            max_bytes,
            bool(flags & 1),
            bool(flags & 2),
        )
        if capacity is None:
            capacity = record_capacity
        elif capacity != record_capacity:
            raise ValueError("capability records disagree on node resources")
        records.append(
            CapabilityRecord(
                ConcreteFormat(input_format),
                AccumulatorPolicy(accumulator),
                PartialWirePolicy(partial_wire),
                ResultWirePolicy(output_format),
                max_terms,
                max_elements,
                max_bits,
                tuple(mtu for mtu, bit in _MTU_BIT.items() if mtu_mask & bit),
                max_intervals,
                max_bytes,
                max_replay_frames,
            )
        )
    assert capacity is not None
    return CapabilityCatalog(tuple(records)), capacity
