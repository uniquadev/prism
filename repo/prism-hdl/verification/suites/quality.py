"""Static RTL and Python quality checks."""

from __future__ import annotations

from .context import CCL_ROOT, HDL_ROOT, require_program, run


def lint_rtl() -> None:
    require_program("verilator")
    tops = (
        ("prism_sim_top", (HDL_ROOT / "verification" / "rtl.f",)),
        ("prism_vivado_top", ()),
        ("prism_open_nic_250mhz", ()),
    )
    for top, extra_manifests in tops:
        command = [
            "verilator",
            "--lint-only",
            "--timing",
            "--sv",
            "-Wall",
            "-Wno-fatal",
            "-Wno-MULTITOP",
            "--top-module",
            top,
            "-f",
            str(HDL_ROOT / "rtl.f"),
        ]
        for manifest in extra_manifests:
            command.extend(("-f", str(manifest)))
        run(command, cwd=HDL_ROOT)


def lint_python() -> None:
    require_program("ruff")
    require_program("mypy")
    targets = [str(CCL_ROOT / "src"), str(CCL_ROOT / "tests"), str(HDL_ROOT / "verification")]
    run(["ruff", "format", "--check", *targets])
    run(["ruff", "check", *targets])
    run(
        [
            "mypy",
            "--config-file",
            str(CCL_ROOT / "pyproject.toml"),
            str(CCL_ROOT / "src"),
            str(HDL_ROOT / "verification" / "ccl"),
        ]
    )
