"""Check that a one-port core has valid elaborated indices and slices."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HDL = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("port_count", (1, 2))
def test_collective_core_port_ranges(port_count: int) -> None:
    verilator = shutil.which("verilator")
    if verilator is None:
        pytest.skip("Verilator is not installed")

    result = subprocess.run(
        (
            verilator,
            "--lint-only",
            "--timing",
            "-Wno-fatal",
            "--top-module",
            "prism_collective_core",
            f"-GNUM_PORTS={port_count}",
            "-f",
            "rtl.f",
        ),
        cwd=HDL,
        capture_output=True,
        text=True,
        check=False,
    )
    diagnostics = result.stdout + result.stderr
    assert result.returncode == 0, diagnostics
    assert "%Warning-ASCRANGE" not in diagnostics, diagnostics
    assert "%Warning-SELRANGE" not in diagnostics, diagnostics
