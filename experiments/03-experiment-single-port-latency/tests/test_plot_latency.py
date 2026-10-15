"""Reject incomplete or non-comparable latency measurements before plotting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.single_port_latency.plot_latency import load_run, validated_samples


def make_run(
    path: Path, *, settle: int, build_id: str = "rtl-a", stall_period: int = 0
) -> Path:
    path.mkdir()
    cases = [
        {"input_format": fmt, "accumulator": "KULISCH_FIXED", "workload": "ordinary",
         "length": length}
        for length in (64, 256)
        for fmt in ("INT8", "FP16", "BF16", "FP32")
    ]
    cases += [
        {"input_format": "FP32", "accumulator": policy, "workload": "ordinary",
         "length": length}
        for length in (64, 256)
        for policy in ("FP32_ARRIVAL",)
    ]
    samples = []
    for case in cases:
        cycles = 47 if case["accumulator"] == "KULISCH_FIXED" else 70
        ingress = 3 if case["length"] == 64 else 9
        samples.append({
            **case,
            "final_packet_to_result_cycles": cycles,
            "final_packet_to_result_ns_at_4ns": 4 * cycles,
            "final_first_beat_to_result_cycles": cycles + ingress - 1,
            "final_ingress_cycles": ingress,
            "oracle_mismatches": 0,
            "data_packets": 8,
            "output_stalled_beats": 9 if stall_period else 0,
        })
    (path / "manifest.json").write_text(json.dumps({
        "fp32_semantics": "admission-online-v1", "status": "complete", "ranks": 8, "physical_ports": 1,
        "clock_period_ns": 4, "output_stall_period": stall_period,
        "seed": 7, "preload_settle_cycles": settle, "cases": cases,
    }), encoding="utf-8")
    (path / "device.json").write_text(json.dumps({
        "build_id": build_id, "parameters": {"NUM_PORTS": 1},
        "sources": {"core.sv": "source-hash"},
    }), encoding="utf-8")
    (path / "samples.json").write_text(json.dumps(samples), encoding="utf-8")
    return path


def test_accepts_same_rtl_with_an_independent_preload_wait(tmp_path: Path) -> None:
    primary = make_run(tmp_path / "primary", settle=128)
    check = make_run(tmp_path / "check", settle=256)
    samples, build_id = validated_samples(primary, check)
    assert build_id == "rtl-a"
    assert len(samples) == 10


def test_rejects_changed_rtl(tmp_path: Path) -> None:
    primary = make_run(tmp_path / "primary", settle=128)
    check = make_run(tmp_path / "check", settle=256, build_id="rtl-b")
    with pytest.raises(ValueError, match="identical RTL"):
        validated_samples(primary, check)


def test_rejects_preload_dependent_latency(tmp_path: Path) -> None:
    primary = make_run(tmp_path / "primary", settle=128)
    check = make_run(tmp_path / "check", settle=256)
    path = check / "samples.json"
    samples = json.loads(path.read_text(encoding="utf-8"))
    samples[0]["final_packet_to_result_cycles"] += 1
    samples[0]["final_packet_to_result_ns_at_4ns"] += 4
    samples[0]["final_first_beat_to_result_cycles"] += 1
    path.write_text(json.dumps(samples), encoding="utf-8")
    with pytest.raises(ValueError, match="preload wait changes"):
        validated_samples(primary, check)


def test_keeps_backpressure_run_out_of_baseline(tmp_path: Path) -> None:
    stress = make_run(tmp_path / "stress", settle=128, stall_period=5)
    with pytest.raises(ValueError, match="incomplete or incompatible"):
        load_run(stress)
    _, _, samples = load_run(stress, expected_stall_period=5)
    assert all(sample["output_stalled_beats"] > 0 for sample in samples)
