"""Infrastructure smoke test only; this does not claim PRISM RTL integration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from prism_experiments.rtl import RtlDevice, run_cocotb


def test_invalid_device_parameters_rejected(tmp_path):
    source = tmp_path / "fixture.sv"
    source.write_text("module fixture; endmodule")
    with pytest.raises(ValueError, match="integer values"):
        RtlDevice("fixture", (source,), {"WIDTH": True})
    with pytest.raises(ValueError, match="duplicate RTL source"):
        RtlDevice("fixture", (source, source))
    parameters = {"WIDTH": 8}
    device = RtlDevice("fixture", (source,), parameters)
    parameters["WIDTH"] = 16
    assert device.parameters["WIDTH"] == 8
    with pytest.raises(TypeError):
        device.parameters["WIDTH"] = 16


@pytest.mark.skipif(
    shutil.which("verilator") is None, reason="requires Verilator toolchain"
)
def test_real_simulator_build_cache_and_manifest(tmp_path: Path):
    source = tmp_path / "fixture.sv"
    source.write_text("""
module fixture #(parameter WIDTH = 8)(
    input logic clk, input logic [WIDTH-1:0] value,
    output logic [WIDTH-1:0] observed
);
    always_ff @(posedge clk) observed <= value;
endmodule
""")
    callback = tmp_path / "src/smoke/fixture_scenario.py"
    callback.parent.mkdir(parents=True)
    callback.write_text("""
import json
import os
from pathlib import Path
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def observe(dut):
    run = Path(os.environ["PRISM_EXPERIMENT_RUN"])
    manifest = json.loads((run / "device.json").read_text())
    assert len(dut.value) == manifest["parameters"]["WIDTH"]
    dut.clk.value = 0
    dut.value.value = 37
    await Timer(2, unit="ns")
    dut.clk.value = 1
    await Timer(2, unit="ns")
    assert int(dut.observed.value) == 37
    (run / "samples.json").write_text(json.dumps([{"observed": 37}]))
""")
    identities = []
    build_stamps = []
    for index, width in enumerate((8, 8, 16)):
        output = tmp_path / f"run{index}"
        output.mkdir()
        run_cocotb(
            RtlDevice("fixture", (source,), {"WIDTH": width}),
            root=tmp_path,
            experiment=tmp_path,
            module="src.smoke.fixture_scenario",
            run_dir=output,
        )
        manifest = json.loads((output / "device.json").read_text())
        identities.append(manifest["build_id"])
        build_stamps.append(
            (tmp_path / manifest["build_directory"] / ".complete").stat().st_mtime_ns
        )
        assert json.loads((output / "samples.json").read_text()) == [{"observed": 37}]
    assert identities[0] == identities[1] != identities[2]
    assert build_stamps[0] == build_stamps[1]
