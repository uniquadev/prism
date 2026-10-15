"""A reproducible two-rank SUM experiment; collect and plot are independent commands."""

from __future__ import annotations

import argparse
import json
import random
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from prism_experiments.artifacts import new_run, repository_root, source_identity, write_json

HERE = Path(__file__).resolve().parents[2]
ROOT = repository_root(HERE)


def positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def fp32_vector(values: list[int]) -> Any:
    """Convert numeric values to the explicit IEEE bit patterns used by CCL."""
    from prism_ccl.domain.model import ConcreteFormat, TypedVector

    return TypedVector(
        ConcreteFormat.FP32,
        tuple(struct.unpack("<I", struct.pack("<f", value))[0] for value in values),
    )


def configure_single(world: Any, *, mtu: int) -> dict[str, Any]:
    """One physical link per rank; derive the logical edges from those same ranks."""
    from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode

    world.add_node(world.manager, bytes.fromhex("020000000000"))
    world.add_prism("switch", bytes.fromhex("020000000003"))
    world.connect(world.manager, 1, "switch", 1, mtu=mtu)
    nodes = [LogicalNode("switch")]
    edges = []
    for rank in range(2):
        name = f"rank{rank}"
        world.add_node(name, bytes([2, 0, 0, 0, 0, rank + 1]))
        world.connect(name, 1, "switch", rank + 2, mtu=mtu)
        nodes.append(LogicalNode(name, rank))
        edges.append(LogicalEdge(name, "switch", 1, 10 + rank, (name, "switch")))
    return {
        "tree": CollectiveTree("switch", tuple(nodes), tuple(edges)),
        "management_paths": {"switch": (world.manager, "switch")},
        "mtu": mtu,
    }


def collect(args: argparse.Namespace) -> Path:
    if args.collective == "allreduce" and args.root_rank is not None:
        raise ValueError("AllReduce delivers to every rank; --root-rank only applies to Reduce")
    if args.samples > 65535:
        raise ValueError("this template supports at most 65535 operation IDs per world")
    from prism_ccl.domain.model import AccumulatorPolicy, PartialWirePolicy
    from prism_ccl.world import PrismWorld

    # Policy pairing is derived once; callers do not specify the same choice twice.
    accumulator, partial = {
        "kulisch-fixed": (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO),
        "fp32-arrival": (AccumulatorPolicy.FP32_ARRIVAL, PartialWirePolicy.FP32),
    }[args.accumulator]
    destination = 0 if args.root_rank is None else args.root_rank
    world = PrismWorld(manager="am")
    topology = configure_single(world, mtu=args.mtu)
    run_dir = new_run(ROOT, HERE.name, args.output)
    manifest = {
        "schema_version": 1,
        "status": "running",
        "backend": "software_packet_model",
        "experiment": HERE.name,
        "collective": args.collective,
        "operator": "SUM",
        "accumulator": accumulator.name,
        "partial_wire": partial.name,
        "seed": args.seed,
        "samples": args.samples,
        "elements_per_rank": args.elements,
        "mtu": args.mtu,
        "root_rank": destination if args.collective == "reduce" else None,
        "provenance": source_identity(ROOT, HERE),
        "measurement_boundary": "serialized Ethernet frames emitted by the software model",
        "excluded_wire_overhead": "FCS, preamble, inter-packet gap",
        "timing": "model ticks are not RTL cycles or physical latency",
    }
    write_json(run_dir / "manifest.json", manifest)
    rng = random.Random(args.seed)
    samples = []
    try:
        for index in range(args.samples):
            # Small integers make the independent expected SUM exact even in FP32.
            vectors = [[rng.randrange(-8, 9) for _ in range(args.elements)] for _ in range(2)]
            expected = fp32_vector([a + b for a, b in zip(*vectors, strict=True)]).bits
            name = f"sample-{index}"
            settings = dict(
                topology,
                vectors={rank: fp32_vector(values) for rank, values in enumerate(vectors)},
                accumulator=accumulator,
                partial_wire=partial,
            )
            if args.collective == "reduce":
                world.register_reduce(name, destination_rank=destination, **settings)
                expected_ranks = {destination}
            else:
                world.register_allreduce(name, **settings)
                expected_ranks = {0, 1}
            result = world.run(name)
            if set(result.rank_bits) != expected_ranks or any(
                bits != expected for bits in result.rank_bits.values()
            ):
                raise AssertionError(
                    f"sample {index}: DUT/model output does not match exact integer SUM"
                )
            if not result.released_contexts:
                raise AssertionError(f"sample {index}: operation resources were not released")
            packets: Counter[str] = Counter()
            byte_counts: Counter[str] = Counter()
            for event in result.frames:
                packets[event.packet_class.name] += 1
                byte_counts[event.packet_class.name] += len(event.frame)
            samples.append(
                {
                    "sample": index,
                    "input_values": vectors,
                    "expected_fp32_bits": expected,
                    "result_fp32_bits": result.rank_bits,
                    "packet_count": dict(packets),
                    "frame_bytes": dict(byte_counts),
                    "model_ticks": result.simulated_ticks,
                    "released_contexts": result.released_contexts,
                }
            )
        write_json(run_dir / "samples.json", samples)
        manifest["status"] = "complete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        write_json(run_dir / "samples.json", samples)
        raise
    finally:
        write_json(run_dir / "manifest.json", manifest)
    print(f"Measurements: {run_dir}")
    return run_dir


