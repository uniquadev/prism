"""Deterministic frame-level backend with explicit AM and hop reliability."""

from __future__ import annotations

import random
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from itertools import chain, islice

from ..domain.capabilities import CapabilityCatalog, CapabilityRecord
from ..domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationConfig,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from ..domain.numbers import ExactValue, combine_exact, decode_native, round_native
from ..domain.topology import CollectiveTree, CompiledContext, PhysicalNetwork
from ..wire.capabilities import decode_capabilities
from ..wire.control import (
    ContextRecord,
    ControlCommand,
    ControlPacket,
    ControlStatus,
    EndpointBindingRecord,
    NodeRole,
    PeerKind,
    decode_control_frame,
    encode_control_frame,
)
from ..wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame
from ..wire.progress import (
    ProgressPacket,
    ProgressStatus,
    decode_progress_frame,
    encode_progress_frame,
)
from .node import NodeReceiver
from .packing import fixed_groups, packetize, select_auto_groups
from .reordering import ReorderPlan
from .window import Admission, ReceiveWindow


class SimulatedTimeout(TimeoutError):
    """A simulated frame did not complete within the retry budget."""


@dataclass(frozen=True, slots=True)
class FaultPlan:
    drop_once: frozenset[tuple[str, str, PacketClass, int]] = frozenset()
    drop_always: frozenset[tuple[str, str, PacketClass, int]] = frozenset()
    seed: int = 0
    retry_ticks: int = 8
    maximum_retries: int = 3


@dataclass(frozen=True, slots=True)
class FrameEvent:
    tick: int
    source: str
    destination: str
    packet_class: PacketClass
    packet_id: int
    path: tuple[str, ...]
    frame: bytes
    delivered: bool


@dataclass(frozen=True, slots=True)
class SoftwareResult:
    rank_bits: Mapping[int, tuple[int, ...]] | None
    rank_values: Mapping[int, tuple[ExactValue, ...]]
    rank_groups: Mapping[int, tuple[NumberGroup, ...]]
    partials: Mapping[str, tuple[ExactValue, ...]]
    frames: tuple[FrameEvent, ...]
    simulated_ticks: int
    released_contexts: bool


@dataclass(frozen=True, slots=True)
class Scenario:
    config: OperationConfig
    tree: CollectiveTree
    vectors: Mapping[int, TypedVector]
    manager: str
    management_paths: Mapping[str, tuple[str, ...]]


class FrameNetwork:
    def __init__(self, physical: PhysicalNetwork, fault: FaultPlan, reorder: ReorderPlan) -> None:
        self.physical = physical
        self.fault = fault
        self.reorder = reorder
        self.tick = 0
        self.events: list[FrameEvent] = []
        self._dropped_once: set[tuple[str, str, PacketClass, int]] = set()
        self.rng = random.Random(fault.seed)
        self.routes: dict[tuple[bytes, int, bytes], tuple[str, ...]] = {}

    def bind_path(self, path: tuple[str, ...], mtu: int) -> None:
        first_port, last_port = self.physical.validate_path(path, mtu)
        for route, port in ((path, first_port), (path[::-1], last_port)):
            key = (self.physical.nodes[route[0]].mac, port, self.physical.nodes[route[-1]].mac)
            if key in self.routes and self.routes[key] != route:
                raise ValueError("ambiguous physical binding")
            self.routes[key] = route

    def bound_route(
        self, source_mac: bytes, local_port: int, peer_mac: bytes, mtu: int
    ) -> tuple[tuple[str, ...], int]:
        path = self.routes.get((source_mac, local_port, peer_mac))
        if path is None:
            raise ValueError("installed endpoint has no physical route")
        _first, ingress = self.physical.validate_path(path, mtu)
        return path, ingress

    def route_by_macs(self, source_mac: bytes, peer_mac: bytes, mtu: int) -> tuple[str, ...]:
        paths = {
            path
            for (source, _port, peer), path in self.routes.items()
            if source == source_mac and peer == peer_mac
        }
        if len(paths) != 1:
            raise ValueError("physical transport needs one route for the peer MACs")
        path = next(iter(paths))
        self.physical.validate_path(path, mtu)
        return path

    def transmit(
        self, frame: bytes, path: tuple[str, ...], packet_class: PacketClass, packet_id: int
    ) -> bool:
        self.physical.validate_path(path, max(576, len(frame) - 14))
        if frame[0:6] != self.physical.nodes[path[-1]].mac:
            raise ValueError("Ethernet destination MAC differs from bound path")
        if frame[6:12] != self.physical.nodes[path[0]].mac:
            raise ValueError("Ethernet source MAC differs from bound path")
        key = (path[0], path[-1], packet_class, packet_id)
        dropped = key in self.fault.drop_always or (
            key in self.fault.drop_once and key not in self._dropped_once
        )
        if dropped:
            self._dropped_once.add(key)
        self.tick += len(path) - 1
        self.events.append(
            FrameEvent(
                self.tick, path[0], path[-1], packet_class, packet_id, path, frame, not dropped
            )
        )
        return not dropped


