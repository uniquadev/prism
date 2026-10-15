"""Executable, reproducible SINGLE and hierarchical packet-world examples."""

from __future__ import annotations

from .application.reordering import ReorderPlan
from .application.software import FaultPlan, SoftwareResult
from .domain.model import ConcreteFormat, TypedVector
from .domain.topology import CollectiveTree, LogicalEdge, LogicalNode
from .wire.data import PacketClass
from .world import PrismWorld


def single_example(*, mtu: int = 1500) -> SoftwareResult:
    world = PrismWorld(manager="am")
    for index, name in enumerate(("am", "r0", "r1")):
        world.add_node(name, bytes([2, 0, 0, 0, 0, index]))
    world.add_prism("s", bytes([2, 0, 0, 0, 0, 3]))
    world.connect("am", 1, "s", 1, mtu=mtu)
    world.connect("r0", 1, "s", 2, mtu=mtu)
    world.connect("r1", 1, "s", 3, mtu=mtu)
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
        mtu=mtu,
    )
    return world.run("single")


def hierarchical_example(
    *,
    seed: int = 7,
    length: int = 500,
    fault: FaultPlan | None = None,
    reorder: ReorderPlan | None = None,
) -> SoftwareResult:
    world = PrismWorld(manager="am")
    for index, name in enumerate(("am", "r0", "r1", "r2", "r3")):
        world.add_node(name, bytes([2, 0, 0, 0, 0, index]))
    world.add_node("forward", bytes([2, 0, 0, 0, 0, 5]), forwarding_only=True)
    for index, name in enumerate(("a", "b", "root"), start=6):
        world.add_prism(name, bytes([2, 0, 0, 0, 0, index]))
    for left, left_port, right, right_port in (
        ("am", 1, "forward", 1),
        ("forward", 2, "a", 3),
        ("forward", 3, "b", 3),
        ("forward", 4, "root", 1),
        ("r0", 1, "a", 1),
        ("r1", 1, "a", 2),
        ("r2", 1, "b", 1),
        ("r3", 1, "b", 2),
    ):
        world.connect(left, left_port, right, right_port)
    tree = CollectiveTree(
        "root",
        (
            LogicalNode("r0", 0),
            LogicalNode("r1", 1),
            LogicalNode("r2", 2),
            LogicalNode("r3", 3),
            LogicalNode("a"),
            LogicalNode("b"),
            LogicalNode("root"),
        ),
        (
            LogicalEdge("r0", "a", 1, 10, ("r0", "a")),
            LogicalEdge("r1", "a", 1, 11, ("r1", "a")),
            LogicalEdge("r2", "b", 1, 10, ("r2", "b")),
            LogicalEdge("r3", "b", 1, 11, ("r3", "b")),
            LogicalEdge("a", "root", 12, 20, ("a", "forward", "root")),
            LogicalEdge("b", "root", 12, 21, ("b", "forward", "root")),
        ),
    )
    vectors = {
        0: TypedVector(ConcreteFormat.INT8, (1,) * length),
        1: TypedVector(
            ConcreteFormat.FP16,
            tuple(0x4000 if index % 2 == 0 else 0x3C01 for index in range(length)),
        ),
        2: TypedVector(
            ConcreteFormat.BF16,
            tuple(0x4080 if index % 2 == 0 else 0x0001 for index in range(length)),
        ),
        3: TypedVector(ConcreteFormat.FP32, (0x40C00000,) * length),
    }
    world.register_reduce(
        "hierarchical",
        tree=tree,
        vectors=vectors,
        destination_rank=1,
        management_paths={
            "a": ("am", "forward", "a"),
            "b": ("am", "forward", "b"),
            "root": ("am", "forward", "root"),
        },
    )
    fault = fault or FaultPlan(drop_once=frozenset({("r0", "a", PacketClass.DATA, 0)}), seed=seed)
    return world.run("hierarchical", fault=fault, reorder=reorder)


def main() -> None:
    single = single_example()
    hierarchy = hierarchical_example()
    print(f"SINGLE ranks={sorted(single.rank_values)} ticks={single.simulated_ticks}")
    print(f"HIERARCHY ranks={sorted(hierarchy.rank_values)} ticks={hierarchy.simulated_ticks}")


if __name__ == "__main__":
    main()
