"""Plot measured final-packet latency alongside EPIC's published reference."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from prism_experiments.artifacts import portable, repository_root

EPIC_NS = 230
EPIC_SOURCE = "https://arxiv.org/html/2605.18683v2#appendix.K"
FORMATS = ("INT8", "FP16", "BF16", "FP32")
POLICIES = ("KULISCH_FIXED", "FP32_ARRIVAL")


def load_run(
    path: Path, *, expected_stall_period: int = 0
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    device = json.loads((path / "device.json").read_text(encoding="utf-8"))
    samples = json.loads((path / "samples.json").read_text(encoding="utf-8"))
    if (
        manifest["status"] != "complete"
        or manifest.get("fp32_semantics") != "admission-online-v1"
        or manifest["ranks"] != 8
        or manifest["physical_ports"] != 1
        or manifest["clock_period_ns"] != 4
        or manifest["output_stall_period"] != expected_stall_period
        or device["parameters"]["NUM_PORTS"] != 1
        or len(samples) != len(manifest["cases"])
    ):
        raise ValueError(f"incomplete or incompatible RTL run: {path}")
    for sample, case in zip(samples, manifest["cases"], strict=True):
        if (
            any(sample[key] != value for key, value in case.items())
            or sample["oracle_mismatches"] != 0
            or sample["data_packets"] != 8
            or sample["output_stalled_beats"] < 0
            or (expected_stall_period == 0 and sample["output_stalled_beats"] != 0)
            or sample["final_packet_to_result_ns_at_4ns"]
            != 4 * sample["final_packet_to_result_cycles"]
            or sample["final_first_beat_to_result_cycles"]
            != sample["final_packet_to_result_cycles"]
            + sample["final_ingress_cycles"] - 1
        ):
            raise ValueError(f"invalid sample in {path}: {case}")
    return manifest, device, samples


def key(sample: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        sample["input_format"],
        sample["accumulator"],
        sample["workload"],
        sample["length"],
    )


def validated_samples(
    primary: Path, settle_check: Path
) -> tuple[dict[tuple[str, str, str, int], dict[str, Any]], str]:
    manifest, device, samples = load_run(primary)
    check_manifest, check_device, check_samples = load_run(settle_check)
    if (
        device["build_id"] != check_device["build_id"]
        or device["sources"] != check_device["sources"]
        or manifest["seed"] != check_manifest["seed"]
        or manifest["preload_settle_cycles"] == check_manifest["preload_settle_cycles"]
    ):
        raise ValueError("settle check must use identical RTL and seed, with a different wait")
    indexed = {key(sample): sample for sample in samples}
    if len(indexed) != len(samples):
        raise ValueError("duplicate primary measurement")
    for sample in check_samples:
        original = indexed.get(key(sample))
        if original is None:
            raise ValueError("settle check has an unmatched case")
        for field in (
            "final_packet_to_result_cycles",
            "final_first_beat_to_result_cycles",
            "final_ingress_cycles",
        ):
            if sample[field] != original[field]:
                raise ValueError(f"preload wait changes {field} for {key(sample)}")
    for length in (64, 256):
        for fmt in FORMATS:
            if (fmt, "KULISCH_FIXED", "ordinary", length) not in indexed:
                raise ValueError(f"missing Kulisch measurement: {fmt}, {length}")
        for policy in POLICIES[1:]:
            if ("FP32", policy, "ordinary", length) not in indexed:
                raise ValueError(f"missing FP32 measurement: {policy}, {length}")
    for length in (64, 256):
        fp16 = indexed[("FP16", "KULISCH_FIXED", "ordinary", length)]
        bf16 = indexed[("BF16", "KULISCH_FIXED", "ordinary", length)]
        if fp16["final_packet_to_result_cycles"] != bf16["final_packet_to_result_cycles"]:
            raise ValueError("FP16 and BF16 latency no longer overlaps")
    return indexed, device["build_id"]


def plot(
    samples: dict[tuple[str, str, str, int], dict[str, Any]],
    output: Path,
    primary: Path,
    settle_check: Path,
    build_id: str,
    data_output: Path,
    backpressure_check: Path | None = None,
) -> None:
    import matplotlib.pyplot as plt

    cases = (
        ("INT8", "KULISCH_FIXED", "INT8 | Kulisch"),
        ("FP16", "KULISCH_FIXED", "FP16/BF16 | Kulisch"),
        ("FP32", "KULISCH_FIXED", "FP32 | Kulisch"),
        ("FP32", "FP32_ARRIVAL", "FP32 | FP32 arrival"),
    )
    output.mkdir(parents=True, exist_ok=True)
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 8.5, "pdf.fonttype": 42}):
        figure, axis = plt.subplots(figsize=(5.9, 2.8), layout="constrained")
        for row, (fmt, policy, _label) in enumerate(cases):
            position = len(cases) - 1 - row
            short = samples[(fmt, policy, "ordinary", 64)]
            long = samples[(fmt, policy, "ordinary", 256)]
            left = short["final_packet_to_result_ns_at_4ns"]
            right = long["final_packet_to_result_ns_at_4ns"]
            axis.hlines(position, 0, right, color="#AAB7C1", lw=1.2)
            axis.scatter(left, position, s=43, color="#245A7A", zorder=3,
                         label="64 elements" if row == 0 else None)
            axis.scatter(right, position, s=49, facecolors="white", edgecolors="#245A7A",
                         marker="s", zorder=3, label="256 elements" if row == 0 else None)
            axis.annotate(str(left), (left, position), xytext=(-6, 8 if row == 3 else -13),
                          textcoords="offset points", ha="right", fontsize=7.5)
            axis.annotate(str(right), (right, position), xytext=(5, 5),
                          textcoords="offset points", fontsize=7.5)
        axis.axvline(EPIC_NS, color="#B34140", ls="--", lw=1.4,
                     label="EPIC Mode-II, ~230 ns")
        axis.set_yticks(range(len(cases)), [label for *_, label in reversed(cases)])
        axis.set_xlim(0, 480)
        axis.set_xlabel("Final DATA to first RESULT (ns at simulated 4 ns)")
        axis.grid(axis="x", color="#E4E8EB", lw=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.legend(frameon=False, fontsize=7, loc="upper right")
        figure.savefig(output / "final_contribution_latency_8rank.pdf", bbox_inches="tight")
        figure.savefig(output / "final_contribution_latency_8rank.svg", bbox_inches="tight")
        plt.close(figure)
    root = repository_root(Path(__file__))
    provenance = {
        "primary_run": portable(primary, root),
        "settle_check_run": portable(settle_check, root),
        "backpressure_check_run": (
            portable(backpressure_check, root) if backpressure_check is not None else None
        ),
        "rtl_build_id": build_id,
        "prism_metric": "last accepted beat of final DATA to first accepted RESULT beat",
        "clock_period_ns": 4,
        "epic_reference_ns_approx": EPIC_NS,
        "epic_source": EPIC_SOURCE,
        "epic_configuration": "Mode-II, eight ranks, Intel Agilex, RTL simulation",
        "comparison_limit": (
            "EPIC gives no payload size or element count for the 230 ns latency and does "
            "not specify which beat marks final-packet arrival. FPGA and timing closure "
            "differ. The one-port PRISM datapath is distinct from its "
            "two-port wide path. EPIC's 250 MHz result refers to a separate VU13P design."
        ),
    }
    (output / "final_contribution_latency_8rank_sources.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    archived_runs = [("baseline", primary), ("settle_check", settle_check)]
    if backpressure_check is not None:
        archived_runs.append(("backpressure_check", backpressure_check))
    for name, run in archived_runs:
        destination = data_output / name
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ("manifest.json", "device.json", "samples.json", "samples.csv"):
            shutil.copy2(run / filename, destination / filename)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--settle-check", type=Path, required=True)
    parser.add_argument("--backpressure-check", type=Path)
    experiment = Path(__file__).resolve().parents[2]
    parser.add_argument("--output", type=Path, default=experiment / "results/figures")
    parser.add_argument("--data-output", type=Path, default=experiment / "results/data")
    args = parser.parse_args()
    samples, build_id = validated_samples(args.run, args.settle_check)
    if args.backpressure_check is not None:
        stress_manifest = json.loads(
            (args.backpressure_check / "manifest.json").read_text(encoding="utf-8")
        )
        stall_period = stress_manifest["output_stall_period"]
        if stall_period < 2:
            raise ValueError("backpressure check must actually impose output stalls")
        _, stress_device, stress_samples = load_run(
            args.backpressure_check, expected_stall_period=stall_period
        )
        baseline_device = json.loads((args.run / "device.json").read_text(encoding="utf-8"))
        if (
            stress_device["build_id"] != build_id
            or stress_device["sources"] != baseline_device["sources"]
            or not stress_samples
            or stress_manifest["seed"]
            != json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))["seed"]
            or any(key(row) not in samples or row["output_stalled_beats"] <= 0
                   for row in stress_samples)
        ):
            raise ValueError("backpressure check does not match the RTL baseline")
    plot(
        samples, args.output, args.run, args.settle_check, build_id, args.data_output,
        args.backpressure_check,
    )
    print(f"Figure: {args.output / 'final_contribution_latency_8rank.pdf'}")
    print(f"Data: {args.data_output}")


if __name__ == "__main__":
    main()
