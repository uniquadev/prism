"""Draw the U280 release figures: line rate, placement, and LUT and power budget.

Every number comes from data.json; the placement view is a Vivado 2022.1
screenshot of the routed v1.0.0 checkpoint. Writes PDF, SVG and PNG in English
and Italian next to this script, or into --output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / "data.json").read_text(encoding="utf-8"))

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "STIXGeneral"],
    "mathtext.fontset": "stix",
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
})

INK = "#202020"
MUTED = "#666666"
BLUE = "#185D78"
GRID = "#E6E6E3"
# Colours Vivado was asked to highlight each block with in the screenshot.
VIVADO = {
    "output_auto_numbergroup": "#FF961E",
    "kulisch_arithmetic": "#00D2E6",
    "receive_and_control": "#EB50D2",
    "port_100g": "#78E650",
    "other": "#8C8C8C",
}
# The same blocks in the muted palette of the thesis figures.
SHADES = {
    "output_auto_numbergroup": BLUE,
    "kulisch_arithmetic": "#6F98AC",
    "receive_and_control": "#B5C9D3",
    "port_100g": "#9A9A96",
    "other": "#D9D9D6",
}

TEXT = {
    "en": {
        "data": "DATA input", "result": "RESULT output", "sparse": "AUTO, sparse exact values",
        "native": "native formats, AUTO", "bound": "100 Gbit/s requirement",
        "axi": "128 Gbit/s AXI limit", "axis": "Sustained rate per stream (Gbit/s)",
        "mixes": "8 tiles, frame bytes",
        "row_data": "DATA input, FP32 (slowest)", "row_native": "RESULT output, native or AUTO",
        "row_kulisch": "RESULT output, Kulisch", "row_sparse": "RESULT output, sparse AUTO (worst)",
        "output_auto_numbergroup": "Output: AUTO and NumberGroup",
        "kulisch_arithmetic": "Exact sum (Kulisch)",
        "receive_and_control": "Receive and control",
        "port_100g": "100G port (CMAC, OpenNIC adapter)", "other": "Other logic",
        "luts": "LUTs", "power": "Power", "static": "static", "core": "PRISM core",
        "port": "100G port", "lut_total": "529,840 LUTs, 40.6% of the device",
        "power_total": "13.6 W estimated on chip", "cmac": "white frame: CMAC 0, QSFP0",
    },
    "it": {
        "data": "Ingresso DATA", "result": "Uscita RESULT", "sparse": "AUTO, valori esatti sparsi",
        "native": "formati nativi, AUTO", "bound": "requisito di 100 Gbit/s",
        "axi": "limite AXI di 128 Gbit/s", "axis": "Velocità sostenuta per flusso (Gbit/s)",
        "mixes": "8 tile, byte dei frame",
        "row_data": "Ingresso DATA, FP32 (il più lento)", "row_native": "Uscita RESULT, nativi o AUTO",
        "row_kulisch": "Uscita RESULT, Kulisch", "row_sparse": "Uscita RESULT, AUTO sparso (peggiore)",
        "output_auto_numbergroup": "Uscita: AUTO e NumberGroup",
        "kulisch_arithmetic": "Somma esatta (Kulisch)",
        "receive_and_control": "Ricezione e controllo",
        "port_100g": "Porta 100G (CMAC, adattatore OpenNIC)", "other": "Altra logica",
        "luts": "LUT", "power": "Potenza", "static": "statica", "core": "core PRISM",
        "port": "porta 100G", "lut_total": "529.840 LUT, il 40,6% del dispositivo",
        "power_total": "13,6 W stimati sul chip", "cmac": "riquadro bianco: CMAC 0, QSFP0",
    },
}


def number(value: float, lang: str, digits: int = 1) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if lang == "it" else text


def save(fig, output: Path, stem: str, lang: str) -> None:
    for ext in ("pdf", "svg", "png"):
        fig.savefig(output / f"{stem}-{lang}.{ext}", dpi=220, facecolor="white",
                    bbox_inches="tight", pad_inches=0.04,
                    metadata={"Date": None} if ext == "pdf" else None)
    plt.close(fig)


def clean(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)


def line_rate(lang: str, output: Path) -> None:
    """One bar per stream: the slowest measured case of each, against 100 Gbit/s."""
    t, rate = TEXT[lang], DATA["line_rate"]
    rows = [
        (t["row_data"], rate["data_numeric_gbps"]["FP32"]),
        (t["row_native"], rate["result_numeric_gbps"]["native"]),
        (t["row_kulisch"], rate["result_numeric_gbps"]["KULISCH"]),
        (t["row_sparse"], min(rate["sparse_auto_axi_gbps"].values())),
    ]
    fig, ax = plt.subplots(figsize=(6.4, 2.3))
    y = list(range(len(rows)))[::-1]
    ax.barh(y, [v for _, v in rows], color=[BLUE, "#6F98AC", "#6F98AC", "#6F98AC"],
            height=0.6)
    for pos, (_, value) in zip(y, rows):
        ax.text(value + 1.5, pos, number(value, lang, 2), ha="left", va="center",
                fontsize=10, color=INK)
    ax.axvline(100, color=INK, ls="--", lw=1.0)
    ax.text(99, len(rows) - 0.35, t["bound"], ha="right", va="center", fontsize=9.5,
            color=INK)
    ax.set_yticks(y, [label for label, _ in rows], fontsize=10)
    ax.set(xlim=(0, 140), ylim=(-0.5, len(rows) - 0.1))
    ax.set_xlabel(t["axis"], fontsize=10)
    ax.tick_params(axis="x", labelsize=9)
    clean(ax)
    fig.tight_layout()
    save(fig, output, "u280_line_rate", lang)


def budget(lang: str, output: Path) -> None:
    t, luts, power = TEXT[lang], DATA["lut_by_block"], DATA["power_w"]
    total = DATA["utilization"]["lut"]["used"]
    fig, ax = plt.subplots(figsize=(6.4, 1.9))
    left = 0.0
    for key, colour in SHADES.items():
        share = 100 * luts[key] / total
        ax.barh(1, share, left=left, color=colour, edgecolor="white", height=0.55)
        if share > 6:
            ax.text(left + share / 2, 1, f"{number(share, lang, 0)}%", ha="center", va="center",
                    fontsize=9.5, color="white" if colour in (BLUE, "#6F98AC") else INK)
        left += share
    parts = [(t["static"], power["static"], "#D9D9D6"), (t["core"], power["prism_core"], BLUE),
             (t["port"], power["port_100g"], "#9A9A96"), ("", power["other"], "#EDEDEA")]
    left = 0.0
    for label, watts, colour in parts:
        share = 100 * watts / power["total"]
        ax.barh(0, share, left=left, color=colour, edgecolor="white", height=0.55)
        if label:
            ax.text(left + share / 2, 0, f"{label} {number(watts, lang)} W", ha="center",
                    va="center", fontsize=9.5, color="white" if colour == BLUE else INK)
        left += share
    ax.set_yticks([1, 0], [t["luts"], t["power"]], fontsize=10)
    ax.text(100, 1.42, t["lut_total"], ha="right", fontsize=9, color=MUTED)
    ax.text(100, 0.42, t["power_total"], ha="right", fontsize=9, color=MUTED)
    ax.set(xlim=(0, 100), ylim=(-0.45, 1.6))
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"], fontsize=9)
    clean(ax)
    handles = [Patch(color=c, label=t[k]) for k, c in SHADES.items()]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=3,
              fontsize=9, frameon=False, handlelength=1.2, columnspacing=1.2)
    save(fig, output, "u280_budget", lang)


def placement(lang: str, output: Path) -> None:
    t = TEXT[lang]
    image = plt.imread(HERE / "u280-placement-vivado.png")
    height, width = image.shape[:2]
    fig, ax = plt.subplots(figsize=(2.5, 4.1))
    ax.imshow(image, extent=(0, width, height, 0))
    for top, bottom, name in ((0, 268, "SLR2"), (268, 540, "SLR1"), (540, 852, "SLR0")):
        ax.text(width + 14, (top + bottom) / 2, name, fontsize=10, color=INK, va="center")
    ax.text(width + 14, 828, "HBM", fontsize=9, color=MUTED, va="center")
    # CMACE4_X0Y6 drives QSFP0 from the left column of SLR2 (clock region X0Y10).
    ax.add_patch(plt.Rectangle((3, 73), 31, 61, fill=False, ec="white", lw=1.2))
    ax.set(xlim=(0, width), ylim=(height, 0))
    ax.axis("off")
    handles = [Patch(color=c, label=t[k]) for k, c in VIVADO.items()]
    handles.append(Patch(facecolor="black", edgecolor="white", label=t["cmac"]))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.01), fontsize=9,
              frameon=False, handlelength=1.2, borderaxespad=0)
    save(fig, output, "u280_placement", lang)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for lang in ("en", "it"):
        line_rate(lang, args.output)
        budget(lang, args.output)
        placement(lang, args.output)


if __name__ == "__main__":
    main()
