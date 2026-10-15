"""Plot verified RESULT-frame accounting by application domain.

Requires matplotlib; run after exact_accumulator_study.py and joint_optimizer.py. The same vector
length is used as the denominator for each method within a case.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


METHODS = (
    ("uniform_kulisch", "Uniform Kulisch", "#254D69", ""),
    ("auto", "AUTO", "#C79659", "//"),
    ("compressed_exact", "AUTO + adaptive compression", "#598D85", "\\\\"),
    ("fixed_fp32", "Fixed FP32", "#F7F7F5", "xx"),
)


def load_cases(baseline_path: Path, optimized_path: Path) -> list[dict]:
    """Fixed-format baselines plus the independently optimized software cases."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    optimized = json.loads(optimized_path.read_text(encoding="utf-8"))
    if baseline["sources"] != optimized["sources"]:
        raise ValueError("baseline and optimizer sources differ")
    if (optimized["constraints"]["mtu"] != baseline["protocol"]["mtu"] or
            optimized["constraints"]["frame_header_bytes"] != baseline["protocol"]["frame_overhead"]):
        raise ValueError("incompatible byte accounting")
    cases = [dict(c) for c in baseline["cases"] if not c["label"].startswith("Constructed")]
    by_label = {c["label"]: c for c in optimized["cases"]}
    if len(by_label) != len(optimized["cases"]) or set(by_label) != {c["label"] for c in cases}:
        raise ValueError("optimizer workload mismatch")
    mapping = {"auto": "numbergroups_only", "compressed_uniform_kulisch": "kulisch_compressed",
               "compressed_exact": "numbergroups_all_compressed"}
    for case in cases:
        opt = by_label[case["label"]]
        if case["n"] != opt["n"]:
            raise ValueError("optimizer denominator mismatch")
        for target, source in mapping.items():
            case[target] = opt["methods"][source]
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    folder = Path(__file__).resolve().parent
    parser.add_argument("--input", type=Path, default=folder / "results.json")
    parser.add_argument("--optimized-input", type=Path, default=folder / "joint_results.json")
    parser.add_argument("--output", type=Path, default=folder / "results_by_domain.pdf")
    args = parser.parse_args()
    cases = load_cases(args.input, args.optimized_input)
    if [case["label"] for case in cases] != [
        "CFD / cavity01", "HPC / bcsstk16", "LLM / QKV", "LLM / MLP"
    ]:
        raise ValueError("case order changed; revise domain grouping")

    plt.rcParams.update({
        "font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 9, "axes.edgecolor": "#343434", "axes.linewidth": 0.7,
        "pdf.fonttype": 42, "svg.fonttype": "none", "hatch.linewidth": 0.45,
    })
    fig, ax = plt.subplots(figsize=(7.25, 3.5))
    fig.patch.set_facecolor("white")
    centers = (0.0, 1.15, 2.48, 3.52)
    width = 0.19
    for method_index, (key, legend, color, hatch) in enumerate(METHODS):
        positions = [center + (method_index - (len(METHODS) - 1) / 2) * width for center in centers]
        heights = [case[key]["frame_bytes"] / case["n"] for case in cases]
        ax.bar(positions, heights, width=width * 0.94, label=legend,
               facecolor=color, edgecolor="#313B40", linewidth=0.45,
               hatch=hatch, zorder=3)

    ax.set_ylim(0, 51)
    ax.set_xlim(-0.56, 4.08)
    ax.set_yticks([0, 10, 20, 30, 40])
    ax.set_ylabel("RESULT-frame bytes per output value")
    ax.set_xticks(centers, ["cavity01\nN = 317", "bcsstk16\nN = 4,884",
                            "QKV\nN = 384", "MLP\nN = 512"])
    ax.set_xlabel("N = output vector length", labelpad=8)
    ax.tick_params(axis="x", length=0, pad=6)
    ax.tick_params(axis="y", length=3)
    ax.grid(axis="y", color="#D9DDDF", linewidth=0.55, zorder=0)
    # A 32-bit FP32 value occupies four payload bytes.  Actual FP32 bars also
    # include RESULT headers, descriptors, padding, and frame boundaries.
    ax.axhline(4.0, color="#B63F3F", linestyle=(0, (1.4, 2.2)),
               linewidth=1.1, dash_capstyle="round", zorder=4)
    ax.text(-0.51, 4.5, "4 B", ha="left", va="bottom", fontsize=7,
            color="#B63F3F", fontweight="bold",
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.2},
            zorder=6)
    ax.text(1.815, 4.6, "Target", ha="center", va="bottom", fontsize=7.5,
            color="#B63F3F", fontweight="bold",
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.3},
            zorder=6)
    for split in (0.575, 1.815):
        ax.axvline(split, color="#B9C1C5", linestyle=(0, (2, 3)),
                   linewidth=0.7, zorder=1)
    for x, title in ((0.0, "Fluid dynamics"), (1.15, "Structural mechanics"),
                     (3.0, "AI / language model")):
        ax.text(x, 48.9, title, ha="center", va="center", fontsize=8.5,
                fontweight="bold", color="#30363A")
    ax.spines[["top", "right"]].set_visible(False)
    fig.legend(loc="upper center", bbox_to_anchor=(0.52, 0.99), ncol=4,
               frameon=False, handlelength=1.6, columnspacing=1.5,
               fontsize=8.4)
    fig.subplots_adjust(left=0.105, right=0.985, bottom=0.225, top=0.86)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, facecolor="white")
    fig.savefig(args.output.with_suffix(".svg"), facecolor="white")
    fig.savefig(args.output.with_suffix(".png"), facecolor="white", dpi=220)
    plt.close(fig)
    print(args.output)


if __name__ == "__main__":
    main()
