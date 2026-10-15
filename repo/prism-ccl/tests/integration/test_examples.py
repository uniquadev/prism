"""Public examples checked against independent rational expectations."""

from __future__ import annotations

from fractions import Fraction

import pytest

from prism_ccl.application.software import FaultPlan, SimulatedTimeout
from prism_ccl.examples import hierarchical_example, single_example
from prism_ccl.wire.data import PacketClass


def test_single_public_example() -> None:
    result = single_example()
    assert result.rank_bits == {0: (0x40400000, 0x40A00000), 1: (0x40400000, 0x40A00000)}
    assert result.released_contexts
    assert any(event.packet_class == PacketClass.CONTROL for event in result.frames)
    assert any(event.packet_class == PacketClass.DATA for event in result.frames)
    assert any(event.packet_class == PacketClass.RESULT for event in result.frames)
    assert any(event.packet_class == PacketClass.PROGRESS for event in result.frames)


def test_minimum_mtu_negotiates_paginated_capabilities() -> None:
    result = single_example(mtu=576)
    assert result.rank_bits[0] == (0x40400000, 0x40A00000)
    responses = [
        event
        for event in result.frames
        if event.source == "s"
        and event.destination == "am"
        and event.packet_class == PacketClass.CONTROL
    ]
    assert len(responses) >= 3
    assert all(len(event.frame) - 14 <= 576 for event in responses)


@pytest.mark.parametrize("seed", [7, 99])
def test_hierarchical_public_example_against_rational_oracle(seed: int) -> None:
    result = hierarchical_example(seed=seed)
    assert result.released_contexts
    assert set(result.rank_bits) == {1}
    assert result.rank_bits[1] == (0x41500000, 0x41000400) * 250
    assert result.partials["a"][0].value == Fraction(3)
    assert result.partials["b"][0].value == Fraction(10)
    assert result.partials["root"][0].value == Fraction(13)
    assert result.partials["a"][1].value == Fraction(2) + Fraction(1, 1024)
    assert result.partials["b"][1].value == Fraction(6) + Fraction(1, 1 << 133)
    assert result.partials["root"][1].value == (
        Fraction(8) + Fraction(1, 1024) + Fraction(1, 1 << 133)
    )
    assert any("forward" in event.path[1:-1] for event in result.frames)
    attempts = [
        event
        for event in result.frames
        if event.source == "r0"
        and event.destination == "a"
        and event.packet_class == PacketClass.DATA
        and event.packet_id == 0
    ]
    assert len(attempts) == 2
    assert not attempts[0].delivered and attempts[1].delivered
    assert attempts[0].frame == attempts[1].frame


def test_simulated_timeout_is_not_host_wall_time() -> None:
    with pytest.raises(SimulatedTimeout, match="timed out"):
        hierarchical_example(
            length=8,
            fault=FaultPlan(
                drop_always=frozenset({("r0", "a", PacketClass.DATA, 0)}),
                retry_ticks=3,
                maximum_retries=2,
            ),
        )


def test_lost_progress_retries_identical_data_without_second_application() -> None:
    result = hierarchical_example(
        length=8,
        fault=FaultPlan(drop_once=frozenset({("a", "r0", PacketClass.PROGRESS, 0)})),
    )
    assert result.rank_bits[1] == (0x41500000, 0x41000400) * 4
    sends = [
        event
        for event in result.frames
        if event.source == "r0"
        and event.destination == "a"
        and event.packet_class == PacketClass.DATA
        and event.packet_id == 0
    ]
    assert len(sends) == 2 and sends[0].frame == sends[1].frame
