from __future__ import annotations

import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def frames_are_atomic_fair_and_stable_under_backpressure(dut) -> None:
    random.seed(0xF4A6E)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s0_axis_tvalid.value = 0
    dut.s1_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    queues = [
        deque(
            [[0x000 + frame * 0x10 + beat for beat in range(1 + frame % 3)] for frame in range(8)]
        ),
        deque(
            [
                [0x800 + frame * 0x10 + beat for beat in range(1 + (frame + 1) % 3)]
                for frame in range(8)
            ]
        ),
    ]
    active = [queues[0].popleft(), queues[1].popleft()]
    positions = [0, 0]
    output_frames = []
    output_frame = []
    held = None

    for _cycle in range(2000):
        for port in range(2):
            prefix = f"s{port}_axis_"
            frame = active[port]
            getattr(dut, prefix + "tvalid").value = frame is not None
            if frame is not None:
                position = positions[port]
                getattr(dut, prefix + "tdata").value = frame[position]
                getattr(dut, prefix + "tkeep").value = 0xF
                getattr(dut, prefix + "tlast").value = position == len(frame) - 1
                getattr(dut, prefix + "tuser").value = port
        ready = random.randrange(5) != 0
        dut.m_axis_tready.value = ready
        await Timer(1, unit="ps")
        if int(dut.m_axis_tvalid.value):
            beat = (
                int(dut.m_axis_tdata.value),
                int(dut.m_axis_tlast.value),
                int(dut.m_axis_tuser.value),
            )
            if not ready:
                if held is not None:
                    assert beat == held
                held = beat
            else:
                held = None
                output_frame.append(beat[0])
                assert ((beat[0] >> 11) & 1) == beat[2]
                if beat[1]:
                    output_frames.append(output_frame)
                    output_frame = []

        accepted = [int(dut.s0_axis_tready.value), int(dut.s1_axis_tready.value)]
        await RisingEdge(dut.clk)
        for port in range(2):
            if accepted[port] and active[port] is not None:
                positions[port] += 1
                if positions[port] == len(active[port]):
                    active[port] = queues[port].popleft() if queues[port] else None
                    positions[port] = 0
        if all(frame is None for frame in active) and len(output_frames) == 16:
            break

    expected = []
    for frame in range(8):
        expected.append([0x000 + frame * 0x10 + beat for beat in range(1 + frame % 3)])
        expected.append([0x800 + frame * 0x10 + beat for beat in range(1 + (frame + 1) % 3)])
    assert output_frames == expected
