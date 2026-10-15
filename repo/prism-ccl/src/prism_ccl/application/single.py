"""One operation on one SINGLE PRISM node, driven through Ethernet frames.

The functions here compile a scenario for one node, build the frames the
manager and the ranks send, and check what the node answers. They do not
depend on how frames travel: a transport sends a frame on a port of the node
and returns the next frame the node sent that matches what is awaited. The
same code drives a simulation of the node and a node on a real network.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol, cast

from ..domain.capabilities import single_rtl_capabilities
from ..domain.model import ConcreteFormat, ResultWirePolicy
from ..domain.numbers import ExactValue, decode_kulisch, decode_native
from ..domain.topology import PhysicalNetwork
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
from ..wire.data import DataPacket, NumberGroup, PacketClass, decode_data_frame, encode_data_frame
from .packing import packetize
from .software import Scenario

# Transaction identifiers of the manager's commands for one operation.
STAGE_TRANSACTION = 10
COMMIT_TRANSACTION = 11
RELEASE_TRANSACTION = 12
ABORT_TRANSACTION = 13


@dataclass(frozen=True, slots=True)
class RankBinding:
    rank: int
    port: int
    local_endpoint: int
    peer_endpoint: int
    peer_mac: bytes
    result_enabled: bool


@dataclass(frozen=True, slots=True)
class SingleBinding:
    node_mac: bytes
    manager_mac: bytes
    context: ContextRecord
    ranks: tuple[RankBinding, ...]


@dataclass(frozen=True, slots=True)
class SingleOutcome:
    """What the ranks with a result received.

    ``rank_bits`` holds the raw native values for a native output format and
    is None otherwise; ``rank_values`` holds the decoded values for every
    output format.
    """

    rank_bits: dict[int, tuple[int, ...]] | None
    rank_values: dict[int, tuple[ExactValue, ...]]
    rank_groups: dict[int, tuple[NumberGroup, ...]]


class FrameTransport(Protocol):
    """Carries frames to and from the ports of one node."""

    async def send(self, port: int, frame: bytes) -> None: ...

    async def receive(
        self, packet_class: PacketClass, *, port: int, destination_mac: bytes | None = None
    ) -> bytes: ...


def compile_single(
    network: PhysicalNetwork,
    scenario: Scenario,
    prism_name: str,
    *,
    physical_ports: int = 2,
) -> SingleBinding:
    """Compile the logical tree, then narrow it to the ports of the node."""
    config = scenario.config
    contexts = scenario.tree.compile(network, config)
    if len(contexts) != 1 or contexts[0].node != prism_name or contexts[0].role != "SINGLE":
        raise ValueError("compiled binding requires exactly one SINGLE PRISM node")
    if set(scenario.vectors) != set(config.ranks):
        raise ValueError("SINGLE node requires all rank vectors")
    for vector in scenario.vectors.values():
        if len(vector.bits) != config.element_count:
            raise ValueError("rank vector length disagrees with the operation")
        single_rtl_capabilities().require(config, vector.format)
    manager_path = scenario.management_paths.get(prism_name)
    if manager_path is None or manager_path[0] != scenario.manager:
        raise ValueError("SINGLE node needs an explicit AM physical path")
    _manager_out, manager_port = network.validate_path(manager_path, config.mtu)
    if manager_port != 0:
        raise ValueError("compiled AM path must enter the node on physical port zero")
    context = contexts[0]
    edges = {edge.child: edge for edge in scenario.tree.edges}
    logical = {node.name: node for node in scenario.tree.nodes}
    ranks: list[RankBinding] = []
    records: list[EndpointBindingRecord] = []
    for child in context.children:
        edge = edges[child]
        rank = logical[child].rank_id
        if rank is None:
            raise ValueError("SINGLE hardware accepts only directly bound rank children")
        _out, local_port = network.validate_path(edge.physical_path, config.mtu)
        if not 0 <= local_port < physical_ports:
            raise ValueError("logical rank path is not bound to a port of the node")
        rank_binding = RankBinding(
            rank,
            local_port,
            edge.parent_endpoint,
            edge.child_endpoint,
            network.nodes[child].mac,
            child in context.result_destinations,
        )
        ranks.append(rank_binding)
        records.append(
            EndpointBindingRecord(
                rank_binding.local_endpoint,
                rank_binding.peer_endpoint,
                rank_binding.port,
                PeerKind.RANK,
                rank_binding.peer_mac,
                rank,
                1,
                frozenset({scenario.vectors[rank].format}),
                rank_binding.result_enabled,
            )
        )
    if len(ranks) > 8 or context.reserved_intervals > 16:
        raise ValueError("SINGLE context exceeds compiled rank or interval resources")
    result_endpoints = tuple(binding.local_endpoint for binding in ranks if binding.result_enabled)
    formats = frozenset(vector.format for vector in scenario.vectors.values())
    record = ContextRecord(
        NodeRole.SINGLE,
        None,
        tuple(binding.local_endpoint for binding in ranks),
        result_endpoints,
        context.original_terms,
        context.reserved_intervals,
        context.reserved_bytes,
        config.element_count,
        config.kulisch_bits,
        config.mtu,
        config.accumulator,
        config.partial_wire,
        config.output_format,
        formats,
        config.kind,
        network.nodes[scenario.manager].mac,
        manager_port,
        config.maximum_original_terms,
        formats,
        tuple(records),
    )
    if context.reserved_bytes < len(ranks) * (config.mtu + 14):
        raise ValueError("compiled receive window lacks one frame per rank")
    return SingleBinding(
        network.nodes[prism_name].mac,
        network.nodes[scenario.manager].mac,
        record,
        tuple(ranks),
    )


def rank_data_frames(
    scenario: Scenario, binding: SingleBinding, rank_binding: RankBinding
) -> tuple[list[bytes], list[DataPacket]]:
    """The DATA frames of one rank in sending order, with their packets."""
    vector = scenario.vectors[rank_binding.rank]
    sent_packets: list[DataPacket] = []
    frames: list[bytes] = []
    packets = packetize(
        (NumberGroup(vector.format, vector.bits),),
        packet_class=PacketClass.DATA,
        operation=scenario.config.key,
        source_endpoint=rank_binding.peer_endpoint,
        destination_endpoint=rank_binding.local_endpoint,
        stream_id=rank_binding.local_endpoint,
        first_element=0,
        mtu=scenario.config.mtu,
        kulisch_bits=scenario.config.kulisch_bits,
    )
    for generated in packets:
        packet = replace(generated, packet_id=rank_binding.rank + 1 + generated.packet_id)
        frames.append(
            encode_data_frame(
                packet,
                destination_mac=binding.node_mac,
                source_mac=rank_binding.peer_mac,
                mtu=scenario.config.mtu,
                kulisch_bits=scenario.config.kulisch_bits,
            )
        )
        sent_packets.append(packet)
    return frames, sent_packets


def control_frame(
    scenario: Scenario,
    binding: SingleBinding,
    command: ControlCommand,
    transaction: int,
    body: bytes = b"",
) -> bytes:
    """A command of the manager to the node."""
    packet = ControlPacket(scenario.config.key, transaction, 0xFFFE, 0xFFFE, command, body=body)
    return encode_control_frame(
        packet,
        destination_mac=binding.node_mac,
        source_mac=binding.manager_mac,
        mtu=scenario.config.mtu,
    )


def check_acknowledgement(
    scenario: Scenario, frame: bytes, command: ControlCommand, transaction: int
) -> None:
    """Raise unless the frame acknowledges the command with OK."""
    response = decode_control_frame(frame, mtu=scenario.config.mtu)
    if (
        response.command != ControlCommand.ACK
        or response.transaction_id != transaction
        or response.status != ControlStatus.OK
    ):
        raise AssertionError(f"operation {scenario.config.key}: {command.name} returned {response}")


class ResultCollector:
    """Collects the RESULT frames of one rank and checks each of them."""

    def __init__(self, scenario: Scenario, rank_binding: RankBinding) -> None:
        self.scenario = scenario
        self.rank_binding = rank_binding
        self.pieces: dict[int, tuple[int | bytes, ...]] = {}
        self.groups: dict[int, tuple[NumberGroup, ...]] = {}
        self.identities: dict[int, bytes] = {}
        self.watermark = 0
        self.last_seen = False
        self.frames = 0

    @property
    def complete(self) -> bool:
        return self.watermark == self.scenario.config.element_count and self.last_seen

    def add(self, frame: bytes) -> None:
        config = self.scenario.config
        rank = self.rank_binding
        result = decode_data_frame(frame, mtu=config.mtu, kulisch_bits=config.kulisch_bits)
        if result.accumulation_inexact:
            raise ArithmeticError(
                f"operation {config.key}: rank {rank.rank} received ACCUMULATION_INEXACT; "
                "no result vector is valid"
            )
        self.frames += 1
        if self.frames > config.element_count:
            raise AssertionError("RESULT stream exceeds the vector packet bound")
        if (
            result.packet_class != PacketClass.RESULT
            or result.operation != config.key
            or result.source_endpoint != rank.local_endpoint
            or result.destination_endpoint != rank.peer_endpoint
            or result.stream_id != rank.peer_endpoint
            or result.first_element + result.element_count > config.element_count
            or result.last != (result.first_element + result.element_count == config.element_count)
            or (
                config.output_format != ResultWirePolicy.AUTO
                and any(
                    group.format != ConcreteFormat(int(config.output_format))
                    for group in result.groups
                )
            )
        ):
            raise AssertionError(
                f"operation {config.key}: rank {rank.rank} received a mismatched RESULT"
            )
        if result.packet_id in self.identities:
            raise AssertionError("duplicate RESULT packet")
        start = result.first_element
        end = start + result.element_count
        if any(
            start < position + len(values) and end > position
            for position, values in self.pieces.items()
        ):
            raise AssertionError("RESULT intervals overlap under different packet IDs")
        self.identities[result.packet_id] = frame
        self.pieces[start] = tuple(value for group in result.groups for value in group.values)
        self.groups[start] = result.groups
        if result.last:
            self.last_seen = True
        while self.watermark in self.pieces:
            self.watermark += len(self.pieces[self.watermark])

    def ordered_groups(self) -> tuple[NumberGroup, ...]:
        return tuple(group for first in sorted(self.groups) for group in self.groups[first])

    def ordered_values(self) -> tuple[int | bytes, ...]:
        return tuple(value for first in sorted(self.pieces) for value in self.pieces[first])


def _native_output(scenario: Scenario) -> bool:
    return scenario.config.output_format in (
        ResultWirePolicy.INT8,
        ResultWirePolicy.FP16,
        ResultWirePolicy.BF16,
        ResultWirePolicy.FP32,
    )


async def run_single(
    scenario: Scenario, binding: SingleBinding, transport: FrameTransport
) -> SingleOutcome:
    """Run one operation: stage, commit, send every rank's DATA, collect the
    results, release. A failure after the stage aborts the operation."""
    staged = False
    try:
        await transport.send(
            0,
            control_frame(
                scenario,
                binding,
                ControlCommand.STAGE,
                STAGE_TRANSACTION,
                binding.context.pack(),
            ),
        )
        check_acknowledgement(
            scenario,
            await transport.receive(PacketClass.CONTROL, port=0),
            ControlCommand.STAGE,
            STAGE_TRANSACTION,
        )
        staged = True
        await transport.send(
            0, control_frame(scenario, binding, ControlCommand.COMMIT, COMMIT_TRANSACTION)
        )
        check_acknowledgement(
            scenario,
            await transport.receive(PacketClass.CONTROL, port=0),
            ControlCommand.COMMIT,
            COMMIT_TRANSACTION,
        )
        for rank_binding in sorted(binding.ranks, key=lambda rank: (rank.port, rank.rank)):
            frames, _packets = rank_data_frames(scenario, binding, rank_binding)
            for frame in frames:
                await transport.send(rank_binding.port, frame)
        rank_bits: dict[int, tuple[int, ...]] | None = {} if _native_output(scenario) else None
        rank_values: dict[int, tuple[ExactValue, ...]] = {}
        rank_groups: dict[int, tuple[NumberGroup, ...]] = {}
        for rank_binding in binding.ranks:
            if not rank_binding.result_enabled:
                continue
            collector = ResultCollector(scenario, rank_binding)
            while not collector.complete:
                collector.add(
                    await transport.receive(
                        PacketClass.RESULT,
                        port=rank_binding.port,
                        destination_mac=rank_binding.peer_mac,
                    )
                )
            groups = collector.ordered_groups()
            rank_groups[rank_binding.rank] = groups
            rank_values[rank_binding.rank] = tuple(
                decode_kulisch(value, scenario.config.kulisch_bits)
                if isinstance(value, bytes)
                else decode_native(value, group.format)
                for group in groups
                for value in group.values
            )
            if rank_bits is not None:
                ordered = collector.ordered_values()
                if any(not isinstance(value, int) for value in ordered):
                    raise AssertionError("native RESULT contains non-native values")
                rank_bits[rank_binding.rank] = cast(tuple[int, ...], ordered)
        await transport.send(
            0, control_frame(scenario, binding, ControlCommand.RELEASE, RELEASE_TRANSACTION)
        )
        check_acknowledgement(
            scenario,
            await transport.receive(PacketClass.CONTROL, port=0),
            ControlCommand.RELEASE,
            RELEASE_TRANSACTION,
        )
        return SingleOutcome(rank_bits, rank_values, rank_groups)
    except Exception:
        if staged:
            # The first failure is what matters; the abort only tidies up.
            with contextlib.suppress(Exception):
                await transport.send(
                    0, control_frame(scenario, binding, ControlCommand.ABORT, ABORT_TRANSACTION)
                )
        raise


@dataclass(frozen=True, slots=True)
class ScriptStep:
    """One step of a frame script for a node that cannot answer interactively.

    ``send``: put ``frame`` on ``port``. ``await_frames``: wait until the
    node has sent ``count`` more frames on ``port``. ``await_quiet``: wait
    until the node has sent nothing for ``count`` cycles.
    """

    kind: str
    port: int = 0
    count: int = 0
    frame: bytes = b""


def script_single(
    scenario: Scenario, binding: SingleBinding, *, quiet_cycles: int = 4000
) -> tuple[ScriptStep, ...]:
    """The steps of run_single for a simulation that replays a script.

    Each command waits for its acknowledgement; after the DATA the script
    waits until the node has been quiet long enough to have sent its results.
    """
    steps = [
        ScriptStep(
            "send",
            0,
            frame=control_frame(
                scenario,
                binding,
                ControlCommand.STAGE,
                STAGE_TRANSACTION,
                binding.context.pack(),
            ),
        ),
        ScriptStep("await_frames", 0, 1),
        ScriptStep(
            "send",
            0,
            frame=control_frame(scenario, binding, ControlCommand.COMMIT, COMMIT_TRANSACTION),
        ),
        ScriptStep("await_frames", 0, 1),
    ]
    for rank_binding in sorted(binding.ranks, key=lambda rank: (rank.port, rank.rank)):
        frames, _packets = rank_data_frames(scenario, binding, rank_binding)
        steps.extend(ScriptStep("send", rank_binding.port, frame=frame) for frame in frames)
    steps.append(ScriptStep("await_quiet", 0, quiet_cycles))
    steps.append(
        ScriptStep(
            "send",
            0,
            frame=control_frame(scenario, binding, ControlCommand.RELEASE, RELEASE_TRANSACTION),
        )
    )
    steps.append(ScriptStep("await_frames", 0, 1))
    return tuple(steps)


class ReplayTransport:
    """Answers run_single with the frames a node sent in a recorded run.

    ``received`` holds the frames the node sent, as (port, frame), in the
    order it sent them. A receive takes the first frame not taken yet that
    matches the awaited class, port and destination.
    """

    def __init__(self, received: Sequence[tuple[int, bytes]]) -> None:
        self.received = list(received)
        self.taken = [False] * len(self.received)
        self.sent: list[tuple[int, bytes]] = []

    async def send(self, port: int, frame: bytes) -> None:
        self.sent.append((port, frame))

    async def receive(
        self, packet_class: PacketClass, *, port: int, destination_mac: bytes | None = None
    ) -> bytes:
        for index, (frame_port, frame) in enumerate(self.received):
            if self.taken[index] or frame_port != port or len(frame) < 16:
                continue
            if frame[15] != int(packet_class):
                continue
            if destination_mac is not None and frame[:6] != destination_mac:
                continue
            self.taken[index] = True
            return frame
        raise TimeoutError(
            f"the recorded run has no further {packet_class.name} frame on port {port}"
        )

    def untaken(self) -> list[tuple[int, bytes]]:
        return [frame for frame, taken in zip(self.received, self.taken, strict=True) if not taken]
