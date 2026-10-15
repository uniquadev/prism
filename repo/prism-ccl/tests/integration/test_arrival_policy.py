"""Arrival arithmetic follows admitted contributions, with rounding after each addition."""

from __future__ import annotations

import struct

from prism_ccl.application.software import FaultPlan
from prism_ccl.domain.model import AccumulatorPolicy, ConcreteFormat, PartialWirePolicy, TypedVector
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode
from prism_ccl.wire.data import PacketClass
from prism_ccl.world import PrismWorld

INPUTS = {"r0": 0x3F800000, "r1": 0x33800000, "r2": 0xBF800000}


def _run(seed: int, policy: AccumulatorPolicy) -> tuple[int, tuple[str, ...]]:
    world = PrismWorld(manager="am")
    for index, name in enumerate(("am", "r0", "r1", "r2")):
        world.add_node(name, bytes([2, 0, 0, 0, 0, index]))
    world.add_prism("s", bytes([2, 0, 0, 0, 0, 4]))
    world.connect("am", 1, "s", 1)
    for index, rank in enumerate(("r0", "r1", "r2")):
        world.connect(rank, 1, "s", index + 2)
    tree = CollectiveTree(
        "s",
        (*tuple(LogicalNode(name, index) for index, name in enumerate(INPUTS)), LogicalNode("s")),
        tuple(
            LogicalEdge(name, "s", 1, index + 10, (name, "s")) for index, name in enumerate(INPUTS)
        ),
    )
    world.register_allreduce(
        "sum",
        tree=tree,
        vectors={
            index: TypedVector(ConcreteFormat.FP32, (INPUTS[name],))
            for index, name in enumerate(INPUTS)
        },
        management_paths={"s": ("am", "s")},
        accumulator=policy,
        partial_wire=PartialWirePolicy.FP32,
    )
    result = world.run("sum", fault=FaultPlan(seed=seed))
    order = tuple(
        event.source
        for event in result.frames
        if event.packet_class == PacketClass.DATA and event.destination == "s"
    )
    return result.rank_bits[0][0], order


def _independent_fp32_fold(order: tuple[str, ...]) -> int:
    running = 0.0
    for name in order:
        operand = struct.unpack("!f", INPUTS[name].to_bytes(4, "big"))[0]
        rounded = struct.pack("!f", running + operand)
        running = struct.unpack("!f", rounded)[0]
    return int.from_bytes(struct.pack("!f", running), "big")


def test_arrival_across_seeded_frame_orders() -> None:
    arrival_results: set[int] = set()
    observed_orders: set[tuple[str, ...]] = set()
    for seed in range(12):
        bits, order = _run(seed, AccumulatorPolicy.FP32_ARRIVAL)
        observed_orders.add(order)
        arrival_results.add(bits)
        assert bits == _independent_fp32_fold(order)
    assert len(observed_orders) > 1
    assert arrival_results == {0x00000000, 0x33800000}
