"""The driver of one SINGLE operation, against a node that answers in software."""

from __future__ import annotations

import asyncio

import pytest

from prism_ccl.application.packing import packetize
from prism_ccl.application.single import (
    ReplayTransport,
    SingleBinding,
    compile_single,
    rank_data_frames,
    run_single,
    script_single,
)
from prism_ccl.application.software import Scenario
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode, PrismCapacity
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
    ControlStatus,
    decode_control_frame,
    encode_control_frame,
)
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame
from prism_ccl.world import PrismWorld

FORMAT = ConcreteFormat.FP32
# Two RESULT packets: 512 FP32 values do not fit one 1500-byte frame.
LEFT = tuple(round_native(decode_native(x & 255, ConcreteFormat.INT8), FORMAT) for x in range(512))
RIGHT = tuple(reversed(LEFT))


def _operation() -> tuple[Scenario, SingleBinding]:
    world = PrismWorld(manager="am")
    world.add_node("am", bytes.fromhex("0250524953ff"))
    world.add_node("hub", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_prism(
        "s", bytes.fromhex("025052495300"), capacity=PrismCapacity(2, 2, 2, 65536, True, False)
    )
    world.connect("am", 1, "hub", 1)
    world.connect("hub", 2, "s", 0)
    nodes, edges = [LogicalNode("s")], []
    for rank in range(2):
        name = f"r{rank}"
        world.add_node(name, bytes((2, 0, 0, 0, 0, rank + 10)))
        world.connect(name, 1, "hub", rank + 3)
        nodes.append(LogicalNode(name, rank))
        edges.append(LogicalEdge(name, "s", 1, 10 + rank, (name, "hub", "s")))
    world.register_reduce(
        "op",
        tree=CollectiveTree("s", tuple(nodes), tuple(edges)),
        vectors={0: TypedVector(FORMAT, LEFT), 1: TypedVector(FORMAT, RIGHT)},
        destination_rank=1,
        management_paths={"s": ("am", "hub", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.FP32,
        kulisch_bits=280,
        maximum_original_terms=2,
    )
    scenario = world.scenario("op")
    return scenario, compile_single(world.network, scenario, "s", physical_ports=1)


EXPECTED_BITS = tuple(
    round_native(combine_exact((decode_native(a, FORMAT), decode_native(b, FORMAT))), FORMAT)
    for a, b in zip(LEFT, RIGHT, strict=True)
)


class AnsweringNode:
    """Acknowledges commands and sends the result once all DATA has arrived."""

    def __init__(
        self,
        scenario: Scenario,
        binding: SingleBinding,
        *,
        refuse: ControlCommand | None = None,
        repeat_result: bool = False,
        inexact: bool = False,
    ) -> None:
        self.scenario = scenario
        self.binding = binding
        self.refuse = refuse
        self.repeat_result = repeat_result
        self.inexact = inexact
        self.sent_by_node: list[tuple[int, bytes]] = []
        self.received: list[tuple[int, bytes]] = []
        self.queue: list[tuple[int, bytes]] = []
        self.data_frames = 0
        self.expected_data_frames = sum(
            len(rank_data_frames(scenario, binding, rank)[0]) for rank in binding.ranks
        )

    def _answer(self, port: int, frame: bytes) -> None:
        self.queue.append((port, frame))
        self.sent_by_node.append((port, frame))

    async def send(self, port: int, frame: bytes) -> None:
        self.received.append((port, frame))
        config = self.scenario.config
        if frame[15] == int(PacketClass.CONTROL):
            packet = decode_control_frame(frame, mtu=config.mtu)
            status = ControlStatus.OK if packet.command != self.refuse else ControlStatus.BAD_STATE
            ack = ControlPacket(
                packet.operation,
                packet.transaction_id,
                0xFFFE,
                0xFFFE,
                ControlCommand.ACK,
                status=int(status),
            )
            self._answer(
                0,
                encode_control_frame(
                    ack,
                    destination_mac=self.binding.manager_mac,
                    source_mac=self.binding.node_mac,
                    mtu=config.mtu,
                ),
            )
            return
        self.data_frames += 1
        if self.data_frames < self.expected_data_frames:
            return
        rank = next(rank for rank in self.binding.ranks if rank.result_enabled)
        if self.inexact:
            # An inexact accumulation ends the result with one empty packet.
            terminal = DataPacket(
                PacketClass.RESULT,
                config.key,
                rank.local_endpoint,
                rank.peer_endpoint,
                rank.peer_endpoint,
                1,
                0,
                (),
                last=True,
                accumulation_inexact=True,
            )
            self._answer(
                rank.port,
                encode_data_frame(
                    terminal,
                    destination_mac=rank.peer_mac,
                    source_mac=self.binding.node_mac,
                    mtu=config.mtu,
                    kulisch_bits=config.kulisch_bits,
                ),
            )
            return
        for packet in packetize(
            (NumberGroup(FORMAT, EXPECTED_BITS),),
            packet_class=PacketClass.RESULT,
            operation=config.key,
            source_endpoint=rank.local_endpoint,
            destination_endpoint=rank.peer_endpoint,
            stream_id=rank.peer_endpoint,
            first_element=0,
            mtu=config.mtu,
            kulisch_bits=config.kulisch_bits,
        ):
            frame = encode_data_frame(
                packet,
                destination_mac=rank.peer_mac,
                source_mac=self.binding.node_mac,
                mtu=config.mtu,
                kulisch_bits=config.kulisch_bits,
            )
            self._answer(rank.port, frame)
            if self.repeat_result:
                self._answer(rank.port, frame)

    async def receive(
        self, packet_class: PacketClass, *, port: int, destination_mac: bytes | None = None
    ) -> bytes:
        for index, (frame_port, frame) in enumerate(self.queue):
            if (
                frame_port == port
                and frame[15] == int(packet_class)
                and (destination_mac is None or frame[:6] == destination_mac)
            ):
                return self.queue.pop(index)[1]
        raise TimeoutError(f"no {packet_class.name} waiting on port {port}")

    def commands(self) -> list[ControlCommand]:
        return [
            decode_control_frame(frame, mtu=self.scenario.config.mtu).command
            for _port, frame in self.received
            if frame[15] == int(PacketClass.CONTROL)
        ]


def test_an_operation_collects_the_result_and_releases_the_node() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding)
    outcome = asyncio.run(run_single(scenario, binding, node))
    assert outcome.rank_bits == {1: EXPECTED_BITS}
    assert set(outcome.rank_values) == {1}
    assert node.commands() == [ControlCommand.STAGE, ControlCommand.COMMIT, ControlCommand.RELEASE]
    assert node.data_frames == node.expected_data_frames == 4


def test_a_recorded_run_replays_to_the_same_outcome() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding)
    outcome = asyncio.run(run_single(scenario, binding, node))
    replay = ReplayTransport(node.sent_by_node)
    assert asyncio.run(run_single(scenario, binding, replay)) == outcome
    assert not replay.untaken()
    assert replay.sent == node.received


def test_the_script_sends_what_the_driver_sends() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding)
    asyncio.run(run_single(scenario, binding, node))
    steps = script_single(scenario, binding, quiet_cycles=100)
    assert [(step.port, step.frame) for step in steps if step.kind == "send"] == node.received
    kinds = [step.kind for step in steps if step.kind != "send"]
    assert kinds == ["await_frames", "await_frames", "await_quiet", "await_frames"]


