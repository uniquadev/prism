"""CCL-owned Python test execution."""

from __future__ import annotations

import sys

from .context import CCL_ROOT, python_environment, run


def run_python_tests(directory: str, pattern: str = "test_*.py") -> None:
    run(
        [sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", pattern, "-v"],
        cwd=CCL_ROOT,
        env=python_environment(),
    )


def run_python_coverage() -> None:
    run([sys.executable, "-m", "coverage", "erase"], cwd=CCL_ROOT)
    for index, directory in enumerate(("tests/unit", "tests/integration")):
        command = [sys.executable, "-m", "coverage", "run"]
        if index:
            command.append("--append")
        command.extend(
            [
                "--branch",
                "--source=prism_ccl",
                "-m",
                "unittest",
                "discover",
                "-s",
                directory,
                "-p",
                "test_*.py",
                "-v",
            ]
        )
        run(command, cwd=CCL_ROOT, env=python_environment())
    run(
        [sys.executable, "-m", "coverage", "report", "--show-missing", "--fail-under=75"],
        cwd=CCL_ROOT,
    )