class SoftwareBackend:
    def __init__(self, network: PhysicalNetwork, capabilities: CapabilityCatalog) -> None:
        self.network = network
        self.capabilities = capabilities

    def run(
        self,
        scenario: Scenario,
        fault: FaultPlan | None = None,
        reorder: ReorderPlan | None = None,
    ) -> SoftwareResult:
        fault = fault or FaultPlan()
        reorder = reorder or ReorderPlan()
        if fault.retry_ticks <= 0 or fault.maximum_retries < 0:
            raise ValueError("simulated retry policy must be bounded and positive")
        config, tree = scenario.config, scenario.tree
        if set(scenario.vectors) != set(config.ranks):
            raise ValueError("every rank needs exactly one typed vector")
        for vector in scenario.vectors.values():
            if len(vector.bits) != config.element_count:
                raise ValueError("rank vector length disagrees with operation")
            self.capabilities.require(config, vector.format)
        contexts = {item.node: item for item in tree.compile(self.network, config)}
        if scenario.manager not in self.network.nodes:
            raise ValueError("AM is absent from physical network")
        if set(scenario.management_paths) != set(contexts):
            raise ValueError("AM needs one explicit path to each PRISM context")
        transport = FrameNetwork(self.network, fault, reorder)
        for edge in tree.edges:
            transport.bind_path(edge.physical_path, config.mtu)
        for path in scenario.management_paths.values():
            transport.bind_path(path, config.mtu)
        bound_flows = {(edge.child, edge.parent, PacketClass.DATA) for edge in tree.edges} | {
            (edge.parent, edge.child, PacketClass.RESULT) for edge in tree.edges
        }
        if any(
            (rule.source, rule.destination, rule.packet_class) not in bound_flows
            for rule in reorder.rules
        ):
            raise ValueError("reorder rule does not name a bound directed collective flow")
        receivers = {
            name: NodeReceiver(
                mac=self.network.nodes[name].mac,
                ports={
                    link.port_at(name): link.mtu
                    for link in self.network.links.values()
                    if name in (link.left, link.right)
                },
                capacity=self.network.capacities[name],
                capabilities=self.capabilities,
                manager_mac=self.network.nodes[scenario.manager].mac,
                manager_port=self.network.validate_path(
                    scenario.management_paths[name], config.mtu
                )[1],
            )
            for name in contexts
        }
        active = self._configure(scenario, contexts, receivers, transport)
        partials: dict[str, tuple[ExactValue, ...]] = {}
        rank_results: dict[int, tuple[int, ...]] = {}
        rank_values: dict[int, tuple[ExactValue, ...]] = {}
        rank_groups: dict[int, tuple[NumberGroup, ...]] = {}
        completed = False
        try:
            names_by_mac = {physical.mac: name for name, physical in self.network.nodes.items()}

            def aggregate(node: str) -> tuple[ExactValue, ...]:
                context = contexts[node]
                installed = receivers[node].contexts[config.key]
                streams: list[tuple[ExactValue, ...]] = []
                running_fp32: tuple[ExactValue, ...] | None = None
                child_bindings = [
                    binding
                    for binding in installed.record.bindings
                    if binding.local_endpoint in installed.record.child_endpoints
                ]
                transport.rng.shuffle(child_bindings)
                for binding in child_bindings:
                    child = names_by_mac[binding.peer_mac]
                    if binding.peer_kind == PeerKind.RANK:
                        assert binding.rank_id is not None
                        vector = scenario.vectors[binding.rank_id]
                        produced = tuple(decode_native(bits, vector.format) for bits in vector.bits)
                        groups: Iterator[NumberGroup] = (
                            NumberGroup(vector.format, vector.bits[offset : offset + 8192])
                            for offset in range(0, len(vector.bits), 8192)
                        )
                        source_endpoint = binding.peer_endpoint
                        path = transport.route_by_macs(
                            binding.peer_mac, receivers[node].mac, installed.record.mtu
                        )
                    else:
                        produced = aggregate(child)
                        parent_endpoint = (
                            receivers[child].contexts[config.key].record.parent_endpoint
                        )
                        assert parent_endpoint is not None
                        sender_binding = (
                            receivers[child].contexts[config.key].binding(parent_endpoint)
                        )
                        if (
                            sender_binding.peer_endpoint != binding.local_endpoint
                            or sender_binding.peer_mac != receivers[node].mac
                        ):
                            raise ValueError("installed peer bindings disagree")
                        source_endpoint = sender_binding.local_endpoint
                        if installed.record.partial_wire == PartialWirePolicy.AUTO:
                            groups = select_auto_groups(
                                produced, installed.record.kulisch_bits, installed.record.mtu
                            )
                        elif installed.record.partial_wire == PartialWirePolicy.KULISCH:
                            groups = fixed_groups(
                                produced, ConcreteFormat.KULISCH, installed.record.kulisch_bits
                            )
                        else:
                            groups = fixed_groups(
                                produced, ConcreteFormat.FP32, installed.record.kulisch_bits
                            )
                        path, _ingress = transport.bound_route(
                            receivers[child].mac,
                            sender_binding.local_port,
                            sender_binding.peer_mac,
                            installed.record.mtu,
                        )
                    packets = packetize(
                        groups,
                        packet_class=PacketClass.DATA,
                        operation=config.key,
                        source_endpoint=source_endpoint,
                        destination_endpoint=binding.local_endpoint,
                        stream_id=binding.local_endpoint,
                        first_element=0,
                        mtu=installed.record.mtu,
                        kulisch_bits=installed.record.kulisch_bits,
                    )
                    received = self._stream(
                        packets, path, binding.formats, config, context, transport, receivers[node]
                    )
                    if config.accumulator == AccumulatorPolicy.FP32_ARRIVAL:
                        running_fp32 = (
                            received
                            if running_fp32 is None
                            else tuple(
                                decode_native(
                                    round_native(
                                        combine_exact((old, operand)), ConcreteFormat.FP32
                                    ),
                                    ConcreteFormat.FP32,
                                )
                                for old, operand in zip(running_fp32, received, strict=True)
                            )
                        )
                    else:
                        streams.append(received)
                if config.accumulator == AccumulatorPolicy.FP32_ARRIVAL:
                    assert running_fp32 is not None
                    partials[node] = running_fp32
                else:
                    partials[node] = tuple(
                        combine_exact(tuple(stream[index] for stream in streams))
                        for index in range(config.element_count)
                    )
                return partials[node]

            root_values = aggregate(tree.root)
            native_output = (
                ConcreteFormat(int(config.output_format))
                if config.output_format not in (ResultWirePolicy.KULISCH, ResultWirePolicy.AUTO)
                else None
            )
            result_bits = (
                tuple(round_native(value, native_output) for value in root_values)
                if native_output is not None
                else None
            )
            output_values = (
                tuple(decode_native(bits, native_output) for bits in result_bits)
                if result_bits is not None and native_output is not None
                else root_values
            )
            self._deliver_results(
                tree.root,
                contexts,
                config,
                output_values,
                result_bits,
                transport,
                rank_results,
                rank_values,
                rank_groups,
                receivers,
            )
            self._complete_event(scenario, transport)
            completed = True
        finally:
            self._control_all(
                scenario,
                contexts,
                receivers,
                transport,
                active,
                ControlCommand.RELEASE if completed else ControlCommand.ABORT,
            )
        return SoftwareResult(
            rank_results if result_bits is not None else None,
            rank_values,
            rank_groups,
            partials,
            tuple(transport.events),
            transport.tick,
            not active and all(not receiver.contexts for receiver in receivers.values()),
        )

    @staticmethod
    def _children_by_name(tree: CollectiveTree) -> dict[str, list[str]]:
        children: dict[str, list[str]] = {node.name: [] for node in tree.nodes}
        for edge in tree.edges:
            children[edge.parent].append(edge.child)
        return children

    def _configure(
        self,
        scenario: Scenario,
        contexts: Mapping[str, CompiledContext],
        receivers: Mapping[str, NodeReceiver],
        transport: FrameNetwork,
    ) -> set[str]:
        tree, config = scenario.tree, scenario.config
        edges_by_parent = {(edge.parent, edge.child): edge for edge in tree.edges}
        edges_by_child = {edge.child: edge for edge in tree.edges}
        logical = {node.name: node for node in tree.nodes}
        active: set[str] = set()
        staged: set[str] = set()
        try:
            for name, context in contexts.items():
                self._query_capabilities(scenario, name, receivers[name], transport)
                accepted = frozenset(vector.format for vector in scenario.vectors.values())
                if config.partial_wire == PartialWirePolicy.AUTO:
                    accepted |= frozenset(ConcreteFormat)
                elif config.partial_wire == PartialWirePolicy.KULISCH:
                    accepted |= frozenset({ConcreteFormat.KULISCH})
                else:
                    accepted |= frozenset({ConcreteFormat.FP32})
                bindings: list[EndpointBindingRecord] = []
                if name in edges_by_child:
                    edge = edges_by_child[name]
                    parent_context = contexts[edge.parent]
                    first_port, _last_port = self.network.validate_path(
                        edge.physical_path, config.mtu
                    )
                    bindings.append(
                        EndpointBindingRecord(
                            edge.child_endpoint,
                            edge.parent_endpoint,
                            first_port,
                            PeerKind.PRISM,
                            self.network.nodes[edge.parent].mac,
                            None,
                            0,
                            (
                                frozenset(ConcreteFormat)
                                if config.output_format == ResultWirePolicy.AUTO
                                else frozenset({ConcreteFormat(int(config.output_format))})
                            ),
                            name in parent_context.result_destinations,
                        )
                    )
                for child in context.children:
                    edge = edges_by_parent[name, child]
                    _first_port, last_port = self.network.validate_path(
                        edge.physical_path, config.mtu
                    )
                    rank_id = logical[child].rank_id
                    child_formats = (
                        frozenset({scenario.vectors[rank_id].format})
                        if rank_id is not None
                        else frozenset(ConcreteFormat)
                        if config.partial_wire == PartialWirePolicy.AUTO
                        else frozenset({ConcreteFormat.KULISCH})
                        if config.partial_wire == PartialWirePolicy.KULISCH
                        else frozenset({ConcreteFormat.FP32})
                    )
                    bindings.append(
                        EndpointBindingRecord(
                            edge.parent_endpoint,
                            edge.child_endpoint,
                            last_port,
                            PeerKind.RANK if rank_id is not None else PeerKind.PRISM,
                            self.network.nodes[child].mac,
                            rank_id,
                            1 if rank_id is not None else contexts[child].original_terms,
                            child_formats,
                            child in context.result_destinations,
                        )
                    )
                _manager_out, manager_port = self.network.validate_path(
                    scenario.management_paths[name], config.mtu
                )
                record = ContextRecord(
                    NodeRole[context.role],
                    edges_by_child[name].child_endpoint if name in edges_by_child else None,
                    tuple(
                        edges_by_parent[name, child].parent_endpoint for child in context.children
                    ),
                    tuple(
                        edges_by_parent[name, child].parent_endpoint
                        for child in context.result_destinations
                    ),
                    context.original_terms,
                    context.reserved_intervals,
                    context.reserved_bytes,
                    config.element_count,
                    config.kulisch_bits,
                    config.mtu,
                    config.accumulator,
                    config.partial_wire,
                    config.output_format,
                    accepted,
                    config.kind,
                    self.network.nodes[scenario.manager].mac,
                    manager_port,
                    config.maximum_original_terms,
                    frozenset(vector.format for vector in scenario.vectors.values()),
                    tuple(bindings),
                )
                path = scenario.management_paths[name]
                if path[0] != scenario.manager or path[-1] != name:
                    raise ValueError("AM path endpoints disagree with binding")
                # A lost ACK leaves the receiver's STAGE outcome uncertain;
                # include it in rollback before transmitting the request.
                staged.add(name)
                self._control_send(
                    scenario,
                    name,
                    path,
                    ControlCommand.STAGE,
                    record.pack(),
                    receivers[name],
                    transport,
                )
            for name in staged:
                self._control_send(
                    scenario,
                    name,
                    scenario.management_paths[name],
                    ControlCommand.COMMIT,
                    b"",
                    receivers[name],
                    transport,
                )
                active.add(name)
        except Exception as error:
            # No arithmetic starts until every context is committed. Roll back
            # any partial AM transaction using the same explicit paths.
            cleanup_errors: list[str] = []
            for name in staged:
                try:
                    self._control_send(
                        scenario,
                        name,
                        scenario.management_paths[name],
                        ControlCommand.ABORT,
                        b"",
                        receivers[name],
                        transport,
                    )
                except (SimulatedTimeout, ValueError) as cleanup_error:
                    cleanup_errors.append(f"{name}: {cleanup_error}")
            if cleanup_errors:
                raise RuntimeError(
                    f"configuration failed ({error}); rollback incomplete: {cleanup_errors}"
                ) from error
            raise
        return active

    def _query_capabilities(
        self, scenario: Scenario, name: str, receiver: NodeReceiver, transport: FrameNetwork
    ) -> None:
        path = scenario.management_paths[name]
        if path[0] != scenario.manager or path[-1] != name:
            raise ValueError("AM capability path endpoints disagree with binding")
        self.network.validate_path(path, scenario.config.mtu)
        query = ControlPacket(scenario.config.key, 0, 0xFFFE, 0xFFFE, ControlCommand.CAPS_QUERY)
        request = encode_control_frame(
            query,
            destination_mac=self.network.nodes[name].mac,
            source_mac=self.network.nodes[scenario.manager].mac,
            mtu=scenario.config.mtu,
        )
        if not transport.transmit(request, path, PacketClass.CONTROL, 0):
            raise SimulatedTimeout("capability query was lost")
        _out, ingress = self.network.validate_path(path, scenario.config.mtu)
        pages = receiver.capability_pages(request, ingress_port=ingress, mtu=scenario.config.mtu)
        records: list[CapabilityRecord] = []
        for index, body in enumerate(pages):
            response = ControlPacket(
                scenario.config.key,
                0,
                0xFFFE,
                0xFFFE,
                ControlCommand.CAPS_RESPONSE,
                body=body,
                fragment_index=index,
                fragment_count=len(pages),
            )
            frame = encode_control_frame(
                response,
                destination_mac=self.network.nodes[scenario.manager].mac,
                source_mac=self.network.nodes[name].mac,
                mtu=scenario.config.mtu,
            )
            if not transport.transmit(frame, path[::-1], PacketClass.CONTROL, 0x80000000 + index):
                raise SimulatedTimeout("capability response fragment was lost")
            decoded = decode_control_frame(frame, mtu=scenario.config.mtu)
            if decoded.fragment_index != index or decoded.fragment_count != len(pages):
                raise ValueError("incomplete capability response")
            page_catalog, capacity = decode_capabilities(decoded.body)
            if capacity != self.network.capacities[name]:
                raise ValueError("advertised and configured node resources disagree")
            records.extend(page_catalog.records)
        catalog = CapabilityCatalog(tuple(records))
        for vector in scenario.vectors.values():
            catalog.require(scenario.config, vector.format)

    def _complete_event(self, scenario: Scenario, transport: FrameNetwork) -> None:
        path = scenario.management_paths[scenario.tree.root][::-1]
        packet = ControlPacket(
            scenario.config.key,
            int(ControlCommand.COMPLETE),
            0xFFFE,
            0xFFFE,
            ControlCommand.COMPLETE,
        )
        frame = encode_control_frame(
            packet,
            destination_mac=self.network.nodes[scenario.manager].mac,
            source_mac=self.network.nodes[scenario.tree.root].mac,
            mtu=scenario.config.mtu,
        )
        if not transport.transmit(frame, path, PacketClass.CONTROL, int(ControlCommand.COMPLETE)):
            raise SimulatedTimeout("operation completion event was lost")
        if decode_control_frame(frame, mtu=scenario.config.mtu) != packet:
            raise AssertionError("completion event failed binary validation")

    def _control_send(
        self,
        scenario: Scenario,
        name: str,
        path: tuple[str, ...],
        command: ControlCommand,
        body: bytes,
        receiver: NodeReceiver,
        transport: FrameNetwork,
    ) -> None:
        packet = ControlPacket(
            scenario.config.key, int(command), 0xFFFE, 0xFFFE, command, body=body
        )
        frame = encode_control_frame(
            packet,
            destination_mac=self.network.nodes[name].mac,
            source_mac=self.network.nodes[scenario.manager].mac,
            mtu=scenario.config.mtu,
        )
        _out, ingress = self.network.validate_path(path, scenario.config.mtu)
        for attempt in range(transport.fault.maximum_retries + 1):
            if attempt:
                transport.tick += transport.fault.retry_ticks
            if not transport.transmit(frame, path, PacketClass.CONTROL, int(command)):
                continue
            ack = receiver.handle_control(frame, ingress_port=ingress, mtu=scenario.config.mtu)
            reply = encode_control_frame(
                ack,
                destination_mac=self.network.nodes[scenario.manager].mac,
                source_mac=receiver.mac,
                mtu=scenario.config.mtu,
            )
            if not transport.transmit(reply, path[::-1], PacketClass.CONTROL, int(command)):
                continue
            decoded = decode_control_frame(reply, mtu=scenario.config.mtu)
            if decoded != ack or decoded.transaction_id != packet.transaction_id:
                raise ValueError("CONTROL acknowledgment identity changed")
            if decoded.status != ControlStatus.OK:
                raise ValueError(
                    f"{name} rejected {command.name}: {ControlStatus(decoded.status).name}"
                )
            return
        raise SimulatedTimeout(f"AM {command.name} acknowledgment timed out at {name}")

    def _control_all(
        self,
        scenario: Scenario,
        contexts: Mapping[str, CompiledContext],
        receivers: Mapping[str, NodeReceiver],
        transport: FrameNetwork,
        active: set[str],
        command: ControlCommand,
    ) -> None:
        errors: list[str] = []
        for name in contexts:
            if name not in active:
                continue
            try:
                self._control_send(
                    scenario,
                    name,
                    scenario.management_paths[name],
                    command,
                    b"",
                    receivers[name],
                    transport,
                )
                active.remove(name)
            except (SimulatedTimeout, ValueError) as error:
                errors.append(f"{name}: {error}")
        if errors or any(receiver.contexts for receiver in receivers.values()):
            raise RuntimeError(
                f"context cleanup incomplete: {errors or 'receiver retains reservations'}"
            )

    def _stream(
        self,
        packets: Iterator[DataPacket],
        path: tuple[str, ...],
        allowed: frozenset[ConcreteFormat],
        config: OperationConfig,
        context: CompiledContext,
        transport: FrameNetwork,
        receiver: NodeReceiver | None = None,
    ) -> tuple[ExactValue, ...]:
        first = next(packets, None)
        if first is None:
            raise ValueError("DATA/RES stream cannot be empty")
        capacity = min(
            context.reserved_intervals, max(1, context.reserved_bytes // (config.mtu + 14))
        )
        if receiver is None:
            window = ReceiveWindow(
                operation=config.key,
                packet_class=first.packet_class,
                source_endpoint=first.source_endpoint,
                destination_endpoint=first.destination_endpoint,
                stream_id=first.stream_id,
                element_count=config.element_count,
                allowed_formats=allowed,
                mtu=config.mtu,
                kulisch_bits=config.kulisch_bits,
                maximum_intervals=context.reserved_intervals,
                maximum_bytes=context.reserved_bytes,
                element_span=capacity * config.mtu,
            )
            window.activate()
        else:
            installed = receiver.contexts[config.key]
            if not installed.active or installed.windows is None:
                raise ValueError("receiver has no committed window")
            window = installed.windows[(first.packet_class, first.destination_endpoint)]
        capacity = min(
            window.maximum_intervals,
            max(1, window.maximum_bytes // (config.mtu + 14)),
        )
        _out, ingress = self.network.validate_path(path, config.mtu)
        packets = chain((first,), packets)
        received: list[ExactValue] = []
        while True:
            wave = list(islice(packets, capacity))
            if not wave:
                break
            wave = transport.reorder.arrange(
                wave,
                source=path[0],
                destination=path[-1],
                packet_class=first.packet_class,
                stream_id=first.stream_id,
                batch=wave[0].packet_id,
            )
            retry: list[tuple[DataPacket, bytes]] = []
            for packet in wave:
                frame = encode_data_frame(
                    packet,
                    destination_mac=self.network.nodes[path[-1]].mac,
                    source_mac=self.network.nodes[path[0]].mac,
                    mtu=config.mtu,
                    kulisch_bits=config.kulisch_bits,
                )
                if not transport.transmit(frame, path, packet.packet_class, packet.packet_id):
                    retry.append((packet, frame))
                    continue
                if not self._receive_and_ack(
                    packet, frame, path, window, transport, received, receiver, ingress
                ):
                    retry.append((packet, frame))
            for packet, frame in retry:
                for _attempt in range(1, transport.fault.maximum_retries + 1):
                    transport.tick += transport.fault.retry_ticks
                    if transport.transmit(frame, path, packet.packet_class, packet.packet_id) and (
                        self._receive_and_ack(
                            packet, frame, path, window, transport, received, receiver, ingress
                        )
                    ):
                        break
                else:
                    raise SimulatedTimeout(
                        f"stream {packet.stream_id} packet {packet.packet_id} timed out"
                    )
        if not window.complete or len(received) != config.element_count:
            raise SimulatedTimeout("stream ended with holes or without LAST")
        return tuple(received)

    def _receive_and_ack(
        self,
        packet: DataPacket,
        frame: bytes,
        path: tuple[str, ...],
        window: ReceiveWindow,
        transport: FrameNetwork,
        received: list[ExactValue],
        receiver: NodeReceiver | None,
        ingress_port: int,
    ) -> bool:
        if receiver is None:
            admission = window.accept(frame)
        else:
            admission, installed_window = receiver.accept_data(frame, ingress_port=ingress_port)
            if installed_window is not window:
                raise ValueError("receiver selected another installed stream")
        if admission == Admission.ACCEPTED:
            while (chunk := window.peek_contiguous()) is not None:
                # Stage the entire validated range and publish it in one list
                # assignment before releasing interval and byte credits.
                received[:] = [*received, *chunk.values]
                window.release_contiguous(chunk)
        status = {
            Admission.ACCEPTED: ProgressStatus.ACCEPTED,
            Admission.DUPLICATE: ProgressStatus.DUPLICATE,
            Admission.NO_CREDIT: ProgressStatus.RETRY,
            Admission.OUT_OF_WINDOW: ProgressStatus.OUT_OF_WINDOW,
            Admission.OVERLAP: ProgressStatus.REJECTED,
        }[admission]
        progress = ProgressPacket(
            packet.operation,
            packet.destination_endpoint,
            packet.source_endpoint,
            packet.stream_id,
            packet.packet_id,
            window.base,
            window.credit_intervals,
            window.credit_bytes,
            status,
            window.complete,
            window.holes[:32],
        )
        ack = encode_progress_frame(
            progress,
            destination_mac=self.network.nodes[path[0]].mac,
            source_mac=self.network.nodes[path[-1]].mac,
            mtu=window.mtu,
        )
        if not transport.transmit(ack, path[::-1], PacketClass.PROGRESS, packet.packet_id):
            return False
        decoded = decode_progress_frame(ack, mtu=window.mtu)
        if decoded != progress or status not in (
            ProgressStatus.ACCEPTED,
            ProgressStatus.DUPLICATE,
        ):
            raise ValueError("receiver rejected packet or progress was corrupted")
        return True

    def _deliver_results(
        self,
        root: str,
        contexts: Mapping[str, CompiledContext],
        config: OperationConfig,
        output_values: tuple[ExactValue, ...],
        bits: tuple[int, ...] | None,
        transport: FrameNetwork,
        rank_results: dict[int, tuple[int, ...]],
        rank_values: dict[int, tuple[ExactValue, ...]],
        rank_groups: dict[int, tuple[NumberGroup, ...]],
        receivers: Mapping[str, NodeReceiver],
    ) -> None:
        names_by_mac = {node.mac: name for name, node in self.network.nodes.items()}

        def deliver(node: str, values: tuple[ExactValue, ...]) -> None:
            installed = receivers[node].contexts[config.key]
            for binding in installed.record.bindings:
                if (
                    binding.local_endpoint not in installed.record.child_endpoints
                    or not binding.result_enabled
                ):
                    continue
                groups = (
                    select_auto_groups(values, config.kulisch_bits, config.mtu)
                    if config.output_format == ResultWirePolicy.AUTO
                    else fixed_groups(
                        values, ConcreteFormat(int(config.output_format)), config.kulisch_bits
                    )
                )
                packets = tuple(
                    packetize(
                        groups,
                        packet_class=PacketClass.RESULT,
                        operation=config.key,
                        source_endpoint=binding.local_endpoint,
                        destination_endpoint=binding.peer_endpoint,
                        stream_id=binding.peer_endpoint,
                        first_element=0,
                        mtu=config.mtu,
                        kulisch_bits=config.kulisch_bits,
                    )
                )
                path, _ingress = transport.bound_route(
                    receivers[node].mac, binding.local_port, binding.peer_mac, config.mtu
                )
                child = names_by_mac[binding.peer_mac]
                context = contexts[node]
                arrived = self._stream(
                    iter(packets),
                    path,
                    (
                        frozenset(ConcreteFormat)
                        if config.output_format == ResultWirePolicy.AUTO
                        else frozenset({ConcreteFormat(int(config.output_format))})
                    ),
                    config,
                    context,
                    transport,
                    None if binding.peer_kind == PeerKind.RANK else receivers[child],
                )
                if binding.peer_kind == PeerKind.RANK:
                    assert binding.rank_id is not None
                    rank_values[binding.rank_id] = arrived
                    rank_groups[binding.rank_id] = tuple(
                        group for packet in packets for group in packet.groups
                    )
                    if bits is not None:
                        rank_results[binding.rank_id] = tuple(
                            round_native(value, ConcreteFormat(int(config.output_format)))
                            for value in arrived
                        )
                else:
                    deliver(child, arrived)

        deliver(root, output_values)
        if config.kind == CollectiveKind.ALLREDUCE:
            recipients = set(config.ranks)
        else:
            assert config.reduce_destination is not None
            recipients = {config.reduce_destination}
        if set(rank_values) != recipients or any(
            value != output_values for value in rank_values.values()
        ):
            raise AssertionError("result routing did not deliver the completed vector")
        if bits is not None and any(value != bits for value in rank_results.values()):
            raise AssertionError("native RESULT bits differ from the selected rounding")
