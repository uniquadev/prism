"""Named PRISM verification suites and their composition."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from .ccl import run_ccl_tests, run_python_coverage, run_python_tests
from .context import HDL_ROOT, OPEN_NIC_SHELL, clean, exclusive_run, show_environment
from .quality import lint_python, lint_rtl
from .rtl import run_cocotb, run_parameter_matrix


def build() -> None:
    """Validate that the complete RTL top elaborates cleanly."""

    lint_rtl()


def lint() -> None:
    lint_rtl()
    lint_python()


def ccl_unit() -> None:
    run_ccl_tests("tests/unit")


def verification_unit() -> None:
    run_python_tests("../prism-hdl/verification/tests/unit", "test_ccl_adapter.py")
    run_python_tests("../prism-hdl/verification/tests/unit", "test_capture.py")
    run_python_tests("../prism-hdl/verification/tests/unit", "test_u280_build.py")


def formats() -> None:
    run_cocotb("prism_fp32_add", "tests.unit.test_formats_cocotb")
    run_cocotb("prism_float_to_kulisch", "tests.unit.test_kulisch_scale_cocotb")
    run_cocotb("prism_int8_to_kulisch", "tests.unit.test_int8_kulisch_scale_cocotb")
    run_cocotb(
        "prism_exact_final_round_scalar",
        "tests.unit.test_exact_final_round_scalar_cocotb",
    )
    run_cocotb(
        "prism_exact_final_round_tile",
        "tests.unit.test_exact_final_round_tile_cocotb",
    )
    run_cocotb(
        "prism_exact_result_tile_harness",
        "tests.integration.test_exact_result_tile_harness_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_native_tile_streamer",
        "tests.unit.test_fp32_result_streamer_cocotb",
    )
    run_cocotb(
        "prism_exact_result_frame_harness",
        "tests.integration.test_exact_result_frame_harness_cocotb",
    )
    run_cocotb(
        "prism_kulisch_tile_serializer16",
        "tests.unit.test_kulisch_tile_serializer16_cocotb",
    )
    run_cocotb(
        "prism_exact_kulisch_result_frame_harness",
        "tests.integration.test_exact_kulisch_result_frame_cocotb",
    )
    for width in (279, 320):
        run_cocotb(
            "prism_auto_wire_scalar",
            "tests.unit.test_auto_wire_scalar_cocotb",
            parameters={"KULISCH_W": width},
        )


def backpressure() -> None:
    run_cocotb(
        "prism_elastic_skid_buffer",
        "tests.unit.test_elastic_skid_buffer_cocotb",
        parameters={"WIDTH": 32},
    )
    # Three control copies over one word: every copy must stay in step.
    run_cocotb(
        "prism_elastic_skid_buffer",
        "tests.unit.test_elastic_skid_buffer_cocotb",
        parameters={"WIDTH": 32, "CONTROL_BITS": 12},
    )
    run_cocotb(
        "prism_elastic_split_buffer",
        "tests.unit.test_elastic_split_buffer_cocotb",
        parameters={
            "WIDTH": 40,
            "REGISTERED_WIDTH": 8,
            "PREWRITE_PAYLOAD_FREE_SLOT": 1,
            "SKID_CONTROL": 0,
        },
    )
    run_cocotb(
        "prism_elastic_split_buffer",
        "tests.unit.test_elastic_split_buffer_cocotb",
        parameters={
            "WIDTH": 40,
            "REGISTERED_WIDTH": 8,
            "PREWRITE_PAYLOAD_FREE_SLOT": 1,
            "SKID_CONTROL": 1,
        },
    )
    run_cocotb(
        "prism_axis_skid_buffer",
        "tests.unit.test_backpressure_cocotb",
        parameters={"DATA_W": 64, "USER_W": 1},
    )
    for depth in (2, 4, 5):
        run_cocotb(
            "prism_elastic_fifo",
            "tests.unit.test_fifo_cocotb",
            parameters={"WIDTH": 16, "DEPTH": depth},
        )
        run_cocotb(
            "prism_elastic_fifo",
            "tests.unit.test_fifo_conservative_cocotb",
            parameters={"WIDTH": 16, "DEPTH": depth, "READY_ON_POP": 0},
        )
        run_cocotb(
            "prism_elastic_fifo",
            "tests.unit.test_fifo_conservative_cocotb",
            parameters={
                "WIDTH": 16,
                "DEPTH": depth,
                "READY_ON_POP": 0,
                "REGISTER_READY": 1,
            },
        )
    run_cocotb(
        "prism_axis_frame_fifo",
        "tests.unit.test_axis_frame_fifo_cocotb",
        parameters={"DATA_W": 32, "USER_W": 2, "DEPTH": 5, "MAX_FRAME_BEATS": 3},
    )


def control() -> None:
    run_cocotb(
        "prism_control_frame_validator_harness",
        "tests.unit.test_control_frame_validator_cocotb",
    )
    run_cocotb(
        "prism_single_lifecycle",
        "tests.unit.test_single_lifecycle_cocotb",
        parameters={"CONTEXT_W": 32},
    )
    run_cocotb("prism_single_control_plane", "tests.integration.test_single_control_plane_cocotb")
    run_cocotb(
        "prism_cmac_bringup",
        "tests.unit.test_cmac_bringup_cocotb",
        parameters={"POLL_CYCLES": 5},
    )
    run_cocotb(
        "prism_cmac_bringup",
        "tests.unit.test_cmac_bringup_cocotb",
        parameters={"POLL_CYCLES": 5, "RS_FEC": 0},
    )


def arbitration() -> None:
    run_cocotb(
        "prism_tile_arbiter",
        "tests.unit.test_tile_arbiter_cocotb",
        parameters={"PORTS": 2, "LANES": 4},
    )


def ingress() -> None:
    run_cocotb(
        "prism_numbergroup_frame_validator_harness",
        "tests.unit.test_numbergroup_frame_validator_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_native_tile_harness",
        "tests.unit.test_numbergroup_native_tile_cocotb",
    )
    run_cocotb("prism_single_data_receiver", "tests.unit.test_single_data_receiver_cocotb")


def numbergroup() -> None:
    run_cocotb("prism_frame_class_router", "tests.unit.test_frame_class_router_cocotb")
    run_cocotb(
        "prism_control_header_parser_harness",
        "tests.unit.test_control_header_parser_cocotb",
    )
    run_cocotb(
        "prism_control_frame_validator_harness",
        "tests.unit.test_control_frame_validator_cocotb",
    )
    run_cocotb(
        "prism_control_context_fixed_parser",
        "tests.unit.test_control_context_fixed_parser_cocotb",
    )
    run_cocotb(
        "prism_control_single_bindings_parser",
        "tests.unit.test_control_single_bindings_parser_cocotb",
    )
    run_cocotb(
        "prism_control_stage_precheck_harness",
        "tests.unit.test_control_stage_precheck_cocotb",
    )
    run_cocotb(
        "prism_single_lifecycle",
        "tests.unit.test_single_lifecycle_cocotb",
        parameters={"CONTEXT_W": 32},
    )
    run_cocotb(
        "prism_control_ack_encoder",
        "tests.unit.test_control_ack_encoder_cocotb",
    )
    run_cocotb(
        "prism_single_control_plane",
        "tests.integration.test_single_control_plane_cocotb",
    )
    run_cocotb(
        "prism_single_control_plane",
        "tests.unit.test_single_control_mtu_cap_cocotb",
        parameters={"MAX_MTU": 576},
    )
    run_cocotb(
        "prism_single_data_receiver",
        "tests.unit.test_single_data_receiver_cocotb",
        parameters={"PORT_INDEX": 0},
    )
    run_cocotb(
        "prism_single_native_ingress",
        "tests.integration.test_single_native_ingress_cocotb",
    )
    run_cocotb(
        "prism_single_native_core",
        "tests.integration.test_single_native_core_cocotb",
    )
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_numbergroup_top_cocotb",
    )
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_prismworld_single_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_header_parser_harness",
        "tests.unit.test_numbergroup_header_parser_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_frame_validator_harness",
        "tests.unit.test_numbergroup_frame_validator_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_interval_window",
        "tests.unit.test_numbergroup_interval_window_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_frame_planner",
        "tests.unit.test_numbergroup_frame_planner_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_reader_harness",
        "tests.unit.test_numbergroup_reader_cocotb",
    )
    run_cocotb(
        "prism_numbergroup_native_tile_harness",
        "tests.unit.test_numbergroup_native_tile_cocotb",
    )
    run_cocotb("prism_kulisch_segmenter", "tests.unit.test_kulisch_segmenter_cocotb")
    run_cocotb("prism_float_to_kulisch", "tests.unit.test_kulisch_scale_cocotb")
    run_cocotb("prism_int8_to_kulisch", "tests.unit.test_int8_kulisch_scale_cocotb")
    run_cocotb(
        "prism_exact_native_tile_pipeline",
        "tests.unit.test_exact_native_tile_pipeline_cocotb",
    )
    run_cocotb(
        "prism_exact_tile_merge2",
        "tests.unit.test_exact_tile_merge2_cocotb",
    )
    run_cocotb(
        "prism_fp32_rounded_result_store",
        "tests.unit.test_fp32_rounded_result_store_cocotb",
    )
    run_cocotb(
        "prism_exact_final_round_scalar",
        "tests.unit.test_exact_final_round_scalar_cocotb",
    )
    for width in (279, 320):
        run_cocotb(
            "prism_auto_wire_scalar",
            "tests.unit.test_auto_wire_scalar_cocotb",
            parameters={"KULISCH_W": width},
        )
    run_cocotb(
        "prism_single_native_stream_egress",
        "tests.integration.test_single_native_stream_egress_cocotb",
    )


def fp32_arrival() -> None:
    run_cocotb("prism_fp32_arrival_bank", "tests.unit.test_fp32_arrival_bank_cocotb")
    for ports in (1, 2, 4):
        run_cocotb(
            "prism_fp32_arrival_backend",
            "tests.unit.test_fp32_arrival_backend_cocotb",
            parameters={"PORTS": ports},
        )
    run_cocotb("prism_sim_top", "tests.integration.test_fp32_online_single_cocotb")


def ccl_integration() -> None:
    run_ccl_tests("tests/integration")


def partial_path() -> None:
    for lanes in (16, 64, 128):
        run_cocotb(
            "prism_auto_wire_tile16",
            "tests.unit.test_auto_wire_tile_cocotb",
            parameters={"LANES": lanes, "KULISCH_W": 280},
        )
    for lanes in (16, 64, 128):
        run_cocotb(
            "prism_numbergroup_banked_segment_reader",
            "tests.unit.test_numbergroup_segment_reader_cocotb",
            parameters={"LANES": lanes, "KULISCH_W": 320},
        )
    run_cocotb(
        "prism_numbergroup_auto_partial_harness",
        "tests.unit.test_numbergroup_auto_partial_cocotb",
        parameters={"LANES": 16},
    )
    run_cocotb(
        "prism_numbergroup_mixed_tile_harness",
        "tests.unit.test_numbergroup_mixed_tile_cocotb",
        parameters={"KULISCH_W": 320, "MTU_BYTES": 576},
    )
    for format_id in (1, 2, 3, 4):
        run_cocotb(
            "prism_native_partial_tile_harness",
            "tests.unit.test_native_partial_tile_harness_cocotb",
            parameters={"FORMAT": format_id},
        )
    run_cocotb(
        "prism_numbergroup_kulisch_tile_streamer",
        "tests.unit.test_kulisch_partial_tile_streamer_cocotb",
        parameters={"KULISCH_W": 320, "MTU_BYTES": 576},
    )
    run_cocotb(
        "prism_numbergroup_kulisch_tile_streamer",
        "tests.unit.test_kulisch_partial_widest_tile_cocotb",
        parameters={"KULISCH_W": 4096, "MTU_BYTES": 576},
    )
    run_cocotb(
        "prism_numbergroup_kulisch_tile_streamer",
        "tests.unit.test_kulisch_partial_mtu1500_cocotb",
        parameters={"KULISCH_W": 320, "MTU_BYTES": 1500},
    )
    run_cocotb(
        "prism_kulisch_partial_tile_harness",
        "tests.integration.test_kulisch_partial_tile_harness_cocotb",
        parameters={"KULISCH_W": 320, "MTU_BYTES": 576},
    )


def rtl_integration() -> None:
    run_cocotb("prism_sim_top", "tests.integration.test_integration_cocotb")
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_exact_only_build_cocotb",
        parameters={"ENABLE_FP32_ACCUMULATION": 0},
    )


def u280_profile() -> None:
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_u280_profile_cocotb",
        parameters={
            "NUM_PORTS": 1,
            "ENABLE_FP32_ACCUMULATION": 0,
            "KULISCH_W": 280,
            "MAX_KULISCH_BITS": 280,
            "MAX_ORIGINAL_TERMS": 2,
            "MAX_CHILDREN": 2,
            "EXACT_BANKS": 4,
        },
    )
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_single_driver_cocotb",
        parameters={
            "NUM_PORTS": 1,
            "ENABLE_FP32_ACCUMULATION": 0,
            "KULISCH_W": 280,
            "MAX_KULISCH_BITS": 280,
            "MAX_ORIGINAL_TERMS": 2,
            "MAX_CHILDREN": 2,
            "EXACT_BANKS": 4,
        },
    )


def u280_two_port_profile() -> None:
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_u280_two_port_profile_cocotb",
        parameters={
            "NUM_PORTS": 2,
            "ENABLE_FP32_ACCUMULATION": 0,
            "KULISCH_W": 280,
            "MAX_KULISCH_BITS": 280,
            "MAX_ORIGINAL_TERMS": 2,
            "MAX_CHILDREN": 2,
            "EXACT_BANKS": 4,
        },
    )


def u280_board() -> None:
    # The shell is fetched at the commit the build pins, unless one is given.
    if "PRISM_OPEN_NIC_SHELL" not in os.environ:
        sys.path.insert(0, str(HDL_ROOT / "integrations"))
        from build_support import prepare_open_nic

        prepare_open_nic(OPEN_NIC_SHELL)
    shell = OPEN_NIC_SHELL / "src"
    if not (shell / "cmac_subsystem" / "cmac_subsystem.sv").exists():
        raise SystemExit(f"ERROR: the board suite needs the OpenNIC shell at {OPEN_NIC_SHELL}")
    board = HDL_ROOT / "integrations" / "u280"
    run_cocotb(
        "prism_u280_top",
        "tests.integration.test_u280_board_cocotb",
        extra_sources=[
            board / "sim" / "xilinx_models.sv",
            board / "sim" / "cmac_subsystem_axi_crossbar.sv",
            *(
                shell / name
                for name in (
                    "utility/generic_reset.sv",
                    "utility/axi_lite_register.sv",
                    "utility/axi_lite_slave.sv",
                    "utility/axi_stream_register_slice.sv",
                    "utility/axi_stream_packet_fifo.sv",
                    "utility/axi_stream_packet_buffer.sv",
                    "utility/axi_stream_size_counter.sv",
                    "utility/level_trigger_cdc.sv",
                    "cmac_subsystem/cmac_subsystem_address_map.v",
                    "cmac_subsystem/cmac_subsystem.sv",
                    "packet_adapter/packet_adapter_register.v",
                    "packet_adapter/packet_adapter_rx.sv",
                    "packet_adapter/packet_adapter_tx.sv",
                    "packet_adapter/packet_adapter.sv",
                )
            ),
            *sorted((board / "rtl").glob("*.sv")),
        ],
        extra_build_args=["+define+__au280__", f"-I{shell}", "--timescale", "1ns/1ps"],
    )


def pipeline() -> None:
    run_cocotb(
        "prism_exact_native_tile_pipeline",
        "tests.unit.test_exact_native_tile_pipeline_cocotb",
    )
    run_cocotb(
        "prism_striped_exact_tile_port",
        "tests.unit.test_striped_exact_tile_port_cocotb",
        parameters={
            "KULISCH_W": 280,
            "MAX_ORIGINAL_TERMS": 2,
            "BANKS": 4,
            "RESULT_LANES": 64,
        },
    )


def throughput() -> None:
    run_cocotb(
        "prism_numbergroup_auto_partial_harness",
        "tests.unit.test_numbergroup_auto_partial_cocotb",
        parameters={"LANES": 16},
    )
    run_cocotb("prism_sim_top", "tests.integration.test_prismworld_single_cocotb")
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_numbergroup_ingress_throughput_cocotb",
    )


def line_rate_target() -> None:
    run_cocotb(
        "prism_sim_top",
        "tests.integration.test_prismworld_line_rate_target_cocotb",
    )
    run_cocotb(
        "prism_single_data_receiver",
        "tests.unit.test_single_data_receiver_line_rate_cocotb",
    )


def partial_line_rate_target() -> None:
    partial_128_target()
    partial_producer_target()
    run_cocotb(
        "prism_numbergroup_mixed_tile_harness",
        "tests.unit.test_numbergroup_mixed_tile_mtu1500_cocotb",
        parameters={"KULISCH_W": 320, "MTU_BYTES": 1500},
    )
    run_cocotb(
        "prism_numbergroup_mixed_tile_harness",
        "tests.unit.test_numbergroup_mixed_tile_rate_cocotb",
        parameters={"KULISCH_W": 320, "MTU_BYTES": 1500},
    )


def partial_wide_target() -> None:
    run_cocotb(
        "prism_numbergroup_auto_partial_harness",
        "tests.unit.test_numbergroup_auto_partial_wide_cocotb",
        parameters={"LANES": 64},
    )


def partial_128_target() -> None:
    run_cocotb(
        "prism_numbergroup_auto_partial_harness",
        "tests.unit.test_numbergroup_auto_partial_wide_cocotb",
        parameters={"LANES": 128},
    )


def partial_producer_target() -> None:
    run_cocotb(
        "prism_exact_auto_partial_stream_harness",
        "tests.integration.test_exact_auto_partial_stream_cocotb",
    )


def result_wide_target() -> None:
    run_cocotb(
        "prism_single_kulisch_stream_egress",
        "tests.unit.test_single_kulisch_stream_egress_wide_cocotb",
        parameters={"LANES": 64},
    )
    # The widths of the U280 profile: an exact value takes 36 bytes, not 41.
    run_cocotb(
        "prism_single_kulisch_stream_egress",
        "tests.unit.test_single_kulisch_stream_egress_wide_cocotb",
        parameters={"LANES": 64, "KULISCH_W": 280, "MAX_KULISCH_BITS": 280},
    )


def result_128_target() -> None:
    run_cocotb(
        "prism_single_kulisch_stream_egress",
        "tests.unit.test_single_kulisch_stream_egress_128_cocotb",
        parameters={"LANES": 128},
    )


def storage() -> None:
    run_cocotb(
        "prism_single_kulisch_stream_egress",
        "tests.unit.test_single_error_result_egress_cocotb",
    )
    run_cocotb(
        "prism_single_native_stream_egress",
        "tests.integration.test_single_native_stream_egress_cocotb",
    )


SUITES: dict[str, Callable[[], None]] = {
    "quality": lint,
    "ccl-coverage": run_python_coverage,
    "ccl-unit": ccl_unit,
    "verification-unit": verification_unit,
    "parameters": run_parameter_matrix,
    "rtl-control": control,
    "rtl-arbitration": arbitration,
    "rtl-ingress": ingress,
    "rtl-numbergroup": numbergroup,
    "rtl-partials": partial_path,
    "rtl-formats": formats,
    "rtl-fp32-arrival": fp32_arrival,
    "rtl-backpressure": backpressure,
    "rtl-pipeline": pipeline,
    "rtl-throughput": throughput,
    "rtl-line-rate-target": line_rate_target,
    "rtl-partial-wide-target": partial_wide_target,
    "rtl-partial-128-target": partial_128_target,
    "rtl-partial-producer-target": partial_producer_target,
    "rtl-result-wide-target": result_wide_target,
    "rtl-result-128-target": result_128_target,
    "rtl-partial-line-rate-target": partial_line_rate_target,
    "rtl-storage": storage,
    "wireshark": lambda: run_ccl_tests("tests/wireshark"),
    "ccl-integration": ccl_integration,
    "rtl-integration": rtl_integration,
    "rtl-u280-profile": u280_profile,
    "rtl-u280-two-port-profile": u280_two_port_profile,
    "rtl-u280-board": u280_board,
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
