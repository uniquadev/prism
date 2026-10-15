"""Compile a device once and run a cocotb experiment against its actual DUT."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType

from .artifacts import portable, write_json


@dataclass(frozen=True)
class RtlDevice:
    """One source of truth for elaboration, recorded unchanged in the run manifest."""

    top: str
    sources: tuple[Path, ...]
    parameters: Mapping[str, int] = field(default_factory=dict)
    clock_period_ns: int = 4

    def __post_init__(self) -> None:
        if not self.top.isidentifier() or self.clock_period_ns <= 0 or not self.sources:
            raise ValueError("device needs an HDL top, sources, and a positive clock period")
        if any(
            not key.isidentifier() or type(value) is not int
            for key, value in self.parameters.items()
        ):
            raise ValueError("RTL parameters must have identifier names and integer values")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "sources", tuple(self.sources))
        if len(set(path.resolve() for path in self.sources)) != len(self.sources):
            raise ValueError("duplicate RTL source")
        for path in self.sources:
            if not path.is_file():
                raise ValueError(f"missing RTL source: {path}")


def read_manifest(hdl: Path, manifest: str = "rtl.f") -> tuple[Path, ...]:
    return tuple(
        (hdl / line.strip()).resolve()
        for line in (hdl / manifest).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//"))
    )


def run_cocotb(
    device: RtlDevice, *, root: Path, experiment: Path, module: str, run_dir: Path
) -> None:
    """One simulator launch; the named module may run many samples with one backend.

    This compiles RTL and never substitutes a software model. The Cocotb
    callback may use the shared PrismWorld SINGLE binding in verification/ccl.
    """
    if shutil.which("verilator") is None:
        raise RuntimeError("Verilator is required: use WSL/Linux or the --docker launcher")
    import cocotb
    from cocotb_tools.runner import get_results, get_runner

    toolchain = subprocess.check_output(["verilator", "--version"], text=True).strip()
    blobs = [
        (path.resolve().relative_to(root.resolve()), path.read_bytes()) for path in device.sources
    ]
    manifest = {
        "top": device.top,
        "parameters": dict(device.parameters),
        "clock_period_ns": device.clock_period_ns,
        "simulator": toolchain,
        "cocotb": version("cocotb"),
        "python": portable(sys.executable, root),
        "runtime": portable(Path(cocotb.__file__).parent, root),
        "build_args": ["--timing", "-Wno-fatal", "-Wno-MULTITOP"],
        "sources": {str(path): hashlib.sha256(data).hexdigest() for path, data in blobs},
    }
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    build = root / "build/cache/experiments" / fingerprint
    build.mkdir(parents=True, exist_ok=True)
    lock = build / ".lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise RuntimeError(f"build in use: {build}; wait for that run to finish") from error
    try:
        sources = []
        # Immutable source snapshot: an ongoing RTL edit cannot change this build midway.
        for relative, data in blobs:
            path = build / "sources" / relative
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            elif path.read_bytes() != data:
                raise RuntimeError(f"modified cached source snapshot: {path}")
            sources.append(path)
        manifest["build_id"] = fingerprint
        manifest["build_directory"] = portable(build, root)
        write_json(run_dir / "device.json", manifest)
        runner = get_runner("verilator")
        if not (build / ".complete").is_file() or not (build / device.top).is_file():
            runner.build(
                sources=sources,
                hdl_toplevel=device.top,
                parameters=dict(device.parameters),
                build_dir=build,
                build_args=manifest["build_args"],
                always=True,
            )
            (build / ".complete").write_text(fingerprint, encoding="utf-8")
        # Cocotb's runner derives PYTHONPATH from sys.path, not extra_env.
        callback_paths = (str(experiment), str(root / "repo/prism-hdl/verification"))
        sys.path[:0] = callback_paths
        try:
            result = runner.test(
                hdl_toplevel=device.top,
                hdl_toplevel_lang="verilog",
                parameters=dict(device.parameters),
                test_module=module,
                test_dir=experiment,
                build_dir=build,
                results_xml=str(run_dir / "cocotb-results.xml"),
                extra_env={"PRISM_EXPERIMENT_RUN": str(run_dir)},
            )
        finally:
            for path in callback_paths:
                sys.path.remove(path)
        total, failed = get_results(result)
        if not total or failed:
            raise RuntimeError(f"RTL experiment failed: {failed}/{total}; inspect {run_dir}")
        if not (run_dir / "samples.json").is_file():
            raise RuntimeError("RTL callback completed without writing measurements")
    finally:
        lock.rmdir()
