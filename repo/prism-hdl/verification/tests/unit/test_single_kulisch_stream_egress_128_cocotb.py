"""An eight-bank exact RESULT readout supplies 128 values per cycle."""

from __future__ import annotations

from typing import Any

import cocotb

from .test_single_kulisch_stream_egress_wide_cocotb import run_exact_auto_result


@cocotb.test()
async def exact_auto_result_sustains_int8_with_128_lane_source(dut: Any) -> None:
    await run_exact_auto_result(dut, 128)


@cocotb.test()
async def exact_auto_result_preserves_all_positions_under_backpressure(dut: Any) -> None:
    await run_exact_auto_result(dut, 128, stall=True)
