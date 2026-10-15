"""Receiver-owned CONTROL admission and locally bound DATA/RESULT streams."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..domain.capabilities import CapabilityCatalog
from ..domain.model import AccumulatorPolicy, CollectiveKind, OperationKey, PartialWirePolicy
from ..domain.numbers import required_kulisch_bits
from ..domain.topology import PrismCapacity
from ..wire.capabilities import encode_capability_pages
from ..wire.control import (
    ContextRecord,
    ControlCommand,
    ControlPacket,
    ControlStatus,
    EndpointBindingRecord,
    NodeRole,
    PeerKind,
    decode_control_frame,
)
from ..wire.data import PacketClass, decode_data_frame
from .window import Admission, ReceiveWindow


@dataclass(slots=True)
class InstalledContext:
    record: ContextRecord
    transaction_id: int
    active: bool = False
    windows: dict[tuple[PacketClass, int], ReceiveWindow] | None = None

    def binding(self, endpoint: int) -> EndpointBindingRecord:
        return next(item for item in self.record.bindings if item.local_endpoint == endpoint)


class NodeReceiver:
    """A PRISM node knows only its own ports, advertised limits and installed records."""

    def __init__(
        self,
        *,
        mac: bytes,
        ports: dict[int, int],
        capacity: PrismCapacity,
        capabilities: CapabilityCatalog,
        manager_mac: bytes,
        manager_port: int,
        control_endpoint: int = 0xFFFE,
    ) -> None:
        self.mac = mac
        self.ports = dict(ports)
        self.capacity = capacity
        self.capabilities = capabilities
        self.manager_mac = manager_mac
        self.manager_port = manager_port
        self.control_endpoint = control_endpoint
        self.contexts: dict[OperationKey, InstalledContext] = {}
        self._journal: dict[
            tuple[OperationKey, ControlCommand, int], tuple[bytes, ControlStatus]
        ] = {}
        self._generations: dict[tuple[int, int, int], tuple[int, int]] = {}

    @property
    def reserved_intervals(self) -> int:
        return sum(item.record.window_intervals for item in self.contexts.values())

    @property
    def reserved_bytes(self) -> int:
        return sum(item.record.window_bytes for item in self.contexts.values())

    def _validate_record(self, record: ContextRecord) -> ControlStatus:
        if record.manager_mac != self.manager_mac or record.manager_port != self.manager_port:
            return ControlStatus.BINDING_INVALID
        if self.manager_port not in self.ports or self.ports[self.manager_port] < record.mtu:
            return ControlStatus.BINDING_INVALID
        if record.role in (NodeRole.SINGLE, NodeRole.ROOT) and record.parent_endpoint is not None:
            return ControlStatus.INVALID
        if record.role in (NodeRole.LEAF, NodeRole.INTERNAL) and record.parent_endpoint is None:
            return ControlStatus.INVALID
        if record.role != NodeRole.SINGLE and not self.capacity.multi_node_roles:
            return ControlStatus.UNSUPPORTED
        if (
            len(record.child_endpoints) > self.capacity.max_children
            or len(record.bindings) > self.capacity.max_endpoints
            or record.window_intervals > self.capacity.window_intervals
            or record.window_bytes > self.capacity.window_bytes
            or record.window_bytes < record.mtu + 14
            or record.original_terms > record.maximum_original_terms
            or record.element_count == 0
            or not 576 <= record.mtu <= 9216
        ):
            return ControlStatus.NO_RESOURCE
        if (
            record.accumulator == AccumulatorPolicy.KULISCH_FIXED
            and record.kulisch_bits < required_kulisch_bits(record.maximum_original_terms)
        ):
            return ControlStatus.UNSUPPORTED
        if record.accumulator == AccumulatorPolicy.KULISCH_FIXED and record.partial_wire not in (
            PartialWirePolicy.KULISCH,
            PartialWirePolicy.AUTO,
        ):
            return ControlStatus.UNSUPPORTED
        if not 8 <= record.kulisch_bits <= 4096:
            return ControlStatus.UNSUPPORTED
        if any(
            not any(
                cap.input_format == fmt
                and cap.accumulator == record.accumulator
                and cap.partial_wire == record.partial_wire
                and cap.output_format == record.output_format
                and record.maximum_original_terms <= cap.maximum_original_terms
                and record.element_count <= cap.maximum_vector_elements
                and record.kulisch_bits <= cap.maximum_kulisch_bits
                and record.mtu in cap.mtus
                and record.window_intervals <= cap.maximum_window_intervals
                and record.window_bytes <= cap.maximum_window_bytes
                for cap in self.capabilities.records
            )
            for fmt in record.rank_formats
        ):
            return ControlStatus.UNSUPPORTED
        child_bindings = record.bindings[int(record.parent_endpoint is not None) :]
        result_children = sum(item.result_enabled for item in child_bindings)
        if record.kind == CollectiveKind.ALLREDUCE and (
            result_children != len(child_bindings)
            or (record.parent_endpoint is not None and not record.bindings[0].result_enabled)
        ):
            return ControlStatus.BINDING_INVALID
        if record.kind == CollectiveKind.REDUCE and (
            result_children > 1 or (record.parent_endpoint is None and result_children != 1)
        ):
            return ControlStatus.BINDING_INVALID
        if record.parent_endpoint is not None and (
            record.bindings[0].peer_kind != PeerKind.PRISM or record.bindings[0].original_terms != 0
        ):
            return ControlStatus.BINDING_INVALID
        if record.role in (NodeRole.SINGLE, NodeRole.LEAF) and any(
            item.peer_kind != PeerKind.RANK for item in child_bindings
        ):
            return ControlStatus.BINDING_INVALID
        if sum(item.original_terms for item in child_bindings) != record.original_terms:
            return ControlStatus.BINDING_INVALID
        if len({item.local_endpoint for item in record.bindings}) != len(record.bindings):
            return ControlStatus.BINDING_INVALID
        if len({item.rank_id for item in child_bindings if item.rank_id is not None}) != sum(
            item.peer_kind == PeerKind.RANK for item in child_bindings
        ):
            return ControlStatus.BINDING_INVALID
        for binding in record.bindings:
            if binding.local_port not in self.ports or self.ports[binding.local_port] < record.mtu:
                return ControlStatus.BINDING_INVALID
            if binding.peer_mac == self.mac or binding.peer_mac == self.manager_mac:
                return ControlStatus.BINDING_INVALID
            if (
                binding.peer_kind == PeerKind.PRISM
                and binding.original_terms == 0
                and (binding.local_endpoint != record.parent_endpoint)
            ):
                return ControlStatus.BINDING_INVALID
            if binding.peer_kind == PeerKind.RANK and not binding.formats <= record.rank_formats:
                return ControlStatus.BINDING_INVALID
            if (
                binding.local_endpoint in record.child_endpoints
                and not binding.formats <= record.accepted_formats
            ):
                return ControlStatus.BINDING_INVALID
        if not self.capacity.shared_port_demux and len(
            {item.local_port for item in record.bindings}
        ) != len(record.bindings):
            return ControlStatus.BINDING_INVALID
        stream_count = len(record.child_endpoints) + int(
            record.parent_endpoint is not None and record.bindings[0].result_enabled
        )
        if (
            record.window_intervals // stream_count < 1
            or record.window_bytes // stream_count < record.mtu + 14
        ):
            return ControlStatus.NO_RESOURCE
        return ControlStatus.OK

    def _windows(
        self, operation: OperationKey, record: ContextRecord
    ) -> dict[tuple[PacketClass, int], ReceiveWindow]:
        windows: dict[tuple[PacketClass, int], ReceiveWindow] = {}
        count = len(record.child_endpoints) + int(
            record.parent_endpoint is not None and record.bindings[0].result_enabled
        )
        intervals = record.window_intervals // count
        bytes_per_stream = record.window_bytes // count
        for binding in record.bindings:
            packet_class = (
                PacketClass.RESULT
                if binding.local_endpoint == record.parent_endpoint
                else PacketClass.DATA
            )
            if packet_class == PacketClass.RESULT and not binding.result_enabled:
                continue
            window = ReceiveWindow(
                operation=operation,
                packet_class=packet_class,
                source_endpoint=binding.peer_endpoint,
                destination_endpoint=binding.local_endpoint,
                stream_id=binding.local_endpoint,
                element_count=record.element_count,
                allowed_formats=binding.formats,
                mtu=record.mtu,
                kulisch_bits=record.kulisch_bits,
                maximum_intervals=intervals,
                maximum_bytes=bytes_per_stream,
                element_span=max(1, bytes_per_stream // (record.mtu + 14)) * record.mtu,
            )
            window.activate()
            windows[(packet_class, binding.local_endpoint)] = window
        return windows

    def capability_pages(self, frame: bytes, *, ingress_port: int, mtu: int) -> tuple[bytes, ...]:
        packet = decode_control_frame(frame, mtu=mtu)
        if (
            packet.command != ControlCommand.CAPS_QUERY
            or frame[:6] != self.mac
            or frame[6:12] != self.manager_mac
            or ingress_port != self.manager_port
        ):
            raise ValueError("capability query binding is invalid")
        return encode_capability_pages(self.capabilities, self.capacity, mtu=mtu)

    def handle_control(self, frame: bytes, *, ingress_port: int, mtu: int) -> ControlPacket:
        packet = decode_control_frame(frame, mtu=mtu)
        if (
            frame[:6] != self.mac
            or frame[6:12] != self.manager_mac
            or ingress_port != self.manager_port
            or packet.destination_endpoint != self.control_endpoint
            or packet.source_endpoint != self.control_endpoint
            or packet.status != 0
        ):
            raise ValueError("CONTROL source, destination or ingress binding is invalid")
        journal_key = (packet.operation, packet.command, packet.transaction_id)
        previous = self._journal.get(journal_key)
        if previous is not None:
            status = previous[1] if previous[0] == frame else ControlStatus.TRANSACTION_CONFLICT
            return self._ack(packet, status)
        status = self._apply(packet)
        self._journal[journal_key] = (frame, status)
        if len(self._journal) > 64:
            del self._journal[next(iter(self._journal))]
        return self._ack(packet, status)

    def _apply(self, packet: ControlPacket) -> ControlStatus:
        operation = packet.operation
        current = self.contexts.get(operation)
        key = (operation.job_id, operation.group_id, operation.operation_id)
        generation = (operation.group_generation, operation.operation_generation)
        previous = self._generations.get(key)
        if previous is not None and generation < previous:
            return ControlStatus.STALE_GENERATION
        if packet.command == ControlCommand.STAGE:
            if current is not None:
                return ControlStatus.BAD_STATE
            # A retired generation must never reopen receive windows for old DATA.
            # Identical retries still use the ACK journal in handle_control.
            if previous is not None and generation == previous:
                return ControlStatus.STALE_GENERATION
            if any(
                old.job_id == operation.job_id
                and old.group_id == operation.group_id
                and old.operation_id == operation.operation_id
                for old in self.contexts
            ):
                return ControlStatus.BAD_STATE
            record = ContextRecord.unpack(packet.body)
            status = self._validate_record(record)
            if status != ControlStatus.OK:
                return status
            if (
                self.reserved_intervals + record.window_intervals > self.capacity.window_intervals
                or self.reserved_bytes + record.window_bytes > self.capacity.window_bytes
            ):
                return ControlStatus.NO_RESOURCE
            self.contexts[operation] = InstalledContext(record, packet.transaction_id)
            self._generations[key] = max(previous or generation, generation)
            return ControlStatus.OK
        if packet.command == ControlCommand.ABORT:
            if current is not None:
                del self.contexts[operation]
            return ControlStatus.OK
        if current is None:
            return ControlStatus.BAD_STATE
        if packet.command == ControlCommand.COMMIT:
            if current.active:
                return ControlStatus.BAD_STATE
            current.windows = self._windows(operation, current.record)
            current.active = True
            return ControlStatus.OK
        if packet.command == ControlCommand.RELEASE:
            if (
                not current.active
                or current.windows is None
                or not all(window.complete for window in current.windows.values())
            ):
                return ControlStatus.BAD_STATE
            del self.contexts[operation]
            return ControlStatus.OK
        return ControlStatus.INVALID

    @staticmethod
    def _ack(packet: ControlPacket, status: ControlStatus) -> ControlPacket:
        return ControlPacket(
            packet.operation,
            packet.transaction_id,
            packet.destination_endpoint,
            packet.source_endpoint,
            ControlCommand.ACK,
            int(status),
        )

    def accept_data(self, frame: bytes, *, ingress_port: int) -> tuple[Admission, ReceiveWindow]:
        if frame[:6] != self.mac:
            raise ValueError("DATA destination MAC differs from node")
        if len(frame) < 34:
            raise ValueError("truncated DATA identity")
        operation = OperationKey(*struct.unpack_from("!QHHHI", frame, 16))
        context = self.contexts.get(operation)
        if context is None or not context.active or context.windows is None:
            raise ValueError("operation configuration is not committed")
        packet = decode_data_frame(
            frame, mtu=context.record.mtu, kulisch_bits=context.record.kulisch_bits
        )
        binding = next(
            (
                item
                for item in context.record.bindings
                if item.local_endpoint == packet.destination_endpoint
            ),
            None,
        )
        if binding is None or (
            frame[6:12] != binding.peer_mac
            or ingress_port != binding.local_port
            or packet.source_endpoint != binding.peer_endpoint
        ):
            raise ValueError("DATA source or endpoint differs from installed binding")
        window = context.windows.get((packet.packet_class, binding.local_endpoint))
        if window is None:
            raise ValueError("DATA/RESULT stream is not committed for this binding")
        return window.accept(frame), window
