from __future__ import annotations

import asyncio
from dataclasses import replace
from fractions import Fraction

import pytest

from prism_ccl.application.node import NodeReceiver
from prism_ccl.application.reordering import ReorderPlan
from prism_ccl.application.software import FaultPlan, SimulatedTimeout
from prism_ccl.domain.capabilities import CapabilityRecord, software_capabilities
from prism_ccl.domain.model import ConcreteFormat, ResultWirePolicy, TypedVector
from prism_ccl.domain.numbers import ExactValue
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode
from prism_ccl.examples import hierarchical_example
from prism_ccl.wire.control import ContextRecord, ControlCommand
from prism_ccl.wire.data import PacketClass
from prism_ccl.world import PrismWorld, SoftwareWorldBackend


def _single() -> PrismWorld:
    world = PrismWorld(manager="am")
    for index, name in enumerate(("am", "r0", "r1")):
        world.add_node(name, bytes([2, 0, 0, 0, 0, index]))
    world.add_prism("s", bytes([2, 0, 0, 0, 0, 3]))
    world.connect("am", 1, "s", 1)
    world.connect("r0", 1, "s", 2)
    world.connect("r1", 1, "s", 3)
    tree = CollectiveTree(
        "s",
        (LogicalNode("r0", 0), LogicalNode("r1", 1), LogicalNode("s")),
        (
            LogicalEdge("r0", "s", 1, 10, ("r0", "s")),
            LogicalEdge("r1", "s", 1, 11, ("r1", "s")),
        ),
    )
    world.register_allreduce(
        "single",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000, 0x40000000)),
            1: TypedVector(ConcreteFormat.FP32, (0x40000000, 0x40400000)),
        },
        management_paths={"s": ("am", "s")},
    )
    return world


def test_single_world_crosses_binary_frames_and_releases_context() -> None:
    result = _single().run("single")
    assert result.rank_bits == {
        0: (0x40400000, 0x40A00000),
        1: (0x40400000, 0x40A00000),
    }
    assert result.released_contexts
    assert result.simulated_ticks > 0
    assert len(result.frames) >= 10


def test_software_backend_uses_the_explicit_async_contract() -> None:
    world = _single()
    result = asyncio.run(
        world.run_async("single", backend=SoftwareWorldBackend(world.capabilities))
    )
    assert result.rank_bits == {0: (0x40400000, 0x40A00000), 1: (0x40400000, 0x40A00000)}
    assert result.released_contexts


def test_reordered_data_is_applied_once_and_result_matches_ordered_run() -> None:
    baseline = hierarchical_example(length=2000, fault=FaultPlan(seed=9))
    reordered = hierarchical_example(
        length=2000,
        fault=FaultPlan(seed=9),
        reorder=ReorderPlan.data(1, window_packets=4, seed=9, edges=(("r3", "b"),)),
    )
    assert reordered.rank_bits == baseline.rank_bits
    assert reordered.released_contexts
    packets = [
        event.packet_id
        for event in reordered.frames
        if event.source == "r3"
        and event.destination == "b"
        and event.packet_class == PacketClass.DATA
        and event.delivered
    ]
    assert packets != sorted(packets)


def test_stage_ack_loss_retries_identical_record_and_releases() -> None:
    result = _single().run(
        "single",
        fault=FaultPlan(drop_once=frozenset({("s", "am", PacketClass.CONTROL, 1)})),
    )
    stages = [
        event
        for event in result.frames
        if event.source == "am"
        and event.destination == "s"
        and event.packet_id == ControlCommand.STAGE
    ]
    assert len(stages) == 2
    assert stages[0].frame == stages[1].frame
    record = ContextRecord.unpack(stages[0].frame[48:])
    assert tuple(binding.local_port for binding in record.bindings) == (2, 3)
    assert tuple(binding.rank_id for binding in record.bindings) == (0, 1)
    assert tuple(binding.peer_endpoint for binding in record.bindings) == (1, 1)
    assert result.released_contexts


def test_commit_timeout_rolls_back_staged_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[NodeReceiver] = []
    original = NodeReceiver.handle_control

    def capture(self: NodeReceiver, frame: bytes, *, ingress_port: int, mtu: int):
        observed.append(self)
        return original(self, frame, ingress_port=ingress_port, mtu=mtu)

    monkeypatch.setattr(NodeReceiver, "handle_control", capture)
    world = _single()
    with pytest.raises(SimulatedTimeout, match="COMMIT"):
        world.run(
            "single",
            fault=FaultPlan(drop_always=frozenset({("am", "s", PacketClass.CONTROL, 2)})),
        )
    assert observed and all(not node.contexts and node.reserved_bytes == 0 for node in observed)


def test_failed_rollback_is_reported_not_claimed_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[NodeReceiver] = []
    original = NodeReceiver.handle_control

    def capture(self: NodeReceiver, frame: bytes, *, ingress_port: int, mtu: int):
        observed.append(self)
        return original(self, frame, ingress_port=ingress_port, mtu=mtu)

    monkeypatch.setattr(NodeReceiver, "handle_control", capture)
    with pytest.raises(RuntimeError, match="rollback incomplete"):
        _single().run(
            "single",
            fault=FaultPlan(
                drop_always=frozenset(
                    {
                        ("am", "s", PacketClass.CONTROL, 2),
                        ("am", "s", PacketClass.CONTROL, 6),
                    }
                )
            ),
        )
    assert observed and any(node.reserved_bytes > 0 for node in observed)


def test_operation_id_reuse_requires_new_generation_after_release() -> None:
    world = _single()
    original = world._scenarios["single"]
    assert world.run("single").released_contexts
    with pytest.raises(ValueError, match="already attempted"):
        world.run("single")
    with pytest.raises(ValueError, match="higher generation"):
        world.register_allreduce(
            "stale",
            tree=original.tree,
            vectors=original.vectors,
            management_paths=original.management_paths,
            key=original.config.key,
        )
    world.register_allreduce(
        "next",
        tree=original.tree,
        vectors=original.vectors,
        management_paths=original.management_paths,
        key=replace(original.config.key, operation_generation=1),
    )
    assert world.run("next").rank_bits[0] == (0x40400000, 0x40A00000)


@pytest.mark.parametrize("record", software_capabilities().records)
def test_every_advertised_arithmetic_tuple_crosses_frames(record: CapabilityRecord) -> None:
    native = {
        ConcreteFormat.INT8: (1, 2, 3),
        ConcreteFormat.FP16: (0x3C00, 0x4000, 0x4200),
        ConcreteFormat.BF16: (0x3F80, 0x4000, 0x4040),
        ConcreteFormat.FP32: (0x3F800000, 0x40000000, 0x40400000),
    }
    world = _single()
    baseline = world._scenarios["single"]
    one, two, _ = native[record.input_format]
    world.register_allreduce(
        "advertised",
        tree=baseline.tree,
        vectors={
            0: TypedVector(record.input_format, (one,)),
            1: TypedVector(record.input_format, (two,)),
        },
        management_paths=baseline.management_paths,
        accumulator=record.accumulator,
        partial_wire=record.partial_wire,
        output_format=record.output_format,
    )
    result = world.run("advertised")
    expected = (ExactValue("finite", False, Fraction(3)),)
    assert result.rank_values == {0: expected, 1: expected}
    if record.output_format in (ResultWirePolicy.AUTO, ResultWirePolicy.KULISCH):
        assert result.rank_bits is None
    else:
        fmt = ConcreteFormat(int(record.output_format))
        assert result.rank_bits == {0: (native[fmt][2],), 1: (native[fmt][2],)}
    assert result.released_contexts
