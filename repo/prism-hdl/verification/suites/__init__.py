"""Named PRISM verification suites and their composition."""

from __future__ import annotations

from collections.abc import Callable

from .ccl import run_python_coverage, run_python_tests
from .context import clean, exclusive_run, show_environment
from .quality import lint_python, lint_rtl
from .rtl import run_cocotb, run_parameter_matrix


def build() -> None:
    """Validate that the complete RTL top elaborates cleanly."""

    lint_rtl()


def lint() -> None:
    lint_rtl()
    lint_python()


def ccl_unit() -> None:
    run_python_tests("tests/unit")


def verification_unit() -> None:
    run_python_tests("../prism-hdl/verification/tests/unit", "test_ccl_adapter.py")
    run_python_tests("../prism-hdl/verification/tests/unit", "test_capture.py")


def formats() -> None:
    run_cocotb("prism_fp32_add", "tests.unit.test_formats_cocotb")
    run_cocotb(
        "prism_fp_input_converter",
        "tests.unit.test_input_converter_cocotb",
        parameters={"LANES": 4},
    )
    run_cocotb(
        "prism_kulisch_width_selector",
        "tests.unit.test_kulisch_width_selector_cocotb",
        parameters={"WIDTH_COUNT": 2, "WIDTH_0": 64, "WIDTH_1": 288},
    )
    run_cocotb(
        "prism_kulisch_input_converter",
        "tests.unit.test_kulisch_input_converter_cocotb",
        parameters={"ACC_W": 288, "LANES": 4},
    )
    run_cocotb(
        "prism_kulisch_input_converter",
        "tests.unit.test_kulisch_deposit_saturation_cocotb",
        parameters={"ACC_W": 16, "LANES": 4},
    )
    run_cocotb(
        "prism_kulisch_finalize_array",
        "tests.unit.test_kulisch_finalize_cocotb",
        parameters={"ACC_W": 320, "LANES": 4},
    )
    run_cocotb(
        "prism_fp_output_converter",
        "tests.unit.test_output_converter_cocotb",
        parameters={"LANES": 4},
    )


def backpressure() -> None:
    run_cocotb(
        "prism_axis_skid_buffer",
        "tests.unit.test_backpressure_cocotb",
        parameters={"DATA_W": 64, "USER_W": 1},
    )
    run_cocotb(
        "prism_elastic_fifo",
        "tests.unit.test_fifo_cocotb",
        parameters={"WIDTH": 16, "DEPTH": 5},
    )
    run_cocotb(
        "prism_axis_frame_fifo",
        "tests.unit.test_axis_frame_fifo_cocotb",
        parameters={"DATA_W": 32, "USER_W": 2, "DEPTH": 5, "MAX_FRAME_BEATS": 3},
    )


def control() -> None:
    run_cocotb("prism_tlv_decoder", "tests.unit.test_control_cocotb")
    run_cocotb(
        "prism_control_reassembler",
        "tests.unit.test_control_reassembler_cocotb",
        parameters={
            "CONTEXTS": 2,
            "CAPACITY_BYTES": 12,
            "MAX_FRAGMENT_BYTES": 8,
            "TIMEOUT_CYCLES": 32,
        },
    )
    run_cocotb(
        "prism_axi_lite_null_slave",
        "tests.unit.test_axi_lite_null_slave_cocotb",
        parameters={"INTERFACES": 2},
    )


def arbitration() -> None:
    run_cocotb(
        "prism_tile_arbiter",
        "tests.unit.test_tile_arbiter_cocotb",
        parameters={"PORTS": 2, "LANES": 4},
    )
    run_cocotb(
        "prism_axis_frame_arbiter",
        "tests.unit.test_frame_arbiter_cocotb",
        parameters={"DATA_W": 32, "USER_W": 1},
    )


def ccl_integration() -> None:
    run_python_tests("tests/integration")


def rtl_integration() -> None:
    run_cocotb("prism_sim_top", "tests.integration.test_integration_cocotb")


SUITES: dict[str, Callable[[], None]] = {
    "quality": lint,
    "ccl-coverage": run_python_coverage,
    "ccl-unit": ccl_unit,
    "verification-unit": verification_unit,
    "parameters": run_parameter_matrix,
    "rtl-control": control,
    "rtl-arbitration": arbitration,
    "rtl-formats": formats,
    "rtl-backpressure": backpressure,
    "rtl-pipeline": lambda: run_cocotb("prism_reduce_harness", "tests.unit.test_pipeline_cocotb"),
    "rtl-throughput": lambda: run_cocotb(
        "prism_reduce_harness",
        "tests.unit.test_pipeline_throughput_cocotb",
        parameters={"LANES": 16, "RANGES": 64},
    ),
    "wireshark": lambda: run_python_tests("tests/wireshark"),
    "ccl-integration": ccl_integration,
    "rtl-integration": rtl_integration,
}
SUITE_NAMES = tuple(SUITES)
ALL_SUITE_NAMES = tuple(name for name in SUITE_NAMES if name not in {"ccl-unit", "ccl-integration"})


def run_suite(name: str) -> None:
    SUITES[name]()


__all__ = (
    "ALL_SUITE_NAMES",
    "SUITE_NAMES",
    "build",
    "clean",
    "exclusive_run",
    "lint",
    "run_suite",
    "show_environment",
)
