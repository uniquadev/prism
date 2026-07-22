from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer, with_timeout


async def reset(dut) -> None:
    dut.rst_n.value = 0
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def send_beat(dut, value: int, *, keep: int = 0xF, last: bool = False, user: int = 0) -> None:
    dut.s_axis_tdata.value = value
    dut.s_axis_tkeep.value = keep
    dut.s_axis_tlast.value = last
    dut.s_axis_tuser.value = user
    dut.s_axis_tvalid.value = 1
    while True:
        await Timer(1, unit="ps")
        if int(dut.s_axis_tready.value):
            await RisingEdge(dut.clk)
            dut.s_axis_tvalid.value = 0
            return
        await RisingEdge(dut.clk)


async def receive_beat(dut) -> tuple[int, bool, tuple[int, bool, bool, bool]]:
    dut.m_axis_tready.value = 0
    while True:
        await Timer(1, unit="ps")
        if int(dut.m_axis_tvalid.value):
            break
        await RisingEdge(dut.clk)
    value = int(dut.m_axis_tdata.value)
    last = bool(dut.m_axis_tlast.value)
    metadata = (
        int(dut.m_frame_bytes.value),
        bool(dut.m_nonfinal_keep_error.value),
        bool(dut.m_final_keep_error.value),
        bool(dut.m_adapter_error.value),
    )
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    dut.m_axis_tready.value = 0
    return value, last, metadata


@cocotb.test()
async def oversized_frame_is_truncated_flagged_drained_and_recovers(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)

    for value in (10, 11, 12, 13):
        await send_beat(dut, value)
    await send_beat(dut, 14, last=True)
    await Timer(1, unit="ps")
    assert int(dut.beat_occupancy.value) == 3
    assert int(dut.completed_frames.value) == 1

    first = [await receive_beat(dut) for _ in range(3)]
    assert [(value, last) for value, last, _metadata in first] == [
        (10, False),
        (11, False),
        (12, True),
    ]
    assert all(metadata == (12, False, False, True) for _value, _last, metadata in first)

    await send_beat(dut, 20, keep=0x3, user=1)
    await send_beat(dut, 21, keep=0x5, last=True)
    second = [await receive_beat(dut) for _ in range(2)]
    assert [(value, last) for value, last, _metadata in second] == [
        (20, False),
        (21, True),
    ]
    assert all(metadata == (4, True, True, True) for _value, _last, metadata in second)
    await Timer(1, unit="ps")
    assert int(dut.beat_occupancy.value) == 0
    assert int(dut.completed_frames.value) == 0


@cocotb.test()
async def full_frame_fifo_replaces_output_beats_each_cycle(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)

    await send_beat(dut, 1)
    await send_beat(dut, 2, last=True)
    await send_beat(dut, 3)
    await send_beat(dut, 4)
    await send_beat(dut, 5, last=True)
    await Timer(1, unit="ps")
    assert int(dut.beat_occupancy.value) == 5
    assert int(dut.s_axis_tready.value) == 0

    consumed = []
    for value, last in ((6, False), (7, True)):
        dut.s_axis_tdata.value = value
        dut.s_axis_tkeep.value = 0xF
        dut.s_axis_tlast.value = last
        dut.s_axis_tuser.value = 0
        dut.s_axis_tvalid.value = 1
        dut.m_axis_tready.value = 1
        await Timer(1, unit="ps")
        assert int(dut.s_axis_tready.value) == 1
        consumed.append(int(dut.m_axis_tdata.value))
        await RisingEdge(dut.clk)
        await Timer(1, unit="ps")
        assert int(dut.beat_occupancy.value) == 5
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    assert consumed == [1, 2]

    remaining = [await receive_beat(dut) for _ in range(5)]
    assert [(value, last) for value, last, _metadata in remaining] == [
        (3, False),
        (4, False),
        (5, True),
        (6, False),
        (7, True),
    ]


@cocotb.test()
async def adjacent_frames_remain_atomic_under_periodic_backpressure(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)

    expected = [
        (frame * 10 + beat, beat == (frame % 3))
        for frame in range(12)
        for beat in range((frame % 3) + 1)
    ]

    async def produce() -> None:
        for value, last in expected:
            await FallingEdge(dut.clk)
            dut.s_axis_tdata.value = value
            dut.s_axis_tkeep.value = 0xF
            dut.s_axis_tlast.value = last
            dut.s_axis_tuser.value = 0
            dut.s_axis_tvalid.value = 1
            while True:
                await ReadOnly()
                accepted = int(dut.s_axis_tready.value)
                await RisingEdge(dut.clk)
                if accepted:
                    break
                await FallingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.s_axis_tvalid.value = 0

    async def consume() -> list[tuple[int, bool]]:
        actual: list[tuple[int, bool]] = []
        cycle = 0
        while len(actual) < len(expected):
            await FallingEdge(dut.clk)
            cycle += 1
            dut.m_axis_tready.value = int(cycle % 7 not in (2, 3))
            await ReadOnly()
            if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
                actual.append((int(dut.m_axis_tdata.value), bool(dut.m_axis_tlast.value)))
            await RisingEdge(dut.clk)
        return actual

    producer = cocotb.start_soon(produce())
    actual = await with_timeout(consume(), 10, "us")
    await producer
    assert actual == expected, [
        (index, expected_beat, actual_beat)
        for index, (expected_beat, actual_beat) in enumerate(zip(expected, actual, strict=True))
        if expected_beat != actual_beat
    ]
