from __future__ import annotations

from itertools import pairwise

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import AccumulatorProfile, WireFormat

LANES = 16
CLOCK_HZ = 250_000_000
OPERATIONS = 128


def packed_ones() -> int:
    return sum(0x3F800000 << (32 * lane) for lane in range(LANES))


@cocotb.test()
async def arithmetic_pipeline_reaches_one_full_tile_per_cycle(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    dut.s_contributor_id.value = 0
    dut.s_expected_contributors.value = 1
    dut.s_input_format.value = int(WireFormat.FP32)
    dut.s_output_format.value = int(WireFormat.FP32)
    dut.s_accumulator_profile.value = int(AccumulatorProfile.KULISCH_FP32)
    dut.s_width_index.value = 1
    dut.s_element_bits.value = packed_ones()
    dut.s_element_keep.value = (1 << LANES) - 1

    next_operation = 0
    accepted_cycles = []
    emitted_cycles = []
    emitted_slots = []
    cycle = 0
    while len(emitted_slots) < OPERATIONS and cycle < 1000:
        dut.s_valid.value = next_operation < OPERATIONS
        if next_operation < OPERATIONS:
            dut.s_operation_slot.value = next_operation
        await Timer(1, unit="ps")
        input_transfer = bool(dut.s_valid.value) and bool(dut.s_ready.value)
        output_transfer = bool(dut.m_valid.value) and bool(dut.m_ready.value)
        if input_transfer:
            accepted_cycles.append(cycle)
        if output_transfer:
            emitted_cycles.append(cycle)
            emitted_slots.append(int(dut.m_operation_slot.value))
            raw = int(dut.m_element_bits.value)
            assert all(((raw >> (32 * lane)) & 0xFFFFFFFF) == 0x3F800000 for lane in range(LANES))
        await RisingEdge(dut.clk)
        if input_transfer:
            next_operation += 1
        cycle += 1

    assert next_operation == OPERATIONS
    assert emitted_slots == list(range(OPERATIONS))
    assert all(right - left == 1 for left, right in pairwise(accepted_cycles))
    assert all(right - left == 1 for left, right in pairwise(emitted_cycles))

    fill_latency_cycles = emitted_cycles[0] - accepted_cycles[0]
    payload_bits_per_cycle = LANES * 32
    payload_rate_bits_per_second = payload_bits_per_cycle * CLOCK_HZ
    dut._log.info(
        "fill_latency_cycles=%d steady_tiles_per_cycle=1 payload_rate_gbps=%.1f",
        fill_latency_cycles,
        payload_rate_bits_per_second / 1e9,
    )
    assert fill_latency_cycles > 0
    assert payload_rate_bits_per_second == 128_000_000_000
