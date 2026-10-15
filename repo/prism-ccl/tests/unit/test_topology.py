from __future__ import annotations

from dataclasses import replace

import pytest

from prism_ccl.domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationConfig,
    OperationKey,
    PartialWirePolicy,
)
from prism_ccl.domain.topology import (
    CollectiveTree,
    LogicalEdge,
    LogicalNode,
    PhysicalLink,
    PhysicalNetwork,
    PhysicalNode,
    PrismCapacity,
)


def _scenario(shared_demux: bool = True) -> tuple[PhysicalNetwork, CollectiveTree, OperationConfig]:
    network = PhysicalNetwork()
    for index, name in enumerate(("r0", "r1", "r2", "r3", "a", "b", "root", "forward")):
        capacity = (
            PrismCapacity(4, 8, 8, 8192, shared_demux, True) if name in {"a", "b", "root"} else None
        )
        network.add_node(
            PhysicalNode(name, bytes([2, 0, 0, 0, 0, index]), name == "forward"),
            capacity,
        )
    for left, left_port, right, right_port in (
        ("r0", 1, "a", 1),
        ("r1", 1, "a", 2),
        ("r2", 1, "b", 1),
        ("r3", 1, "b", 2),
        ("a", 3, "forward", 1),
        ("b", 3, "forward", 2),
        ("forward", 3, "root", 1),
    ):
        network.add_link(PhysicalLink(left, left_port, right, right_port, 1500))
    tree = CollectiveTree(
        "root",
        (
            *(LogicalNode(name, index) for index, name in enumerate(("r0", "r1", "r2", "r3"))),
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
    config = OperationConfig(
        OperationKey(1, 2, 3, 4, 5),
        CollectiveKind.REDUCE,
        (0, 1, 2, 3),
        16,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.AUTO,
        ConcreteFormat.FP32,
        1,
        4,
        280,
    )
    return network, tree, config


def test_two_intermediates_and_forwarding_only_physical_node() -> None:
    network, tree, config = _scenario()
    contexts = {context.node: context for context in tree.compile(network, config)}
    assert contexts["root"].role == "ROOT"
    assert contexts["root"].children == ("a", "b")
    assert contexts["root"].result_destinations == ("a",)
    assert contexts["a"].result_destinations == ("r1",)
    assert contexts["b"].result_destinations == ()
    assert contexts["root"].original_terms == 4
    assert "forward" not in contexts


def test_shared_port_needs_explicit_demultiplexing() -> None:
    network, tree, config = _scenario(shared_demux=False)
    with pytest.raises(ValueError, match="demultiplexing"):
        tree.compile(network, config)


def test_tree_rejects_missing_path_and_incorrect_rank_membership() -> None:
    network, tree, config = _scenario()
    wrong_path = replace(tree.edges[-1], physical_path=("b", "root"))
    with pytest.raises(ValueError, match="viable"):
        replace(tree, edges=(*tree.edges[:-1], wrong_path)).compile(network, config)
    with pytest.raises(ValueError, match="membership"):
        tree.compile(network, replace(config, ranks=(0, 1, 2)))
