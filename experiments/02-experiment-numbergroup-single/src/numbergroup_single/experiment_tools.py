"""Compare source-identified SINGLE exact profiles or redraw their plot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from prism_experiments.artifacts import new_run, repository_root, source_identity, write_json
from prism_experiments.rtl import RtlDevice, read_manifest, run_cocotb

HERE = Path(__file__).resolve().parents[2]
ROOT = repository_root(HERE)
HDL = ROOT / "repo/prism-hdl"


def elements(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 4096:
        raise argparse.ArgumentTypeError("SINGLE RTL supports 1..4096 elements")
    return parsed


def rtl_sources(reference_device: Path | None) -> tuple[Path, ...]:
    if reference_device is None:
        return (*read_manifest(HDL), *read_manifest(HDL, "verification/rtl.f"))
    reference = json.loads(reference_device.read_text(encoding="utf-8"))
    if reference.get("top") != "prism_sim_top":
        raise ValueError("reference device is not prism_sim_top")
    expected = reference["sources"]
    current_order = (
        *read_manifest(HDL),
        *read_manifest(HDL, "verification/rtl.f"),
    )
    ordered = [path.relative_to(ROOT).as_posix() for path in current_order]
    relative = tuple(name for name in ordered if name in expected) + tuple(
        name for name in expected if name not in ordered
    )
    snapshot = ROOT / reference["build_directory"] / "sources"
    frozen = tuple(snapshot / name for name in relative)
    for name, path in zip(relative, frozen, strict=True):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
            raise ValueError(f"missing or changed RTL snapshot source: {name}")
    return frozen


def collect(args: argparse.Namespace) -> Path:
    if args.output_stall_period == 1 or args.output_stall_period < 0:
        raise ValueError("output stall period must be zero or at least two cycles")
    if args.workload == "half_ulp" and args.input_format != "fp32":
        raise ValueError("half_ulp requires FP32 inputs")
    if args.workload == "sparse_exact" and (args.input_format != "fp32" or args.ranks != 2):
        raise ValueError("sparse_exact requires two FP32 ranks")
    if args.workload == "one_wide" and (
        args.input_format not in ("fp16", "bf16", "fp32")
        or args.output_format not in ("auto", "kulisch")
        or args.collective != "reduce"
        or args.ranks != 2
        or args.elements < 2
    ):
        raise ValueError(
            "one_wide requires two ranks, Reduce, at least two elements, "
            "FP16/BF16/FP32 input and AUTO/Kulisch output"
        )
    if not 0 <= args.reorder_probability <= 1:
        raise ValueError("reorder probability must be between zero and one")
    if not 2 <= args.reorder_window_packets <= 32:
        raise ValueError("reorder window must contain 2..32 packets")
    if args.preload_first_rank and (args.ranks != 2 or args.reorder_probability != 0):
        raise ValueError("preload measurement requires two ranks and ordered DATA")
    if args.preload_settle_cycles < 0:
        raise ValueError("preload settle cycles cannot be negative")
    sources = rtl_sources(args.source_device)
    traffic_order = "reordered" if args.reorder_probability else "ordered"
    run_dir: Path = new_run(ROOT, f"{HERE.name}/{traffic_order}", args.output)
    manifest = {
        "fp32_semantics": "admission-online-v1",
        "schema_version": 4,
        "status": "running",
        "backend": "cocotb_verilator",
        "experiment": HERE.name,
        "collective": args.collective,
        "seed": args.seed,
        "ranks": args.ranks,
        "output_stall_period": args.output_stall_period,
        "capture_pcaps": args.capture_pcaps,
        "preload_first_rank": args.preload_first_rank,
        "preload_settle_cycles": args.preload_settle_cycles,
        "workload": args.workload,
        "input_format": args.input_format.upper(),
        "output_format": args.output_format.upper(),
        "elements_per_rank": args.elements,
        "traffic_order": traffic_order,
        "reorder": {
            "probability": args.reorder_probability,
            "window_packets": args.reorder_window_packets,
            "seed": args.seed if args.reorder_seed is None else args.reorder_seed,
            "scope": "rank-to-PRISM DATA flows",
        },
        "profiles": (
            ("KULISCH_FIXED/KULISCH", "FP32_ARRIVAL/FP32")
            if args.input_format == "fp32" and args.output_format in ("fp32", "auto")
            else ("KULISCH_FIXED/KULISCH",)
        ),
        "measurement_boundary": "first accepted STAGE beat to last accepted RESULT beat",
        "clock_period_ns": 4,
        "excluded_wire_overhead": "FCS, preamble, inter-packet gap",
        "provenance": source_identity(ROOT, HERE),
        "source_device": str(args.source_device.resolve()) if args.source_device else None,
    }
    write_json(run_dir / "manifest.json", manifest)
    device = RtlDevice("prism_sim_top", sources)
    try:
        run_cocotb(
            device,
            root=ROOT,
            experiment=HERE,
            module="src.numbergroup_single.rtl_callback",
            run_dir=run_dir,
        )
        manifest["status"] = "complete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        write_json(run_dir / "manifest.json", manifest)
    print(f"Measurements: {run_dir}")
    return run_dir


def plot(run_dir: Path, output: Path | None = None) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    samples = json.loads((run_dir / "samples.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 4
        or manifest.get("status") != "complete"
        or manifest.get("backend") != "cocotb_verilator"
        or not 1 <= len(samples) <= 4
    ):
        raise ValueError("plot requires completed Cocotb RTL samples")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination = output or run_dir / "figures"
    destination.mkdir(parents=True, exist_ok=True)
    with plt.rc_context({"font.family": "serif", "font.size": 10}):
        figure, axes = plt.subplots(1, 2, figsize=(8, 2.8), layout="constrained")
        labels = [sample["accumulator"] for sample in samples]
        positions = range(len(samples))
        axes[0].scatter([sample["collective_cycles"] * 0.004 for sample in samples], positions)
        axes[0].set_xlabel("Collective response time (µs at target clock)")
        axes[1].scatter([sample["result_aggregate_gbps_at_4ns"] for sample in samples], positions)
        axes[1].set_xlabel("Aggregate RESULT payload (Gbit/s at target clock)")
        for axis in axes:
            axis.set_yticks(list(positions), labels)
            axis.set_xlim(left=0)
            axis.spines[["top", "right"]].set_visible(False)
            axis.grid(axis="x", alpha=0.2)
        figure.suptitle(
            f"SINGLE {manifest['input_format']}→{manifest['output_format']}, "
            f"{manifest['elements_per_rank']} elements — simulated, not routed"
        )
        figure.savefig(destination / "single.svg")
        figure.savefig(destination / "single.png", dpi=180)
        plt.close(figure)
    print(f"Figures: {destination}")


def summarize(parent: Path) -> None:
    columns = (
        "run",
        "build_id",
        "traffic_order",
        "seed",
        "reorder_probability",
        "reorder_window_packets",
        "reorder_seed",
        "input_format",
        "output_format",
        "workload",
        "elements_per_rank",
        "ranks",
        "collective",
        "accumulator",
        "partial_wire",
        "setup_cycles",
        "collective_cycles",
        "data_to_result_cycles",
        "data_input_window_cycles",
        "result_output_window_cycles",
        "collective_elements_per_second_at_4ns",
        "input_aggregate_gbps_at_4ns",
        "input_aggregate_elements_per_second_at_4ns",
        "result_aggregate_gbps_at_4ns",
        "data_packets",
        "data_reordered_packets",
        "data_max_displacement_packets",
        "precision_mismatched_elements",
        "precision_max_ulp",
        "precision_mean_ulp",
        "precision_max_absolute_error",
        "precision_mean_absolute_error",
        "output_stalled_beats",
        "preload_first_rank",
        "final_contribution_latency_cycles",
        "final_contribution_ingress_cycles",
        "input_stalled_beats_port_0",
        "input_stalled_beats_port_1",
    )
    failures = []
    for traffic_order in ("ordered", "reordered"):
        rows = []
        for run_dir in sorted((parent / traffic_order).glob("*/manifest.json")):
            manifest = json.loads(run_dir.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != 4:
                continue
            if manifest["status"] != "complete":
                failures.append(
                    {
                        "run": run_dir.parent.name,
                        "traffic_order": traffic_order,
                        "status": manifest["status"],
                        "error": manifest.get("error"),
                    }
                )
                continue
            device = json.loads((run_dir.parent / "device.json").read_text(encoding="utf-8"))
            samples = json.loads((run_dir.parent / "samples.json").read_text(encoding="utf-8"))
            for sample in samples:
                row = {
                    "run": run_dir.parent.name,
                    "build_id": device["build_id"],
                    "traffic_order": traffic_order,
                    "seed": manifest["seed"],
                    "reorder_probability": manifest["reorder"]["probability"],
                    "reorder_window_packets": manifest["reorder"]["window_packets"],
                    "reorder_seed": manifest["reorder"]["seed"],
                    "input_format": manifest["input_format"],
                    "output_format": manifest["output_format"],
                    "workload": manifest["workload"],
                    "elements_per_rank": manifest["elements_per_rank"],
                    "ranks": manifest["ranks"],
                    "collective": manifest["collective"],
                    "preload_first_rank": manifest.get("preload_first_rank", False),
                    "input_stalled_beats_port_0": sample["input_stalled_beats_by_port"][0],
                    "input_stalled_beats_port_1": sample["input_stalled_beats_by_port"][1],
                }
                row.update({name: sample.get(name) for name in columns if name not in row})
                row["input_aggregate_elements_per_second_at_4ns"] = (
                    manifest["ranks"]
                    * manifest["elements_per_rank"]
                    * 250_000_000
                    / sample["data_input_window_cycles"]
                )
                rows.append(row)
        destination = parent / traffic_order / "samples.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{traffic_order}: {len(rows)} samples in {destination}")
    write_json(parent / "failed_runs.json", failures)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "all"):
        command = commands.add_parser(name)
        command.add_argument("--collective", choices=("reduce", "allreduce"), default="allreduce")
        command.add_argument("--seed", type=int, default=7)
        command.add_argument("--ranks", type=int, choices=(2, 3), default=2)
        command.add_argument("--output-stall-period", type=int, default=0)
        command.add_argument("--capture-pcaps", action="store_true")
        command.add_argument("--preload-first-rank", action="store_true")
        command.add_argument("--preload-settle-cycles", type=int, default=64)
        command.add_argument("--reorder-probability", type=float, default=0.0)
        command.add_argument("--reorder-window-packets", type=int, default=2)
        command.add_argument("--reorder-seed", type=int)
        command.add_argument(
            "--workload",
            choices=("ordinary", "half_ulp", "sparse_exact", "one_wide"),
            default="ordinary",
        )
        command.add_argument("--source-device", type=Path)
        command.add_argument(
            "--input-format", choices=("int8", "fp16", "bf16", "fp32"), default="fp32"
        )
        command.add_argument(
            "--output-format",
            choices=("int8", "fp16", "bf16", "fp32", "kulisch", "auto"),
            default="fp32",
        )
        command.add_argument("--elements", type=elements, default=64)
        command.add_argument("--output", type=Path)
    command = commands.add_parser("plot")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--output", type=Path)
    command = commands.add_parser("summarize")
    command.add_argument("--input", type=Path, default=ROOT / "build/experiments" / HERE.name)
    args = parser.parse_args()
    try:
        if args.command == "plot":
            plot(args.input, args.output)
        elif args.command == "summarize":
            summarize(args.input)
        else:
            run_dir = collect(args)
            if args.command == "all":
                plot(run_dir)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")