def test_a_refused_commit_aborts_the_operation() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding, refuse=ControlCommand.COMMIT)
    with pytest.raises(AssertionError, match="COMMIT"):
        asyncio.run(run_single(scenario, binding, node))
    assert node.commands() == [ControlCommand.STAGE, ControlCommand.COMMIT, ControlCommand.ABORT]


def test_a_refused_stage_is_not_aborted() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding, refuse=ControlCommand.STAGE)
    with pytest.raises(AssertionError, match="STAGE"):
        asyncio.run(run_single(scenario, binding, node))
    assert node.commands() == [ControlCommand.STAGE]


def test_a_repeated_result_packet_is_refused() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding, repeat_result=True)
    with pytest.raises(AssertionError, match="duplicate RESULT"):
        asyncio.run(run_single(scenario, binding, node))
    assert node.commands()[-1] == ControlCommand.ABORT


def test_an_inexact_result_is_an_arithmetic_error() -> None:
    scenario, binding = _operation()
    node = AnsweringNode(scenario, binding, inexact=True)
    with pytest.raises(ArithmeticError, match="ACCUMULATION_INEXACT"):
        asyncio.run(run_single(scenario, binding, node))


def test_a_replay_without_the_awaited_frame_times_out() -> None:
    scenario, binding = _operation()
    with pytest.raises(TimeoutError):
        asyncio.run(run_single(scenario, binding, ReplayTransport([])))
