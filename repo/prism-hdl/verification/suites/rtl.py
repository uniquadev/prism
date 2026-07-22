"""RTL elaboration, parameter, and Cocotb suite mechanics."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import tempfile
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
) -> None:
    try:
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
    digest.update(top.encode())
    digest.update(json.dumps(parameters or {}, sort_keys=True).encode())
    for source in rtl_sources():
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
        sources=rtl_sources(),
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
        (
            "single-port-narrow",
            {
                "NUM_PORTS": 1,
                "INGRESS_FIFO_DEPTH": 32,
                "EGRESS_FIFO_DEPTH": 32,
                "WORK_FIFO_DEPTH": 16,
                "OPERATION_CONTEXTS": 4,
                "ACCUMULATOR_RANGES": 16,
                "LANES": 8,
                "WIDTH_COUNT": 1,
                "WIDTH_0": 64,
                "WIDTH_1": 64,
                "WIDTH_2": 64,
            },
        ),
        (
            "compact",
            {"NUM_PORTS": 2, "WIDTH_COUNT": 2, "WIDTH_0": 64, "WIDTH_1": 288, "WIDTH_2": 288},
        ),
        (
            "default",
            {"NUM_PORTS": 2, "WIDTH_COUNT": 3, "WIDTH_0": 64, "WIDTH_1": 288, "WIDTH_2": 320},
        ),
        (
            "four-port",
            {
                "NUM_PORTS": 4,
                "INGRESS_FIFO_DEPTH": 128,
                "EGRESS_FIFO_DEPTH": 128,
                "WORK_FIFO_DEPTH": 16,
                "OPERATION_CONTEXTS": 12,
                "ACCUMULATOR_RANGES": 32,
                "LANES": 8,
                "WIDTH_COUNT": 2,
                "WIDTH_0": 64,
                "WIDTH_1": 288,
                "WIDTH_2": 288,
            },
        ),
    )
    for name, parameters in configurations:
        output = BUILD_ROOT / "parameters" / f"{name}.xml"
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "verilator",
            "--xml-only",
            "--timing",
            "--sv",
            "-Wall",
            "-Wno-fatal",
            "-Wno-MULTITOP",
            # Matrix tops intentionally override defaults from the package superset.
            "-Wno-UNUSEDPARAM",
            "--top-module",
            "prism_collective_core",
            "--xml-output",
            str(output),
        ]
        command.extend(f"-G{key}={value}" for key, value in parameters.items())
        command.extend(["-f", str(HDL_ROOT / "rtl.f")])
        run(command, cwd=HDL_ROOT)
        xml = output.read_text(encoding="utf-8")
        if parameters["WIDTH_COUNT"] == 1 and 'name="u_kulisch_1"' in xml:
            raise SystemExit("ERROR: disabled Kulisch width-1 converter survived elaboration")
        if parameters["WIDTH_COUNT"] < 3 and 'name="u_kulisch_2"' in xml:
            raise SystemExit("ERROR: disabled Kulisch width-2 converter survived elaboration")
        if parameters["WIDTH_COUNT"] > 1 and 'name="u_kulisch_1"' not in xml:
            raise SystemExit("ERROR: enabled Kulisch width-1 converter is absent")
        if parameters["WIDTH_COUNT"] > 2 and 'name="u_kulisch_2"' not in xml:
            raise SystemExit("ERROR: enabled Kulisch width-2 converter is absent")
