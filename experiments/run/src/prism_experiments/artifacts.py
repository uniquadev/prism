"""Explicit run directories and source provenance; never overwrite a previous run."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def repository_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "repo/prism-ccl/pyproject.toml").is_file():
            return candidate
    raise ValueError("cannot find PRISM repository; pass an experiment inside its checkout")


def portable(path: Path | str, root: Path) -> str:
    """A recorded path: relative to the checkout, or only its name outside it."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.name


def new_run(root: Path, name: str, destination: Path | None = None) -> Path:
    path = destination or root / "build/experiments" / name / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_identity(root: Path, experiment: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unavailable"

    paths = [
        *experiment.glob("*.py"),
        *experiment.glob("src/**/*.py"),
        experiment / "pyproject.toml",
        experiment / "uv.lock",
    ]
    paths += list((root / "repo/prism-ccl/src").rglob("*.py"))
    paths += list((root / "repo/prism-hdl/verification/ccl").glob("*.py"))
    paths += list((root / "experiments/run/src").rglob("*.py"))
    return {
        "git_revision": git("rev-parse", "HEAD"),
        "git_dirty": git("status", "--porcelain") not in ("", "unavailable"),
        "python": platform.python_version(),
        "platform": platform.system(),
        "sources": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths))
        },
    }
