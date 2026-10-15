"""Public launcher, example and documented API regressions."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from prism_experiments.artifacts import source_identity

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "experiments/01-experiment-single-reduce/experiment.py"


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


launcher = load(ROOT / "experiments/run/launch.py")


def project(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    for file in ("experiment.py", "README.md", "uv.lock"):
        (path / file).write_text("", encoding="utf-8")
    (path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")
    return path


def test_discovery_ignores_invalid_layout_and_sorts_numeric_order(tmp_path):
    project(tmp_path, "10-experiment-last")
    project(tmp_path, "02-experiment-first")
    project(tmp_path, "not-an-experiment")
    missing = project(tmp_path, "03-experiment-missing")
    (missing / "uv.lock").unlink()
    malformed = project(tmp_path, "04-experiment-malformed")
    (malformed / "pyproject.toml").write_text('project = "invalid"', encoding="utf-8")
    assert [path.name for path in launcher.discover(tmp_path)] == [
        "02-experiment-first",
        "10-experiment-last",
    ]
    with pytest.raises(ValueError, match=r"uv\.lock"):
        launcher.validate_project(missing, tmp_path)


def test_selected_path_cannot_escape_experiments(tmp_path):
    outer = project(tmp_path, "01-experiment-outside")
    inside = tmp_path / "experiments"
    inside.mkdir()
    with pytest.raises(ValueError, match="direct experiments"):
        launcher.validate_project(outer, inside)


def test_arguments_with_spaces_are_forwarded_without_a_shell():
    with (
        patch.object(launcher.shutil, "which", return_value="uv"),
        patch.object(
            launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as run,
    ):
        assert (
            launcher.main(
                [
                    "run",
                    "01-experiment-single-reduce",
                    "--",
                    "plot",
                    "--input",
                    "folder with spaces",
                ]
            )
            == 0
        )
        call = run.call_args
        assert call.args[0][-3:] == ["plot", "--input", "folder with spaces"]
        assert not call.kwargs.get("shell", False)
        assert "UV_PROJECT_ENVIRONMENT" in call.kwargs["env"]


@pytest.mark.parametrize("kind,expected_ranks", [("reduce", {"1"}), ("allreduce", {"0", "1"})])
@pytest.mark.parametrize("policy", ["kulisch-fixed", "fp32-arrival"])
def test_template_collects_verified_results(tmp_path, kind, expected_ranks, policy):
    output = tmp_path / "run"
    command = [
        sys.executable,
        str(EXPERIMENT),
        "collect",
        "--samples",
        "1",
        "--elements",
        "3",
        "--collective",
        kind,
        "--accumulator",
        policy,
        "--output",
        str(output),
    ]
    if kind == "reduce":
        command += ["--root-rank", "1"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    manifest = json.loads((output / "manifest.json").read_text())
    sample = json.loads((output / "samples.json").read_text())[0]
    assert manifest["status"] == "complete" and manifest["operator"] == "SUM"
    assert set(sample["result_fp32_bits"]) == expected_ranks
    assert sample["packet_count"]["CONTROL"] > 0 and sample["packet_count"]["DATA"] > 0
    assert "latency_cycles" not in sample
    assert manifest["provenance"]["sources"]


@pytest.mark.parametrize(
    "arguments,explanation",
    [
        (["--backend", "cocotb"], "unrecognized arguments"),
        (["--collective", "allreduce", "--root-rank", "0"], "only applies to Reduce"),
        (["--samples", "0"], "must be positive"),
    ],
)
def test_invalid_or_unsupported_modes_fail_before_creating_results(
    tmp_path, arguments, explanation
):
    output = tmp_path / "run"
    result = subprocess.run(
        [
            sys.executable,
            str(EXPERIMENT),
            "collect",
            *arguments,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and explanation in result.stderr
    assert not output.exists()


def test_plot_only_does_not_create_a_world_or_import_cocotb(tmp_path):
    module = load(EXPERIMENT)
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "backend": "software_packet_model",
        "collective": "reduce",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "samples.json").write_text(
        json.dumps([{"frame_bytes": {"DATA": 128}, "packet_count": {"DATA": 2}}])
    )
    with patch.dict(sys.modules, {"cocotb": None, "prism_ccl.world": None}):
        module.plot(tmp_path)
    assert (tmp_path / "figures/traffic.svg").stat().st_size > 0


def test_documented_software_example_runs():
    text = (ROOT / "docs/chapters/2-getting-started/ccl-experiments.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.S)
    assert blocks
    namespace = {}
    for block in blocks:
        exec(compile(block, "ccl-experiments.md", "exec"), namespace)


def test_source_identity_includes_moved_experiment_modules():
    experiment = ROOT / "experiments/02-experiment-numbergroup-single"
    sources = source_identity(ROOT, experiment)["sources"]
    assert "experiments/02-experiment-numbergroup-single/experiment.py" in sources
    callback = "experiments/02-experiment-numbergroup-single/src/numbergroup_single/rtl_callback.py"
    assert callback in sources
