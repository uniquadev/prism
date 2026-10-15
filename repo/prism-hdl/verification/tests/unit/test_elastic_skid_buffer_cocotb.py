from __future__ import annotations

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer


def spread(index: int, mask: int) -> int:
    """Map a small index to a distinct word that exercises every data bit."""
    return (index * 0x9E3779B1) & mask


@cocotb.test()
async def elastic_skid_buffer_registers_ready_and_preserves_order(dut):
    seed = 29
    random.seed(seed)
    dut._log.info("deterministic_seed=%d", seed)
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    mask = (1 << len(dut.s_data)) - 1

    pending = [spread(index, mask) for index in range(300)]
    expected: list[int] = []
    received: list[int] = []
    active: int | None = None
    for _cycle in range(5000):
        if active is None and pending and random.randrange(4) != 0:
            active = pending.pop(0)
        dut.s_valid.value = int(active is not None)
        if active is not None:
            dut.s_data.value = active

        dut.m_ready.value = 0
        await Timer(1, unit="ps")
        ready_when_stalled = int(dut.s_ready.value)
        dut.m_ready.value = 1
        await Timer(1, unit="ps")
        assert int(dut.s_ready.value) == ready_when_stalled
        dut.m_ready.value = random.randrange(2)
        await Timer(1, unit="ps")

        input_fire = active is not None and int(dut.s_ready.value)
        output_fire = int(dut.m_valid.value) and int(dut.m_ready.value)
        if input_fire:
            expected.append(active)
            active = None
        if output_fire:
            received.append(int(dut.m_data.value))
        await RisingEdge(dut.clk)
        if not pending and active is None and len(received) == len(expected):
            break

    assert len(expected) == 300
    assert received == expected


@cocotb.test()
async def elastic_skid_buffer_covers_occupancy_transitions_and_reset(dut):
    """Check every occupancy/handshake case and sustained one-word-per-cycle flow."""
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    expected: list[int] = []
    mask = (1 << len(dut.s_data)) - 1
    next_word = 0

    async def cycle(valid: int, ready: int, reset: bool = False) -> tuple[bool, bool]:
        nonlocal next_word
        await FallingEdge(dut.clk)
        dut.rst_n.value = int(not reset)
        dut.s_valid.value = valid
        dut.s_data.value = spread(next_word, mask)
        dut.m_ready.value = ready
        await Timer(1, unit="ns")
        if reset:
            await RisingEdge(dut.clk)
            expected.clear()
            return False, False
        assert int(dut.s_ready.value) == int(len(expected) < 2)
        assert int(dut.m_valid.value) == int(bool(expected))
        if expected:
            assert int(dut.m_data.value) == expected[0]
        accepted = bool(valid and int(dut.s_ready.value))
        emitted = bool(ready and expected)
        if emitted:
            expected.pop(0)
        if accepted:
            expected.append(spread(next_word, mask))
            next_word += 1
        await RisingEdge(dut.clk)
        return accepted, emitted

    for occupancy in range(3):
        for valid in range(2):
            for ready in range(2):
                await cycle(0, 0, reset=True)
                for _ in range(occupancy):
                    await cycle(1, 0)
                await cycle(valid, ready)
                for _ in range(3):
                    await cycle(0, 1)
                assert not expected

    await cycle(0, 0, reset=True)
    assert await cycle(1, 1) == (True, False)
    for _ in range(64):
        assert await cycle(1, 1) == (True, True)
    await cycle(1, 0)
    assert len(expected) == 2
    await cycle(1, 0, reset=True)
    await cycle(0, 1)
    assert not expected
