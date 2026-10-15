"""The exact-result serializer preserves consecutive elements under backpressure."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

WIDTH = 320


async def send_tile(dut: Any, first: int, values: tuple[int, ...]) -> None:
    await FallingEdge(dut.clk)
    assert int(dut.s_ready.value) == 1
    dut.s_first_element.value = first
    dut.s_keep.value = (1 << len(values)) - 1
    dut.s_tags.value = 0
    dut.s_integers.value = sum(value << (index * WIDTH) for index, value in enumerate(values))
    dut.s_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0


@cocotb.test()
async def full_and_partial_tiles_survive_stalls(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_clear.value = 0
    dut.s_first_element.value = 0
    dut.s_keep.value = 0
    dut.s_tags.value = 0
    dut.s_integers.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    for first, values in ((0, tuple(range(1, 17))), (16, (17, 18, 19))):
        dut.m_ready.value = 0
        await send_tile(dut, first, values)
        observed: list[tuple[int, ...]] = []
        for cycle in range(40):
            await FallingEdge(dut.clk)
            dut.m_ready.value = int(cycle % 4 != 1)
            await ReadOnly()
            assert int(dut.m_fault.value) == 0
            if int(dut.m_valid.value) and int(dut.m_ready.value):
                count = int(dut.m_count.value)
                position = int(dut.m_first_element.value)
                word = int(dut.m_integers.value)
                assert int(dut.m_tags.value) == 0
                observed.extend(
                    (position + lane, (word >> (lane * WIDTH)) & ((1 << WIDTH) - 1))
                    for lane in range(count)
                )
            await RisingEdge(dut.clk)
            if len(observed) == len(values):
                break
        assert observed == [(first + index, value) for index, value in enumerate(values)]
        await FallingEdge(dut.clk)
        assert int(dut.s_ready.value) == 1
