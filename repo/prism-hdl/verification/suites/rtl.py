"""RTL elaboration, parameter, and Cocotb suite mechanics."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .context import BUILD_ROOT, HDL_ROOT, python_environment, require_program, run


def rtl_sources() -> list[Path]:
    manifests = (HDL_ROOT / "rtl.f", HDL_ROOT / "verification" / "rtl.f")
    missing_manifests = [manifest for manifest in manifests if not manifest.exists()]
    if missing_manifests:
        raise SystemExit(
            "ERROR: missing RTL manifest(s):\n" + "\n".join(str(path) for path in missing_manifests)
        )
    sources = [
        HDL_ROOT / line.strip()
        for manifest in manifests
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    missing = [source for source in sources if not source.exists()]
    if missing:
        raise SystemExit(
            "ERROR: missing RTL source(s):\n" + "\n".join(str(path) for path in missing)
        )
    return sources


def run_cocotb(
    top: str,
    test_module: str,
    *,
    parameters: dict[str, int] | None = None,
    extra_sources: Sequence[Path] = (),
    extra_build_args: Sequence[str] = (),
) -> None:
    try:
        import cocotb
        from cocotb_tools.runner import get_results, get_runner
    except ImportError as exc:
        raise SystemExit("ERROR: cocotb is required for RTL simulation suites") from exc

    build_dir = BUILD_ROOT / test_module
    toolchain = (
        subprocess.check_output([require_program("verilator"), "--version"], text=True).strip()
        + "|cocotb="
        + importlib.metadata.version("cocotb")
    )
    digest = hashlib.sha256()
    digest.update(toolchain.encode())
    # Generated makefiles and simulator binaries reference this runtime's
    # absolute paths. Equal package versions in a new isolated uv environment
    # cannot safely reuse a binary linked against a deleted environment.
    digest.update(str(Path(cocotb.__file__).resolve().parent).encode())
    digest.update(sys.executable.encode())
    digest.update(top.encode())
    digest.update(json.dumps(parameters or {}, sort_keys=True).encode())
    digest.update(json.dumps(list(extra_build_args)).encode())
    sources = [*rtl_sources(), *extra_sources]
    for source in sources:
        digest.update(source.as_posix().encode())
        digest.update(source.read_bytes())
    signature = digest.hexdigest()
    stamp = build_dir / ".prism-build"
    if stamp.exists() and stamp.read_text(encoding="utf-8") != signature:
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    executable = build_dir / top
    needs_build = not executable.exists()
    if not stamp.exists() and executable.exists():
        stamp.write_text(signature, encoding="utf-8")

    os.environ.update(python_environment())
    runner = get_runner("verilator")
    runner.build(
        sources=sources,
        hdl_toplevel=top,
        build_dir=build_dir,
        parameters=parameters or {},
        build_args=[
            "--timing",
            "-Wall",
            "-Wno-fatal",
            "-Wno-MULTITOP",
            # Focused tops compile the complete package and manifest superset.
            "-Wno-UNUSEDPARAM",
            *extra_build_args,
        ],
        always=needs_build,
    )
    stamp.write_text(signature, encoding="utf-8")
    retain_xml = os.environ.get("PRISM_XML_RESULTS") == "1"
    with tempfile.TemporaryDirectory(prefix="prism-cocotb-") as temporary_directory:
        if retain_xml:
            results_directory = BUILD_ROOT / "results"
            results_directory.mkdir(parents=True, exist_ok=True)
            results_xml = results_directory / f"{test_module.replace('.', '_')}.results.xml"
        else:
            results_xml = Path(temporary_directory) / "results.xml"

        # A test that depends on a parameter of its build reads it here.
        os.environ["PRISM_PARAMETERS"] = json.dumps(parameters or {}, sort_keys=True)
        results = runner.test(
            hdl_toplevel=top,
            test_module=test_module,
            test_dir=HDL_ROOT / "verification",
            build_dir=build_dir,
            results_xml=str(results_xml),
        )
        total, failed = get_results(results)
        if total == 0 or failed:
            raise SystemExit(f"ERROR: Cocotb suite {test_module} failed {failed} of {total} tests")


def run_parameter_matrix() -> None:
    require_program("verilator")
    configurations = (
        ("single-two-port-minimum-mtu", "prism_collective_core", {"NUM_PORTS": 2, "LINK_MTU": 576}),
        ("single-two-port-default", "prism_collective_core", {"NUM_PORTS": 2}),
        (
            "single-two-port-kulisch-only",
            "prism_collective_core",
            {"NUM_PORTS": 2, "ENABLE_FP32_ACCUMULATION": 0},
        ),
        ("single-four-port", "prism_collective_core", {"NUM_PORTS": 4}),
        ("single-eight-port", "prism_collective_core", {"NUM_PORTS": 8}),
        (
            "partial-minimum-width",
            "prism_numbergroup_auto_partial_sender",
            {"KULISCH_W": 278, "MTU_BYTES": 576},
        ),
        (
            "partial-default-width",
            "prism_numbergroup_auto_partial_sender",
            {"KULISCH_W": 320, "MTU_BYTES": 576},
        ),
        (
            "partial-maximum-local-elements",
            "prism_numbergroup_auto_partial_sender",
            {"KULISCH_W": 320, "MTU_BYTES": 1500},
        ),
    )
    for name, top, parameters in configurations:
        print(f"[prism] parameter-profile={name}")
        command = [
            "verilator",
            "--lint-only",
            "--timing",
            "--sv",
            "-Wall",
            "-Wno-fatal",
            "-Wno-MULTITOP",
            "-Wno-UNUSEDPARAM",
            "--top-module",
            top,
        ]
        command.extend(f"-G{key}={value}" for key, value in parameters.items())
        command.extend(["-f", str(HDL_ROOT / "rtl.f")])
        run(command, cwd=HDL_ROOT)
