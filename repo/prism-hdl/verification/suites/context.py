"""Shared paths and process helpers for verification suites."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
HDL_ROOT = REPO_ROOT / "repo" / "prism-hdl"
CCL_ROOT = REPO_ROOT / "repo" / "prism-ccl"
BUILD_ROOT = Path(os.environ.get("PRISM_BUILD_DIR", REPO_ROOT / "build" / "prism-hdl"))


@contextmanager
def exclusive_run() -> Iterator[None]:
    """Reject concurrent runners that would write the same build tree."""

    lock_path = BUILD_ROOT.parent / f".{BUILD_ROOT.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        lock.seek(0)
        lock.write(b"\0")
        lock.flush()
        try:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SystemExit(
                f"ERROR: another PRISM verification run is using {BUILD_ROOT}"
            ) from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def run(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("[prism] " + " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def python_environment() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(CCL_ROOT / "src"), str(HDL_ROOT / "verification")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PRISM_BUILD_DIR"] = str(BUILD_ROOT)
    env["PRISM_TRACE_ROOT"] = str(HDL_ROOT / "verification" / "traces")
    return env


def require_program(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise SystemExit(f"ERROR: required program is unavailable: {name}")
    return resolved


def show_environment() -> None:
    print(f"repository={REPO_ROOT}")
    print(f"python={sys.executable}")
    print(f"python_version={sys.version.split()[0]}")
    print(f"verilator={shutil.which('verilator') or 'unavailable'}")
    print(f"docker={shutil.which('docker') or 'unavailable'}")
    print(f"tshark={shutil.which('tshark') or 'unavailable'}")
    print(f"build_dir={BUILD_ROOT}")


def clean() -> None:
    resolved = BUILD_ROOT.resolve()
    repository = REPO_ROOT.resolve()
    if repository not in resolved.parents:
        raise SystemExit(f"ERROR: refusing to clean build directory outside repository: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
        print(f"[prism] removed {resolved}")
