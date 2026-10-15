"""Small executable PrismWorld scenario bound to the compiled SINGLE DUT."""

from __future__ import annotations

from typing import Any

from prism_ccl.domain.capabilities import single_rtl_capabilities
from prism_ccl.domain.model import ConcreteFormat, TypedVector
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode, PrismCapacity
from prism_ccl.world import PrismWorld

from .world import CocotbResult, CocotbSingleBackend


def single_world() -> tuple[PrismWorld, CollectiveTree]:
    world = PrismWorld(manager="am", capabilities=single_rtl_capabilities())
    for number, name in enumerate(("am", "r0", "r1")):
        world.add_node(name, bytes((2, 0, 0, 0, 0, number)))
    world.add_node("forward", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_prism(
        "s",
        bytes.fromhex("020000000003"),
        capacity=PrismCapacity(2, 2, 2, 4096, True, False),
    )
    for left, left_port, right, right_port in (
        ("am", 1, "forward", 1),
        ("r0", 1, "forward", 2),
        ("forward", 3, "s", 0),
        ("r1", 1, "s", 1),
    ):
        world.connect(left, left_port, right, right_port)
    tree = CollectiveTree(
        "s",
        (LogicalNode("r0", 0), LogicalNode("r1", 1), LogicalNode("s")),
        (
            LogicalEdge("r0", "s", 1, 10, ("r0", "forward", "s")),
            LogicalEdge("r1", "s", 1, 11, ("r1", "s")),
        ),
    )
    return world, tree


def shared_port_world() -> tuple[PrismWorld, CollectiveTree]:
    """Three rank endpoints; two share the forwarding path into physical port 0."""
    world = PrismWorld(manager="am", capabilities=single_rtl_capabilities())
    for number, name in enumerate(("am", "r0", "r1")):
        world.add_node(name, bytes((2, 0, 0, 0, 0, number)))
    world.add_node("forward", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_node("r2", bytes.fromhex("020000000005"))
    world.add_prism(
        "s",
        bytes.fromhex("020000000003"),
        capacity=PrismCapacity(3, 3, 3, 8192, True, False),
    )
    for left, left_port, right, right_port in (
        ("am", 1, "forward", 1),
        ("r0", 1, "forward", 2),
        ("forward", 3, "s", 0),
        ("r1", 1, "s", 1),
        ("r2", 1, "forward", 4),
    ):
        world.connect(left, left_port, right, right_port)
    tree = CollectiveTree(
        "s",
        (
            LogicalNode("r0", 0),
            LogicalNode("r1", 1),
            LogicalNode("r2", 2),
            LogicalNode("s"),
        ),
        (
            LogicalEdge("r0", "s", 1, 10, ("r0", "forward", "s")),
            LogicalEdge("r1", "s", 1, 11, ("r1", "s")),
            LogicalEdge("r2", "s", 1, 12, ("r2", "forward", "s")),
        ),
    )
    return world, tree


async def single_example(dut: Any) -> CocotbResult:
    world, tree = single_world()
    world.register_allreduce(
        "demo",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000, 0x40000000)),
            1: TypedVector(ConcreteFormat.FP32, (0x40000000, 0x40400000)),
        },
        management_paths={"s": ("am", "forward", "s")},
    )
    return await world.run_async("demo", backend=CocotbSingleBackend(dut, prism_name="s"))


async def reduce_example(dut: Any) -> CocotbResult:
    world, tree = single_world()
    world.register_reduce(
        "reduce",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP16, (0x3C00, 0x4000)),
            1: TypedVector(ConcreteFormat.BF16, (0x4000, 0x4040)),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
    )
    return await world.run_async("reduce", backend=CocotbSingleBackend(dut, prism_name="s"))
