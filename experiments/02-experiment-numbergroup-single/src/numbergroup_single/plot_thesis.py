"""Rebuild the SINGLE thesis figures from source-matched cycle-exact runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
from matplotlib.figure import Figure

matplotlib.use("Agg")

HERE = Path(__file__).resolve().parents[2]
ROOT = HERE.parents[1]
BUILD_ID = "dfd75793798e565a0ae27fc66819eb589f629afe01f31b7415f4cad99d887758"
FORMATS = ("INT8", "FP16", "BF16", "FP32")
WIDTHS = {"INT8": 8, "FP16": 16, "BF16": 16, "FP32": 32}
LENGTHS = (64, 256, 1024, 4096)
MTU = 1500
ONE_WIDE_CASES = (("FP16", 726), ("FP32", 363))
SETTLE_CYCLES = (64, 128)
CLOCK_NS = 4


@dataclass(frozen=True)
class Observation:
    path: Path
    manifest: dict[str, Any]
    sample: dict[str, Any]

    @property
    def key(self) -> tuple[str, str, str, int, str, str, int]:
        return (
            self.manifest["workload"],
            self.manifest["input_format"],
            self.manifest["output_format"],
            self.manifest["elements_per_rank"],
            self.manifest["collective"],
            self.sample["accumulator"],
            self.manifest["preload_settle_cycles"]
            if self.manifest.get("preload_first_rank", False)
            else 0,
        )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measurement_sources(row: Observation) -> dict[str, str]:
    return {
        name: digest
        for name, digest in row.manifest["provenance"]["sources"].items()
        if name.startswith(("repo/prism-ccl/src/", "repo/prism-hdl/verification/ccl/"))
        or name
        in {
            "experiments/02-experiment-numbergroup-single/experiment.py",
            "experiments/02-experiment-numbergroup-single/rtl_callback.py",
            "experiments/02-experiment-numbergroup-single/workloads.py",
            "experiments/02-experiment-numbergroup-single/src/numbergroup_single/rtl_callback.py",
            "experiments/02-experiment-numbergroup-single/src/numbergroup_single/workloads.py",
        }
    }


def observations(
    parent: Path, build_id: str
) -> dict[tuple[str, str, str, int, str, str, int], Observation]:
    selected: dict[tuple[str, str, str, int, str, str, int], Observation] = {}
    source_hashes: dict[str, str] | None = None
    for manifest_path in sorted(parent.glob("*/manifest.json")):
        run = manifest_path.parent
        device_path = run / "device.json"
        if not device_path.is_file():
            continue
        device = json.loads(device_path.read_text(encoding="utf-8"))
        if device["build_id"] != build_id:
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["status"] != "complete" and str(manifest.get("error", "")).startswith(
            "build in use:"
        ):
            continue
        if manifest["status"] != "complete":
            raise ValueError(f"failed or unfinished run on selected build: {run}")
        if (
            manifest["backend"] != "cocotb_verilator"
            or manifest["clock_period_ns"] != CLOCK_NS
            or manifest["ranks"] != 2
            or manifest["seed"] != 7
            or manifest["traffic_order"] != "ordered"
            or manifest["reorder"]["probability"] != 0
            or manifest["output_stall_period"] != 0
        ):
            raise ValueError(f"incompatible cycle-exact run: {run}")
        if source_hashes is None:
            source_hashes = device["sources"]
        elif device["sources"] != source_hashes:
            raise ValueError("selected build contains inconsistent RTL source hashes")
        samples = json.loads((run / "samples.json").read_text(encoding="utf-8"))
        for sample in samples:
            if sample["accumulator"] == "FP32_ARRIVAL" and manifest.get("fp32_semantics") != "admission-online-v1":
                raise ValueError("FP32 plots require measurements of online admission accumulation")
            observation = Observation(run, manifest, sample)
            if observation.key in selected:
                raise ValueError(f"duplicate scenario {observation.key}")
            selected[observation.key] = observation
    if not selected:
        raise ValueError(f"no completed source-matched runs for {build_id}")
    return selected


def require(
    rows: dict[tuple[str, str, str, int, str, str, int], Observation],
    workload: str,
    input_format: str,
    output_format: str,
    length: int,
    collective: str,
    accumulator: str = "KULISCH_FIXED",
    settle_cycles: int = 0,
) -> Observation:
    key = (
        workload,
        input_format,
        output_format,
        length,
        collective,
        accumulator,
        settle_cycles,
    )
    if key not in rows:
        raise ValueError(f"missing cycle-exact run: {key}")
    return rows[key]


def per_port_gbps(row: Observation) -> float:
    count = row.manifest["elements_per_rank"]
    cycles = row.sample["data_input_window_cycles"]
    calculated = count * WIDTHS[row.manifest["input_format"]] / (cycles * CLOCK_NS)
    reported = row.sample["input_aggregate_gbps_at_4ns"] / 2
    if abs(calculated - reported) > 1e-9:
        raise ValueError(f"DATA rate disagrees with accepted cycle window: {row.path}")
    return calculated


def result_frame_gbps(row: Observation) -> float:
    return (
        row.sample["frame_bytes"]["RESULT"]
        * 8
        / (row.sample["result_output_window_cycles"] * CLOCK_NS)
    )


def result_saving(auto: Observation, fixed: Observation) -> tuple[int, float]:
    before = fixed.sample["frame_bytes"]["RESULT"]
    after = auto.sample["frame_bytes"]["RESULT"]
    if not 0 < after <= before:
        raise ValueError("AUTO RESULT bytes must be positive and no larger than fixed")
    return before - after, 100 * (before - after) / before


def full_packet_group_capacity(input_format: str) -> int:
    value_bytes = WIDTHS[input_format] // 8
    return ((MTU - 46) // 4 * 4) // value_bytes


def verify_preload(first: Observation, second: Observation) -> None:
    if first.sample["source_bits"] != second.sample["source_bits"]:
        raise ValueError("preload controls used different input vectors")
    if (
        first.sample["final_contribution_latency_cycles"]
        != second.sample["final_contribution_latency_cycles"]
        or first.sample["final_contribution_ingress_cycles"]
        != second.sample["final_contribution_ingress_cycles"]
    ):
        raise ValueError("final-contribution latency depends on preload settling")


def matched_rows(
    rows: dict[tuple[str, str, str, int, str, str, int], Observation],
) -> tuple[
    list[Observation],
    list[tuple[Observation, Observation]],
    list[tuple[Observation, Observation]],
    list[Observation],
    Observation,
]:
    scaling = [require(rows, "ordinary", "FP32", "AUTO", n, "allreduce") for n in LENGTHS]
    formats = [
        (
            require(rows, "ordinary", fmt, "AUTO", 4096, "allreduce"),
            require(rows, "ordinary", fmt, "KULISCH", 4096, "allreduce"),
        )
        for fmt in FORMATS
    ]
    pairs = [
        (
            require(rows, "one_wide", fmt, "AUTO", count, "reduce"),
            require(rows, "one_wide", fmt, "KULISCH", count, "reduce"),
        )
        for fmt, count in ONE_WIDE_CASES
    ]
    all_exact = require(rows, "half_ulp", "FP32", "AUTO", 64, "reduce")
    if all_exact.sample["result_format_elements"] != {"KULISCH": 64}:
        raise ValueError("all-exact control did not retain Kulisch values")
    for auto, fixed in [*pairs, *formats]:
        count = auto.manifest["elements_per_rank"]
        if measurement_sources(auto) != measurement_sources(fixed):
            raise ValueError("AUTO/fixed comparison used different measurement sources")
        if auto.sample["source_bits"] != fixed.sample["source_bits"]:
            raise ValueError("AUTO/fixed comparison used different input vectors")
        if auto.sample["frame_bytes"]["DATA"] != fixed.sample["frame_bytes"]["DATA"]:
            raise ValueError("AUTO/fixed comparison changed DATA traffic")
        expected_count = count * (2 if auto.manifest["collective"] == "allreduce" else 1)
        if auto.manifest["workload"] == "one_wide":
            expected_auto = {auto.manifest["input_format"]: count - 1, "KULISCH": 1}
        else:
            expected_auto = {"INT8": expected_count}
        if auto.sample["result_format_elements"] != expected_auto:
            raise ValueError("AUTO concrete RESULT formats differ from the expected workload")
        if fixed.sample["result_format_elements"] != {"KULISCH": expected_count}:
            raise ValueError("fixed profile did not transport all values as Kulisch")
        if auto.sample["precision_mismatched_elements"] != 0:
            raise ValueError("exact AUTO result differs from the independent FP32-rounded oracle")
        if auto.manifest["workload"] == "one_wide" and (
            count != full_packet_group_capacity(auto.manifest["input_format"])
            or auto.sample["packet_count"]["DATA"] != 2
            or auto.sample["frame_bytes"]["DATA"] != 3024
        ):
            raise ValueError("NumberGroup comparison must fill one DATA packet per rank")
    fixed_fp32 = require(rows, "ordinary", "FP32", "FP32", 4096, "allreduce")
    auto_fp32 = formats[-1][0]
    if (
        fixed_fp32.sample["source_bits"] != auto_fp32.sample["source_bits"]
        or fixed_fp32.sample["frame_bytes"]["DATA"] != auto_fp32.sample["frame_bytes"]["DATA"]
        or fixed_fp32.sample["result_format_elements"] != {"FP32": 8192}
        or fixed_fp32.sample["precision_mismatched_elements"] != 0
    ):
        raise ValueError("fixed FP32 control differs from the AUTO output workload")
    latency = []
    for input_format, output_format, accumulator in (
        ("INT8", "AUTO", "KULISCH_FIXED"),
        ("FP32", "AUTO", "KULISCH_FIXED"),
        ("FP32", "FP32", "KULISCH_FIXED"),
        ("FP32", "KULISCH", "KULISCH_FIXED"),
        ("FP32", "AUTO", "FP32_ARRIVAL"),
    ):
        first, second = (
            require(
                rows,
                "ordinary",
                input_format,
                output_format,
                64,
                "allreduce",
                accumulator,
                settle_cycles=settle,
            )
            for settle in SETTLE_CYCLES
        )
        verify_preload(first, second)
        latency.extend((first, second))
    baseline = [
        *scaling,
        *(row for pair in formats for row in pair),
        *latency,
        fixed_fp32,
        all_exact,
    ]
    if any(measurement_sources(row) != measurement_sources(baseline[0]) for row in baseline):
        raise ValueError("baseline figures used different measurement sources")
    if any(
        measurement_sources(row) != measurement_sources(pairs[0][0])
        for pair in pairs
        for row in pair
    ):
        raise ValueError("NumberGroup cases used different measurement sources")
    return scaling, formats, pairs, latency, fixed_fp32


def save(figure: Figure, output: Path, stem: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    figure.savefig(output / f"{stem}.pdf")
    figure.savefig(output / f"{stem}.svg")


def plot_throughput(
    formats: list[tuple[Observation, Observation]], fixed_fp32: Observation, output: Path
) -> None:
    import matplotlib.pyplot as plt

    names = [auto.manifest["input_format"] for auto, _ in formats]
    rates = [per_port_gbps(auto) for auto, _ in formats]
    elements = [rate / WIDTHS[name] for rate, name in zip(rates, names, strict=True)]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 8.5, "pdf.fonttype": 42}):
        representative_auto, representative_fixed = formats[-1]
        output_rates = [
            result_frame_gbps(representative_auto),
            result_frame_gbps(fixed_fp32),
            result_frame_gbps(representative_fixed),
        ]
        figure, axis = plt.subplots(figsize=(3.0, 2.45), layout="constrained")
        axis.bar(
            ["AUTO", "FP32", "Kulisch"],
            output_rates,
            color=["#D39A56", "#72909F", "#245A7A"],
            width=0.6,
        )
        for index, rate in enumerate(output_rates):
            axis.text(
                index, rate - 3, f"{rate:.1f}", ha="center", va="top", color="white", fontsize=8
            )
        axis.axhline(128, color="#4C5359", ls="--", lw=1, label="128 AXI ideal")
        axis.set_ylim(0, 145)
        axis.set_ylabel("RESULT frames (Gbit/s, aggregate)")
        axis.legend(frameon=False, fontsize=7, loc="upper left")
        axis.grid(axis="y", color="#E4E8EB", lw=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        save(figure, output, "throughput_result")
        plt.close(figure)

        figure, axis = plt.subplots(figsize=(3.0, 2.45), layout="constrained")
        shown = (0, 1, 3)
        positions = list(range(len(shown)))
        actual = [elements[index] for index in shown]
        ideal = [128 / WIDTHS[names[index]] for index in shown]
        axis.vlines(positions, 0, actual, color="#AAB7C1", lw=1.1)
        axis.scatter(positions, actual, color="#245A7A", s=34, zorder=3, label="Measured")
        for position, limit in zip(positions, ideal, strict=True):
            axis.hlines(limit, position - 0.18, position + 0.18, color="#B07031", lw=1.6)
        axis.plot([], [], color="#B07031", lw=1.6, label="128 Gbit/s ideal")
        axis.set_xticks(positions, ("INT8", "FP16/BF16", "FP32"))
        axis.set_ylim(0, 17.5)
        axis.set_ylabel("DATA elements (billion/s per port)")
        axis.legend(frameon=False, fontsize=7, loc="upper right")
        axis.grid(axis="y", color="#E4E8EB", lw=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        save(figure, output, "throughput_elements")
        plt.close(figure)


def plot_latency(scaling: list[Observation], output: Path) -> None:
    import matplotlib.pyplot as plt

    lengths = [row.manifest["elements_per_rank"] for row in scaling]
    exact = [row.sample["collective_cycles"] * CLOCK_NS / 1000 for row in scaling]
    arrival = []
    for row in scaling:
        samples = json.loads((row.path / "samples.json").read_text(encoding="utf-8"))
        cycles = {sample["accumulator"]: sample["collective_cycles"] for sample in samples}
        arrival.append(cycles["FP32_ARRIVAL"] * CLOCK_NS / 1000)
    setup = scaling[0].sample["setup_cycles"] * CLOCK_NS / 1000
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 8.5, "pdf.fonttype": 42}):
        figure, axis = plt.subplots(figsize=(5.9, 2.65), layout="constrained")
        axis.plot(lengths, exact, "o-", color="#245A7A", lw=1.7, label="Kulisch fixed")
        axis.plot(lengths, arrival, "s--", color="#B07031", lw=1.4, label="FP32 arrival")
        axis.axhline(setup, color="#737B81", ls=":", lw=1, label="Setup interval")
        axis.set_xscale("log", base=2)
        axis.set_xlim(52, 4800)
        axis.set_xticks(lengths, [str(length) for length in lengths])
        axis.set_xlabel("FP32 elements per rank")
        axis.set_ylabel("Collective response time (µs)")
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", color="#E4E8EB", lw=0.7)
        axis.spines[["top", "right"]].set_visible(False)
        axis.legend(frameon=False, fontsize=7, loc="upper left")
        save(figure, output, "response_by_length")
        plt.close(figure)


def plot_result_bytes(pairs: list[tuple[Observation, Observation]], output: Path) -> None:
    import matplotlib.pyplot as plt

    def separated(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 8.5, "pdf.fonttype": 42}):
        figure, axis = plt.subplots(figsize=(5.9, 2.3), layout="constrained")
        for position, (auto, fixed) in enumerate(pairs):
            auto_bytes = auto.sample["frame_bytes"]["RESULT"]
            fixed_bytes = fixed.sample["frame_bytes"]["RESULT"]
            auto_packets = auto.sample["packet_count"]["RESULT"]
            fixed_packets = fixed.sample["packet_count"]["RESULT"]
            axis.barh(
                position - 0.17,
                fixed_bytes,
                height=0.28,
                color="#245A7A",
                label="Uniform Kulisch" if position == 0 else None,
            )
            axis.barh(
                position + 0.17,
                auto_bytes,
                height=0.28,
                color="#D39A56",
                label="AUTO" if position == 0 else None,
            )
            axis.text(
                fixed_bytes + 2500,
                position - 0.17,
                f"{separated(fixed_bytes)} B · {fixed_packets} pkt",
                va="center",
                fontsize=7.5,
            )
            axis.text(
                auto_bytes + 2500,
                position + 0.17,
                f"{separated(auto_bytes)} B · {auto_packets} pkt",
                va="center",
                fontsize=7.5,
            )
        maximum = max(fixed.sample["frame_bytes"]["RESULT"] for _, fixed in pairs)
        axis.set_xlim(0, maximum * 1.4)
        axis.set_yticks(range(len(pairs)), [auto.manifest["input_format"] for auto, _ in pairs])
        axis.invert_yaxis()
        axis.set_xlabel("Total RESULT frame bytes (B)")
        axis.set_ylabel("Native format")
        axis.grid(axis="x", color="#E4E8EB", lw=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.legend(frameon=False, fontsize=7, loc="lower right")
        save(figure, output, "result_bytes")
        plt.close(figure)


def plot_final_latency(latency: list[Observation], output: Path) -> None:
    import matplotlib.pyplot as plt

    by_case = {
        (
            row.manifest["input_format"],
            row.manifest["output_format"],
            row.sample["accumulator"],
        ): row
        for row in latency
    }
    cases = [
        ("INT8", "AUTO", "KULISCH_FIXED", "INT8 | Kulisch | AUTO"),
        ("FP32", "AUTO", "KULISCH_FIXED", "FP32 | Kulisch | AUTO"),
        ("FP32", "FP32", "KULISCH_FIXED", "FP32 | Kulisch | FP32"),
        ("FP32", "KULISCH", "KULISCH_FIXED", "FP32 | Kulisch | Kulisch"),
        ("FP32", "AUTO", "FP32_ARRIVAL", "FP32 | FP32 arrival | AUTO"),
    ]
    values = [
        by_case[(input_format, output_format, accumulator)].sample[
            "final_contribution_latency_cycles"
        ]
        for input_format, output_format, accumulator, _ in cases
    ]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 8.5, "pdf.fonttype": 42}):
        figure, axis = plt.subplots(figsize=(5.9, 2.55), layout="constrained")
        positions = list(reversed(range(len(cases))))
        axis.hlines(positions, 0, values, color="#AAB7C1", lw=1.2)
        axis.scatter(values, positions, color="#245A7A", s=38, zorder=3)
        for x, y in zip(values, positions, strict=True):
            axis.text(x + 1.5, y, f"{x} ({x * CLOCK_NS} ns)", va="center", fontsize=8)
        axis.set_yticks(positions, [label for *_, label in cases])
        axis.set_xlim(0, 100)
        axis.set_xlabel("Cycles")
        axis.grid(axis="x", color="#E4E8EB", lw=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        save(figure, output, "final_contribution_latency")
        plt.close(figure)


def write_sources(rows: list[Observation], data_output: Path, build_id: str) -> None:
    data_output.mkdir(parents=True, exist_ok=True)
    selected = sorted(rows, key=lambda row: row.key)
    device = json.loads((selected[0].path / "device.json").read_text(encoding="utf-8"))
    fields = (
        "run",
        "workload",
        "input_format",
        "output_format",
        "elements_per_rank",
        "collective",
        "accumulator",
        "setup_cycles",
        "collective_cycles",
        "data_window_cycles",
        "result_window_cycles",
        "data_gbps_per_port",
        "result_frame_bytes",
        "result_packets",
        "result_groups",
        "result_format_elements",
        "preload_settle_cycles",
        "final_contribution_latency_cycles",
        "final_contribution_ingress_cycles",
        "result_frame_gbps",
    )
    with (data_output / "evaluation-cycle-exact.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            sample = row.sample
            writer.writerow(
                {
                    "run": row.path.name,
                    "workload": row.manifest["workload"],
                    "input_format": row.manifest["input_format"],
                    "output_format": row.manifest["output_format"],
                    "elements_per_rank": row.manifest["elements_per_rank"],
                    "collective": row.manifest["collective"],
                    "accumulator": sample["accumulator"],
                    "setup_cycles": sample["setup_cycles"],
                    "collective_cycles": sample["collective_cycles"],
                    "data_window_cycles": sample["data_input_window_cycles"],
                    "result_window_cycles": sample["result_output_window_cycles"],
                    "data_gbps_per_port": f"{per_port_gbps(row):.9f}",
                    "result_frame_bytes": sample["frame_bytes"]["RESULT"],
                    "result_packets": sample["packet_count"]["RESULT"],
                    "result_groups": sample["numbergroups"]["RESULT"],
                    "result_format_elements": json.dumps(
                        sample["result_format_elements"], sort_keys=True
                    ),
                    "preload_settle_cycles": (
                        row.manifest["preload_settle_cycles"]
                        if row.manifest.get("preload_first_rank", False)
                        else ""
                    ),
                    "final_contribution_latency_cycles": sample[
                        "final_contribution_latency_cycles"
                    ],
                    "final_contribution_ingress_cycles": sample[
                        "final_contribution_ingress_cycles"
                    ],
                    "result_frame_gbps": f"{result_frame_gbps(row):.9f}",
                }
            )
    source = {
        "build_id": build_id,
        "clock_period_ns": CLOCK_NS,
        "scope": "Verilator/Cocotb SINGLE, two ranks on separate ports, seed 7",
        "rtl_sources": device["sources"],
        "runs": {
            row.path.name: {
                "manifest_sha256": sha256(row.path / "manifest.json"),
                "device_sha256": sha256(row.path / "device.json"),
                "samples_sha256": sha256(row.path / "samples.json"),
                "measurement_sources": measurement_sources(row),
            }
            for row in selected
        },
    }
    (data_output / "figure-sources.json").write_text(
        json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "build/experiments/02-experiment-numbergroup-single/ordered",
    )
    parser.add_argument("--build-id", default=BUILD_ID)
    parser.add_argument("--output", type=Path, default=HERE / "results/figures")
    parser.add_argument("--data-output", type=Path, default=HERE / "results")
    args = parser.parse_args()
    rows = observations(args.input, args.build_id)
    scaling, formats, pairs, latency, fixed_fp32 = matched_rows(rows)
    plot_throughput(formats, fixed_fp32, args.output)
    plot_latency(scaling, args.output)
    plot_result_bytes(pairs, args.output)
    plot_final_latency(latency, args.output)
    paths = {
        row.path
        for row in [
            *scaling,
            *(row for pair in formats for row in pair),
            *(row for pair in pairs for row in pair),
            *latency,
            fixed_fp32,
        ]
    }
    paths.add(require(rows, "half_ulp", "FP32", "AUTO", 64, "reduce").path)
    write_sources(
        [row for row in rows.values() if row.path in paths], args.data_output, args.build_id
    )
    print(f"Figures: {args.output}")
    print(f"Data: {args.data_output}")


if __name__ == "__main__":
    main()
