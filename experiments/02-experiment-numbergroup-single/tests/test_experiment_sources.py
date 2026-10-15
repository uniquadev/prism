"""A thesis sweep must not silently mix RTL source revisions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "src/numbergroup_single/experiment_tools.py"
spec = importlib.util.spec_from_file_location("numbergroup_experiment", SCRIPT)
assert spec and spec.loader
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def test_reference_device_uses_verified_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = Path("repo/prism-hdl/src/test.sv")
    live = tmp_path / relative
    live.parent.mkdir(parents=True)
    live.write_bytes(b"new source")
    build = tmp_path / "build"
    frozen = build / "sources" / relative
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"verified source")
    reference = tmp_path / "device.json"
    reference.write_text(
        json.dumps(
            {
                "top": "prism_sim_top",
                "build_directory": str(build),
                "sources": {relative.as_posix(): hashlib.sha256(frozen.read_bytes()).hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(experiment, "ROOT", tmp_path)
    monkeypatch.setattr(
        experiment,
        "read_manifest",
        lambda _hdl, manifest="rtl.f": (tmp_path / "changed_manifest.sv",),
    )
    assert experiment.rtl_sources(reference) == (frozen,)

    frozen.write_bytes(b"tampered source")
    with pytest.raises(ValueError, match="changed RTL snapshot"):
        experiment.rtl_sources(reference)
