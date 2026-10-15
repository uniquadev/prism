"""Sustained, full-size native NumberGroups through the two-port SINGLE RTL."""

from __future__ import annotations

from collections import Counter
from typing import Any

import cocotb
from ccl.examples import shared_port_world
from ccl.world import CocotbSingleBackend
from cocotb.triggers import FallingEdge, ReadOnly
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    TypedVector,
)

ELEMENTS = 4096
FORMAT_ONE = (
    (ConcreteFormat.INT8, 1),
    (ConcreteFormat.FP16, 0x3C00),
    (ConcreteFormat.BF16, 0x3F80),
    (ConcreteFormat.FP32, 0x3F800000),
)


async def count_stages(dut: Any, counters: Counter[str]) -> None:
    while True:
        await FallingEdge(dut.clk)
        await ReadOnly()
        counters["fast_mode_cycles"] += bool(int(dut.debug_fast_mode.value))
        counters["fast_exact_cycles"] += bool(int(dut.debug_fast_exact.value))
        for port in range(2):
            mask = 1 << port
            data_valid = bool(int(dut.debug_data_valid.value) & mask)
            data_ready = bool(int(dut.debug_data_ready.value) & mask)
            reader_valid = bool(int(dut.debug_reader_valid.value) & mask)
            reader_ready = bool(int(dut.debug_reader_ready.value) & mask)
            tile_valid = bool(int(dut.debug_tile_valid.value) & mask)
            tile_ready = bool(int(dut.debug_tile_ready.value) & mask)
            prefix = f"port{port}_"
            counters[prefix + "data_beats"] += data_valid and data_ready
            counters[prefix + "data_stalls"] += data_valid and not data_ready
            counters[prefix + "reader_bytes"] += reader_valid and reader_ready
            counters[prefix + "reader_stalls"] += reader_valid and not reader_ready
            counters[prefix + "reader_elements"] += (
                reader_valid
                and reader_ready
                and bool(int(dut.debug_reader_element_last.value) & mask)
            )
            counters[prefix + "tiles"] += tile_valid and tile_ready
            counters[prefix + "tile_stalls"] += tile_valid and not tile_ready
            if tile_valid and tile_ready:
                counters[prefix + "tile_elements"] += int(dut.debug_tile_count[port].value)
            bank_valid = bool(int(dut.debug_bank_input_valid.value) & mask)
            bank_ready = bool(int(dut.debug_bank_input_ready.value) & mask)
            bank_advance = bool(int(dut.debug_bank_advance.value) & mask)
            counters[prefix + "bank_tiles"] += bank_valid and bank_ready
            counters[prefix + "bank_stalls"] += bank_valid and not bank_ready
            counters[prefix + "bank_hazards"] += bank_valid and bool(
                int(dut.debug_bank_hazard.value) & mask
            )
            counters[prefix + "converted_tiles"] += bank_advance and bool(
                int(dut.debug_bank_stage1_valid.value) & mask
            )
            counters[prefix + "accumulated_tiles"] += bank_advance and bool(
                int(dut.debug_bank_stage2_valid.value) & mask
            )
            counters[prefix + "memory_commit_tiles"] += bank_advance and bool(
                int(dut.debug_bank_stage2_valid.value) & mask
            )
            counters[prefix + "bank_output_tiles"] += bank_advance and bool(
                int(dut.debug_bank_stage3_valid.value) & mask
            )


@cocotb.test()
async def full_groups_expose_ingress_stage_rates(dut: Any) -> None:
    for run_index, (input_format, one_bits) in enumerate(FORMAT_ONE):
        world, tree = shared_port_world()
        vectors = {rank: TypedVector(input_format, (one_bits,) * ELEMENTS) for rank in range(3)}
        world.register_reduce(
            "sustained",
            tree=tree,
            vectors=vectors,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.AUTO,
            output_format=ConcreteFormat.FP32,
            destination_rank=1,
        )
        counters: Counter[str] = Counter()
        monitor = cocotb.start_soon(count_stages(dut, counters))
        try:
            result = await world.run_async(
                "sustained",
                backend=CocotbSingleBackend(
                    dut,
                    prism_name="s",
                    timeout_cycles=200_000,
                    start_clock=run_index == 0,
                ),
            )
        finally:
            monitor.cancel()
        dut._log.info(
            "INGRESS_STAGE_COUNTERS format=%s stages=%s", input_format.name, dict(counters)
        )
        assert result.rank_bits == {1: (0x40400000,) * ELEMENTS}
        assert result.released_context
        assert counters["port0_tile_elements"] + counters["port1_tile_elements"] == (3 * ELEMENTS)
        # One native-width issue group and one ingress beat can each be
        # handled per port per cycle. Their sum is a serialization budget;
        # the two validation banks normally overlap most of this work.
        serialized_port_budget = max(
            counters[f"port{port}_data_beats"] + counters[f"port{port}_tiles"] for port in range(2)
        )
        assert result.timing.data_window_cycles <= serialized_port_budget
        element_bits = (
            8
            if input_format == ConcreteFormat.INT8
            else (32 if input_format == ConcreteFormat.FP32 else 16)
        )
        # Port 0 carries two complete ranks in this topology. The measured
        # DATA window includes both accepted frames and downstream arithmetic.
        port0_numeric_gbps = 2 * ELEMENTS * element_bits / (result.timing.data_window_cycles * 4)
        assert port0_numeric_gbps >= 100, (
            f"{input_format.name}: complete SINGLE DATA window {port0_numeric_gbps:.2f} Gb/s"
        )
        for port in range(2):
            prefix = f"port{port}_"
            assert counters[prefix + "reader_bytes"] == 0
            assert counters[prefix + "tile_stalls"] == 0
            assert counters[prefix + "bank_stalls"] == 0
            assert counters[prefix + "bank_hazards"] == 0
            assert counters[prefix + "bank_tiles"] == counters[prefix + "tiles"]
            assert counters[prefix + "converted_tiles"] == counters[prefix + "tiles"]
            assert counters[prefix + "accumulated_tiles"] == counters[prefix + "tiles"]
            assert counters[prefix + "memory_commit_tiles"] == counters[prefix + "tiles"]
            assert counters[prefix + "bank_output_tiles"] == counters[prefix + "tiles"]
        dut._log.info(
            "INGRESS_METRICS format=%s data_window=%d port0_numeric=%.2f Gb/s "
            "input_stalls=%s stages=%s",
            input_format.name,
            result.timing.data_window_cycles,
            port0_numeric_gbps,
            result.stalled_input_beats,
            dict(counters),
        )
