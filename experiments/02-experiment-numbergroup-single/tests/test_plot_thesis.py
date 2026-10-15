"""Protect the comparisons used in the thesis figures."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "src/numbergroup_single/plot_thesis.py"
spec = importlib.util.spec_from_file_location("plot_thesis", SCRIPT)
assert spec and spec.loader
plot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plot
spec.loader.exec_module(plot)


def observation(
    result_bytes: int,
    result_cycles: int,
    *,
    settle_cycles: int = 0,
    final_latency: int = 33,
) -> plot.Observation:
    return plot.Observation(
        Path("synthetic"),
        {
            "workload": "ordinary",
            "input_format": "FP32",
            "output_format": "AUTO",
            "elements_per_rank": 64,
            "collective": "allreduce",
            "preload_first_rank": settle_cycles != 0,
            "preload_settle_cycles": settle_cycles,
        },
        {
            "accumulator": "KULISCH_FIXED",
            "frame_bytes": {"RESULT": result_bytes},
            "result_output_window_cycles": result_cycles,
            "source_bits": [[1, 2], [3, 4]],
            "final_contribution_latency_cycles": final_latency,
            "final_contribution_ingress_cycles": 5,
        },
    )


def test_result_frame_rate_uses_frame_bytes_and_output_window() -> None:
    auto = observation(8672, 157)
    fixed_fp32 = observation(34208, 563)
    fixed = observation(351232, 5653)
    assert plot.result_frame_gbps(auto) == pytest.approx(110.4713375796)
    assert plot.result_frame_gbps(fixed_fp32) == pytest.approx(121.5204262877)
    assert plot.result_frame_gbps(fixed) == pytest.approx(124.2639306563)


def test_result_saving_is_absolute_bytes_not_per_element() -> None:
    saved, percent = plot.result_saving(observation(4388, 72), observation(175616, 2816))
    assert saved == 171228
    assert percent == pytest.approx(97.5013666181)
    with pytest.raises(ValueError, match="no larger"):
        plot.result_saving(observation(175616, 2816), observation(4388, 72))


def test_single_group_cases_fill_the_same_data_frame_budget() -> None:
    assert plot.full_packet_group_capacity("FP16") == 726
    assert plot.full_packet_group_capacity("BF16") == 726
    assert plot.full_packet_group_capacity("FP32") == 363
    assert plot.ONE_WIDE_CASES == (("FP16", 726), ("FP32", 363))


def test_preload_runs_remain_distinct_and_latency_must_agree() -> None:
    first = observation(248, 15, settle_cycles=64)
    second = observation(248, 15, settle_cycles=128)
    assert first.key != second.key
    plot.verify_preload(first, second)
    with pytest.raises(ValueError, match="depends on preload"):
        plot.verify_preload(first, observation(248, 15, settle_cycles=128, final_latency=34))
