from __future__ import annotations

import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def split_buffer_keeps_payload_and_control_paired_under_stalls(dut):
    seed = 0x534C52
    random.seed(seed)
    dut._log.info("deterministic_seed=%d", seed)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.s_data.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    source = deque(((index << 8) | (index ^ 0xA5)) for index in range(300))
    reference = deque()
    received: list[int] = []
    active: int | None = None
    stalled_data: int | None = None

    for _cycle in range(10000):
        if active is None and source and random.randrange(4) != 0:
            active = source.popleft()
        dut.s_valid.value = int(active is not None)
        dut.s_data.value = active if active is not None else random.getrandbits(40)
        dut.m_ready.value = random.randrange(2)
        await Timer(1, unit="ps")

        input_fire = active is not None and int(dut.s_ready.value)
        output_fire = int(dut.m_valid.value) and int(dut.m_ready.value)
        output_data = int(dut.m_data.value)

        if int(dut.m_valid.value) and not int(dut.m_ready.value):
            if stalled_data is not None:
                assert output_data == stalled_data
            stalled_data = output_data
        else:
            stalled_data = None

        if input_fire:
            reference.append(active)
            active = None
        if output_fire:
            assert reference
            assert output_data == reference.popleft()
            received.append(output_data)

        await RisingEdge(dut.clk)
        if not source and active is None and not reference:
            break

    expected = [((index << 8) | (index ^ 0xA5)) for index in range(300)]
    assert received == expected
