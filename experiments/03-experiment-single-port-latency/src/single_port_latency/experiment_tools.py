"""Measure final-packet latency for eight ranks sharing one physical port."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from prism_experiments.artifacts import (
    new_run,
    portable,
    repository_root,
    source_identity,
    write_json,
)
from prism_experiments.rtl import RtlDevice, read_manifest, run_cocotb

HERE = Path(__file__).resolve().parents[2]
ROOT = repository_root(HERE)
HDL = ROOT / "repo/prism-hdl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lengths", type=int, nargs="+", default=[64, 256])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--settle-cycles", type=int, default=128)
    parser.add_argument("--output-stall-period", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        run_experiment(args)
    except ValueError as error:
        parser.error(str(error))


def run_experiment(args: argparse.Namespace) -> Path:
    """Collect and validate one source-identified RTL latency run."""
    if not args.lengths or any(not 1 <= length <= 256 for length in args.lengths):
        raise ValueError("each length must fit one native DATA packet: 1..256 elements")
    if args.settle_cycles < 0:
        raise ValueError("settle cycles cannot be negative")
    if args.output_stall_period == 1 or args.output_stall_period < 0:
        raise ValueError("output stall period must be zero or at least two")

    cases = [
        {"input_format": fmt, "accumulator": "KULISCH_FIXED", "workload": "ordinary", "length": n}
        for n in args.lengths
        for fmt in ("INT8", "FP16", "BF16", "FP32")
    ]
    cases.extend(
        {"input_format": "FP32", "accumulator": policy, "workload": "ordinary", "length": n}
        for n in args.lengths
        for policy in ("FP32_ARRIVAL",)
    )
    cases.extend(
        {"input_format": "FP32", "accumulator": policy, "workload": "sensitive", "length": 64}
        for policy in ("KULISCH_FIXED", "FP32_ARRIVAL")
    )
    run_dir = new_run(ROOT, HERE.name, args.output)
    manifest = {
        "fp32_semantics": "admission-online-v1",
        "schema_version": 1,
        "status": "running",
        "backend": "cocotb_verilator",
        "ranks": 8,
        "physical_ports": 1,
        "clock_period_ns": 4,
        "seed": args.seed,
        "preload_settle_cycles": args.settle_cycles,
        "mtu_bytes": 1500,
        "output_stall_period": args.output_stall_period,
        "cases": cases,
        "primary_metric": (
            "first accepted RESULT beat minus last accepted beat of final DATA packet"
        ),
        "secondary_metric": (
            "first accepted RESULT beat minus first accepted beat of final DATA packet"
        ),
        "command": [
            portable(sys.executable, ROOT),
            portable(HERE / "experiment.py", ROOT),
            *sys.argv[1:],
        ],
        "provenance": source_identity(ROOT, HERE),
    }
    write_json(run_dir / "manifest.json", manifest)
    device = RtlDevice(
        "prism_sim_top",
        (*read_manifest(HDL), *read_manifest(HDL, "verification/rtl.f")),
        parameters={"NUM_PORTS": 1},
    )
    try:
        run_cocotb(
            device,
            root=ROOT,
            experiment=HERE,
            module="src.single_port_latency.rtl_callback",
            run_dir=run_dir,
        )
        samples = json.loads((run_dir / "samples.json").read_text(encoding="utf-8"))
        if len(samples) != len(cases):
            raise AssertionError("RTL callback did not return every requested case")
        build_id = json.loads((run_dir / "device.json").read_text(encoding="utf-8"))["build_id"]
        columns = (
            "build_id",
            "seed",
            "preload_settle_cycles",
            "clock_period_ns",
            *samples[0].keys(),
        )
        with (run_dir / "samples.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            for sample in samples:
                writer.writerow(
                    {
                        "build_id": build_id,
                        "seed": args.seed,
                        "preload_settle_cycles": args.settle_cycles,
                        "clock_period_ns": 4,
                        **sample,
                    }
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
