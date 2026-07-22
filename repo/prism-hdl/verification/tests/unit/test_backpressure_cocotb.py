from __future__ import annotations

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def skid_buffer_never_drops_or_reorders(dut):
    seed = 19
    random.seed(seed)
    dut._log.info("deterministic_seed=%d", seed)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    pending = list(range(200))
    expected = []
    received = []
    active = None
    for _cycle in range(3000):
        dut.m_axis_tready.value = random.randrange(2)
        if active is None and pending and random.randrange(4) != 0:
            active = pending.pop(0)
        dut.s_axis_tvalid.value = int(active is not None)
        if active is not None:
            dut.s_axis_tdata.value = active
            dut.s_axis_tkeep.value = 0xFF
            dut.s_axis_tlast.value = active & 1
            dut.s_axis_tuser.value = (active >> 1) & 1
        await Timer(1, unit="ps")
        input_fire = active is not None and int(dut.s_axis_tready.value)
        output_fire = int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value)
        if input_fire:
            expected.append((active, 0xFF, active & 1, (active >> 1) & 1))
            active = None
        if output_fire:
            received.append(
                (
                    int(dut.m_axis_tdata.value),
                    int(dut.m_axis_tkeep.value),
                    int(dut.m_axis_tlast.value),
                    int(dut.m_axis_tuser.value),
                )
            )
        await RisingEdge(dut.clk)
        if not pending and active is None and len(received) == len(expected):
            break
    assert len(expected) == 200
    assert received == expected
