from __future__ import annotations

import pytest

from prism_ccl.application.reordering import ReorderPlan, ReorderRule
from prism_ccl.wire.data import PacketClass


def test_default_is_ordered_and_seed_is_repeatable() -> None:
    packets = list(range(12))
    assert (
        ReorderPlan().arrange(
            packets, source="r0", destination="s", packet_class=PacketClass.DATA, stream_id=1
        )
        == packets
    )
    plan = ReorderPlan.data(1, window_packets=4, seed=7)
    first = plan.arrange(
        packets, source="r0", destination="s", packet_class=PacketClass.DATA, stream_id=1
    )
    assert first != packets
    assert first == plan.arrange(
        packets, source="r0", destination="s", packet_class=PacketClass.DATA, stream_id=1
    )
    assert all(abs(index - value) <= 3 for index, value in enumerate(first))
    assert (
        plan.arrange(
            packets, source="r0", destination="s", packet_class=PacketClass.RESULT, stream_id=1
        )
        == packets
    )


def test_named_edges_do_not_affect_other_streams() -> None:
    plan = ReorderPlan.data(1, seed=11, edges=(("r0", "s"),))
    packets = list(range(8))
    assert (
        plan.arrange(
            packets, source="r1", destination="s", packet_class=PacketClass.DATA, stream_id=1
        )
        == packets
    )
    assert (
        plan.arrange(
            packets, source="r0", destination="s", packet_class=PacketClass.DATA, stream_id=1
        )
        != packets
    )


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan")])
def test_invalid_probability(probability: float) -> None:
    with pytest.raises(ValueError, match="probability"):
        ReorderPlan.data(probability)


def test_invalid_window_and_duplicate_rule() -> None:
    with pytest.raises(ValueError, match="window"):
        ReorderPlan.data(0.5, window_packets=1)
    rule = ReorderRule("r0", "s", PacketClass.DATA, 0.5)
    with pytest.raises(ValueError, match="more than one"):
        ReorderPlan(rules=(rule, rule))
    with pytest.raises(ValueError, match="cannot be empty"):
        ReorderPlan.data(0.5, edges=())


def test_reorder_window_cannot_exceed_receive_capacity() -> None:
    ReorderPlan.data(1, seed=7).require_window_capacity(2)
    with pytest.raises(ValueError, match="receive capacity 2"):
        ReorderPlan.data(1, window_packets=4, seed=7).require_window_capacity(2)
    ReorderPlan.data(0, window_packets=4).require_window_capacity(2)
