"""Discover and launch experiment projects from the repository root (stdlib only)."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"[0-9]+-experiment-[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def validate_project(path: Path, experiments: Path) -> None:
    if path.resolve().parent != experiments.resolve() or not NAME.fullmatch(path.name):
        raise ValueError(
            "expected a direct experiments/<order>-experiment-<name> directory"
        )
    for name in ("experiment.py", "pyproject.toml", "uv.lock", "README.md"):
        if not (path / name).is_file():
            raise ValueError(f"missing {name}")
    config = tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = config.get("project")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise ValueError("pyproject.toml needs [project].name")


def discover(experiments: Path) -> list[Path]:
    found = []
    for path in experiments.iterdir() if experiments.is_dir() else ():
        try:
            validate_project(path, experiments)
        except (ValueError, OSError):
            continue
        found.append(path)
    return sorted(found, key=lambda path: (int(path.name.split("-", 1)[0]), path.name))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    forwarded: list[str] = []
    if "--" in args:
        boundary = args.index("--")
        args, forwarded = args[:boundary], args[boundary + 1 :]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "run"))
    parser.add_argument("experiment", nargs="?")
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--image", default="prism-experiments:dev")
    options = parser.parse_args(args)
    experiments = ROOT / "experiments"
    if options.action == "list":
        if options.experiment or forwarded:
            parser.error("list does not accept an experiment or forwarded arguments")
        for path in discover(experiments):
            print(path.name)
        return 0
    if not options.experiment:
        parser.error("run requires an experiment directory")
    supplied = Path(options.experiment)
    project = experiments / supplied if len(supplied.parts) == 1 else ROOT / supplied
    try:
        validate_project(project, experiments)
    except (ValueError, OSError) as error:
        parser.error(f"invalid experiment {options.experiment!r}: {error}")
    if options.image.startswith("-"):
        parser.error("invalid Docker image name")
    relative = project.relative_to(ROOT).as_posix()
    if options.docker:
        if not shutil.which("docker"):
            parser.error("Docker is not installed or not on PATH")
        command = [
            "docker",
            "build",
            "--target",
            "experiments",
            "-t",
            options.image,
            "-f",
            str(ROOT / "repo/prism-hdl/Dockerfile"),
            str(ROOT),
        ]
        subprocess.run(command, check=True)
        command = [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=bind,source={ROOT},target=/work",
            "--workdir",
            "/work",
            "--env",
            "UV_CACHE_DIR=/tmp/uv-cache",
            "--env",
            "UV_PROJECT_ENVIRONMENT=/tmp/experiment-venv",
            "--env",
            "HOME=/tmp",
        ]
        if hasattr(os, "getuid"):
            command += ["--user", f"{os.getuid()}:{os.getgid()}"]
        command += [
            options.image,
            "uv",
            "run",
            "--locked",
            "--no-dev",
            "--project",
            relative,
            "python",
            f"{relative}/experiment.py",
            *forwarded,
        ]
    else:
        uv = shutil.which("uv")
        if uv is None:
            parser.error("install uv, or use --docker with Docker installed")
        command = [
            uv,
            "run",
            "--locked",
            "--no-dev",
            "--project",
            str(project),
            "python",
            str(project / "experiment.py"),
            *forwarded,
        ]
    # No shell: arguments after -- retain their boundaries, including paths with spaces.
    environment = os.environ.copy()
    if not options.docker:
        environment.setdefault(
            "UV_CACHE_DIR",
            str(
                ROOT
                / "build/cache/experiment-uv"
                / f"{sys.platform}-{platform.machine().lower()}"
            ),
        )
        environment.setdefault(
            "UV_PROJECT_ENVIRONMENT",
            str(
                ROOT
                / "build/cache/experiment-env"
                / project.name
                / f"{sys.platform}-{platform.machine().lower()}"
            ),
        )
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
