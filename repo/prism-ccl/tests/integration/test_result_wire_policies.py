"""RESULT wire selection does not change the selected arithmetic."""

from fractions import Fraction

import pytest

from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import ExactValue
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode
from prism_ccl.wire.data import PacketClass, decode_data_frame
from prism_ccl.world import PrismWorld


def _run(accumulator: AccumulatorPolicy, output: ResultWirePolicy):
    world = PrismWorld(manager="am")
    for index, name in enumerate(("am", "r0", "r1", "s")):
        mac = bytes((2, 0, 0, 0, 0, index))
        if name == "s":
            world.add_prism(name, mac)
        else:
            world.add_node(name, mac)
    world.connect("am", 1, "s", 1)
    world.connect("r0", 1, "s", 2)
    world.connect("r1", 1, "s", 3)
    tree = CollectiveTree(
        "s",
        (LogicalNode("r0", 0), LogicalNode("r1", 1), LogicalNode("s")),
        (LogicalEdge("r0", "s", 1, 10, ("r0", "s")), LogicalEdge("r1", "s", 1, 11, ("r1", "s"))),
    )
    world.register_reduce(
        "sum",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000, 0x3F800000)),
            1: TypedVector(ConcreteFormat.FP32, (0, 0x33800000)),
        },
        destination_rank=0,
        management_paths={"s": ("am", "s")},
        accumulator=accumulator,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=output,
    )
    return world.run("sum")


@pytest.mark.parametrize("output", (ResultWirePolicy.KULISCH, ResultWirePolicy.AUTO))
def test_exact_result_reaches_rank_without_fp32_rounding(output: ResultWirePolicy) -> None:
    result = _run(AccumulatorPolicy.KULISCH_FIXED, output)
    assert result.rank_bits is None
    assert result.rank_values == {
        0: (
            ExactValue("finite", False, Fraction(1)),
            ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24)),
        )
    }
    formats = tuple(group.format for group in result.rank_groups[0])
    assert formats == (
        (ConcreteFormat.KULISCH,)
        if output == ResultWirePolicy.KULISCH
        else (ConcreteFormat.INT8, ConcreteFormat.KULISCH)
    )
    frame = next(
        event.frame
        for event in result.frames
        if event.packet_class == PacketClass.RESULT and event.destination == "r0"
    )
    packet = decode_data_frame(frame, mtu=1500, kulisch_bits=279)
    assert tuple(group.format for group in packet.groups) == formats


def test_auto_transports_the_already_rounded_fp32_result() -> None:
    result = _run(AccumulatorPolicy.FP32_ARRIVAL, ResultWirePolicy.AUTO)
    assert result.rank_bits is None
    assert result.rank_values[0] == (
        ExactValue("finite", False, Fraction(1)),
        ExactValue("finite", False, Fraction(1)),
    )
    assert tuple(group.format for group in result.rank_groups[0]) == (ConcreteFormat.INT8,)
