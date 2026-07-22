from __future__ import annotations

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from prism_ccl.collectives.reference import fp32_sum_bits, kulisch_sum_bits
from prism_ccl.protocol.constants import AccumulatorProfile, WireFormat


def pack_lanes(values):
    result = 0
    for lane, value in enumerate(values):
        result |= value << (32 * lane)
    return result


async def send(
    dut,
    contributor,
    values,
    profile,
    width_index=1,
    *,
    operation_slot=0,
    expected_contributors=2,
    keep=0xF,
):
    dut.s_contributor_id.value = contributor
    dut.s_operation_slot.value = operation_slot
    dut.s_expected_contributors.value = expected_contributors
    dut.s_input_format.value = int(WireFormat.FP32)
    dut.s_output_format.value = int(WireFormat.FP32)
    dut.s_accumulator_profile.value = int(profile)
    dut.s_width_index.value = width_index
    dut.s_element_bits.value = pack_lanes(values)
    dut.s_element_keep.value = keep
    dut.s_valid.value = 1
    while not int(dut.s_ready.value):
        await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.s_valid.value = 0


@cocotb.test()
async def typed_reduction_boundary_matches_profiles_and_stalls_cleanly(dut):
    seed = 23
    random.seed(seed)
    dut._log.info("deterministic_seed=%d", seed)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    left = [0x3F800000, 0x40000000, 0xBF800000, 0x00000001]
    right = [0x40400000, 0xC0000000, 0x3F800000, 0x00000001]
    profiles = [
        AccumulatorProfile.FP32_ARRIVAL,
        AccumulatorProfile.FP32_ORDERED,
        AccumulatorProfile.KULISCH_FP32,
    ]
    for profile in profiles:
        await send(dut, 1, right, profile)
        await send(dut, 0, left, profile)
        for _ in range(2000):
            dut.m_ready.value = random.randrange(2)
            if int(dut.m_valid.value):
                raw = int(dut.m_element_bits.value)
                actual = [(raw >> (32 * lane)) & 0xFFFFFFFF for lane in range(4)]
                if profile == AccumulatorProfile.KULISCH_FP32:
                    expected = [
                        kulisch_sum_bits(
                            [left[i], right[i]],
                            input_format=WireFormat.FP32,
                            maximum_terms=2,
                            compiled_widths=(64, 288, 320),
                        ).bits
                        for i in range(4)
                    ]
                else:
                    expected = [
                        fp32_sum_bits([(0, left[i]), (1, right[i])], ordered=True) for i in range(4)
                    ]
                assert actual == expected
                while not int(dut.m_ready.value):
                    await RisingEdge(dut.clk)
                    dut.m_ready.value = 1
                await RisingEdge(dut.clk)
                break
            await RisingEdge(dut.clk)
        else:
            raise AssertionError(f"no output for profile {profile.name}")


@cocotb.test()
async def kulisch_saturation_is_reported_as_a_sticky_warning(dut):
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    for value in (0x14400000, 0x94400000):
        values = [value] * 4
        await send(dut, 0, values, AccumulatorProfile.KULISCH_FP32, width_index=0)
        await send(dut, 1, values, AccumulatorProfile.KULISCH_FP32, width_index=0)
        for _ in range(100):
            if int(dut.m_valid.value):
                raw = int(dut.m_element_bits.value)
                actual = [(raw >> (32 * lane)) & 0xFFFFFFFF for lane in range(4)]
                expected_value = kulisch_sum_bits(
                    [value, value],
                    input_format=WireFormat.FP32,
                    maximum_terms=2,
                    compiled_widths=(64,),
                )
                assert actual == [expected_value.bits] * 4
                assert int(dut.m_accumulation_inexact.value) == 1
                dut.m_ready.value = 1
                await RisingEdge(dut.clk)
                dut.m_ready.value = 0
                break
            await RisingEdge(dut.clk)
        else:
            raise AssertionError("no saturated Kulisch output")


@cocotb.test()
async def concurrent_ranges_and_duplicate_contributions_remain_isolated(dut):
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    a0 = [0x3F800000] * 4
    a1 = [0x40000000] * 4
    b0 = [0x40800000] * 4
    b1 = [0x40A00000] * 4
    await send(dut, 0, a0, AccumulatorProfile.KULISCH_FP32, operation_slot=0)
    await send(dut, 0, b0, AccumulatorProfile.KULISCH_FP32, operation_slot=1)
    await send(dut, 0, a0, AccumulatorProfile.KULISCH_FP32, operation_slot=0)
    await send(dut, 1, b1, AccumulatorProfile.KULISCH_FP32, operation_slot=1)
    await send(dut, 1, a1, AccumulatorProfile.KULISCH_FP32, operation_slot=0)

    dut.m_ready.value = 1
    observed = {}
    for _ in range(100):
        if int(dut.m_valid.value):
            slot = int(dut.m_operation_slot.value)
            raw = int(dut.m_element_bits.value)
            observed[slot] = [(raw >> (32 * lane)) & 0xFFFFFFFF for lane in range(4)]
            if len(observed) == 2:
                await RisingEdge(dut.clk)
                break
        await RisingEdge(dut.clk)
    assert observed == {
        0: [0x40400000] * 4,
        1: [0x41100000] * 4,
    }
