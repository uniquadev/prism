"""Shared, dependency-free helpers for PRISM Vivado build commands."""

from __future__ import annotations

import os
import re
import shutil
import string
import subprocess
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

BOARD_VERSIONS = {
    "au280": "v2022.1",
}
# The OpenNIC shell whose CMAC subsystem and packet adapter the U280 build uses.
OPEN_NIC_COMMIT = "940907fc99fc8d73dbea0028b3a23095a660a42a"


def repository_root(start: Path) -> Path:
    """Find the repository root without depending on the caller's cwd."""
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "Makefile").is_file() and (candidate / "repo" / "prism-hdl").is_dir():
            return candidate
    raise RuntimeError(f"repository root was not found above '{start}'")


def bounded_integer(minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        parsed = int(value)
        if not minimum <= parsed <= maximum:
            raise ValueError(f"expected an integer in {minimum}..{maximum}")
        return parsed

    return parse


def _vivado_command(executable: Path, arguments: Sequence[str]) -> list[str]:
    command = [str(executable), *map(str, arguments)]
    if os.name == "nt" and executable.suffix.lower() in {".bat", ".cmd"}:
        command_line = subprocess.list2cmdline(command)
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
    return command


def windows_vivado_roots(board: str) -> Iterator[Path]:
    """Yield common Vivado layouts without embedding one workstation path."""
    version = BOARD_VERSIONS[board].removeprefix("v")
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        yield drive / "AMDDesignTools" / "Vivado" / version
        yield drive / "AMDDesignTools" / version / "Vivado"
        yield drive / "Xilinx" / "Vivado" / version


def resolve_vivado(board: str, override: str | None) -> Path:
    configured = override or os.environ.get(f"VIVADO_{board.upper()}")
    configured = configured or os.environ.get("VIVADO")
    executable_name = "vivado.bat" if os.name == "nt" else "vivado"

    if configured is not None:
        candidate = Path(configured).expanduser()
        if candidate.is_dir():
            candidate = candidate / "bin" / executable_name
        elif not candidate.is_file():
            discovered = shutil.which(configured)
            if discovered:
                candidate = Path(discovered)
        if not candidate.is_file():
            raise RuntimeError(f"configured Vivado for {board} was not found at '{configured}'")
        return candidate.resolve()

    if os.name == "nt":
        for root in windows_vivado_roots(board):
            candidate = root / "bin" / executable_name
            if candidate.is_file():
                return candidate.resolve()

    discovered = shutil.which("vivado")
    if discovered:
        return Path(discovered).resolve()

    raise RuntimeError(
        f"Vivado for {board} was not found in PATH or a common installation directory"
    )


def run_vivado(
    executable: Path,
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _vivado_command(executable, arguments),
        cwd=cwd,
        env=environment,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def vivado_version_output(executable: Path) -> str:
    """Return Vivado's version banner or fail if it cannot be identified."""
    # Some Vivado Windows launchers return 1 for the informational -version
    # command even though the version output is valid.
    result = run_vivado(executable, ["-version"], capture_output=True, check=False)
    output = result.stdout.strip()
    if not output:
        raise RuntimeError(f"Vivado version could not be read from '{executable}'")
    return output


def vivado_version(executable: Path) -> str:
    """Return Vivado's first version line."""
    return vivado_version_output(executable).splitlines()[0]


def verify_vivado_version(board: str, executable: Path) -> None:
    first_line = vivado_version(executable)
    expected = BOARD_VERSIONS[board]
    if expected not in first_line:
        raise RuntimeError(f"{board} requires Vivado {expected}; found '{first_line}'")


def build_environment(license_files: Sequence[str] | None) -> dict[str, str]:
    environment = os.environ.copy()
    if license_files:
        resolved = []
        for value in license_files:
            path = Path(value).expanduser().resolve()
            if not path.is_file():
                raise RuntimeError(f"Vivado license file was not found at '{path}'")
            resolved.append(str(path))
        environment["XILINXD_LICENSE_FILE"] = os.pathsep.join(resolved)
    return environment


def run_checked(arguments: Sequence[str], *, cwd: Path | None = None) -> None:
    subprocess.run(list(map(str, arguments)), cwd=cwd, check=True)


@contextmanager
def short_build_root(root: Path, drive_letter: str) -> Iterator[Path]:
    """Map the OpenNIC tree to a short Windows drive for Vivado."""
    if os.name != "nt":
        yield root
        return

    drive = f"{drive_letter.upper()}:"
    mapping_pattern = re.compile(rf"^{re.escape(drive)}\\: => (?P<target>.+)$", re.IGNORECASE)
    listing = subprocess.run(
        ["subst"], check=True, text=True, capture_output=True
    ).stdout.splitlines()
    existing = next(
        (match.group("target") for line in listing if (match := mapping_pattern.match(line))),
        None,
    )
    created = False
    if existing is not None:
        if Path(existing).resolve() != root.resolve():
            raise RuntimeError(f"{drive} is already mapped to '{existing}'")
    else:
        run_checked(["subst", drive, str(root)])
        created = True

    try:
        yield Path(f"{drive}\\")
    finally:
        if created:
            run_checked(["subst", drive, "/D"])


def prepare_open_nic(shell_root: Path) -> None:
    if not (shell_root / ".git").is_dir():
        shell_root.parent.mkdir(parents=True, exist_ok=True)
        run_checked(
            ["git", "clone", "https://github.com/Xilinx/open-nic-shell.git", str(shell_root)]
        )
        run_checked(["git", "checkout", "--detach", OPEN_NIC_COMMIT], cwd=shell_root)

    head_file = shell_root / ".git" / "HEAD"
    if not head_file.exists():
        raise RuntimeError(f"'{shell_root}' is not an OpenNIC Git checkout")
    # A detached checkout names its commit in HEAD; reading it avoids Git's
    # ownership check on a checkout mounted into a container.
    actual_commit = head_file.read_text(encoding="utf-8").strip()
    if actual_commit.startswith("ref:"):
        actual_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=shell_root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    if actual_commit != OPEN_NIC_COMMIT:
        raise RuntimeError(f"OpenNIC Shell is at {actual_commit}; expected {OPEN_NIC_COMMIT}")