def plot(run_dir: Path, output: Path | None = None) -> None:
    # No cocotb import, simulator startup, build or collection on this path.
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    samples = json.loads((run_dir / "samples.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "complete"
        or manifest.get("backend") != "software_packet_model"
        or not samples
    ):
        raise ValueError("plot requires a complete software packet-model run with schema version 1")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["CONTROL", "DATA", "RESULT", "PROGRESS"]
    destination = output or run_dir / "figures"
    destination.mkdir(parents=True, exist_ok=True)
    with plt.rc_context({"font.family": "serif", "font.size": 10}):
        fig, axes = plt.subplots(1, 2, figsize=(8, 3.2), layout="constrained")
        for axis, field, unit in zip(
            axes,
            ("frame_bytes", "packet_count"),
            ("Frame bytes / collective", "Packets / collective"),
            strict=True,
        ):
            values = [
                sum(sample[field].get(label, 0) for sample in samples) / len(samples)
                for label in labels
            ]
            axis.bar(labels, values, color="#42677b", edgecolor="black", linewidth=0.6)
            axis.set_ylabel(unit)
            axis.spines[["top", "right"]].set_visible(False)
            axis.tick_params(axis="x", labelsize=8)
            axis.set_ylim(bottom=0)
        fig.suptitle(f"{manifest['collective'].title()} SUM — software packet model")
        fig.savefig(destination / "traffic.svg")
        fig.savefig(destination / "traffic.png", dpi=180)
        plt.close(fig)
    print(f"Figures: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "all"):
        command = commands.add_parser(
            name, help="collect measurements" + (" and plot" if name == "all" else "")
        )
        command.add_argument("--collective", choices=("reduce", "allreduce"), default="reduce")
        command.add_argument("--root-rank", type=int, choices=(0, 1))
        command.add_argument("--samples", type=positive, default=3)
        command.add_argument("--elements", type=positive, default=32)
        command.add_argument("--seed", type=int, default=7)
        command.add_argument("--mtu", type=int, choices=(576, 1500, 9000), default=1500)
        command.add_argument(
            "--accumulator",
            default="kulisch-fixed",
            choices=("kulisch-fixed", "fp32-arrival"),
        )
        command.add_argument(
            "--output", type=Path, help="new run directory; must not already exist"
        )
    command = commands.add_parser("plot", help="render existing measurements without simulation")
    command.add_argument("--input", type=Path, required=True, help="a completed run directory")
    command.add_argument("--output", type=Path, help="figure directory; defaults to INPUT/figures")
    args = parser.parse_args()
    try:
        if args.command == "plot":
            plot(args.input, args.output)
        else:
            output = collect(args)
            if args.command == "all":
                plot(output)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")
