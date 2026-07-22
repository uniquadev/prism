from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


async def reset(dut: object, cycles: int = 4) -> None:
    """Start the test clock and apply the active-low DUT reset."""

    if cycles < 1:
        raise ValueError("reset cycles must be positive")
    dynamic_dut = cast(Any, dut)  # Cocotb discovers DUT handles at runtime.
    dynamic_dut.rst_n.value = 0
    await Clock(dynamic_dut.clk, 4, unit="ns").start(start_high=False)
    for _ in range(cycles):
        await RisingEdge(dynamic_dut.clk)
    dynamic_dut.rst_n.value = 1
    await RisingEdge(dynamic_dut.clk)


async def wait_until(clock: object, predicate: Callable[[], bool], timeout: int = 1000) -> None:
    """Wait for a predicate at rising edges, bounded by a cycle timeout."""

    if timeout < 1:
        raise ValueError("timeout must be positive")
    dynamic_clock = cast(Any, clock)  # Cocotb clock handles are runtime-defined.
    for _ in range(timeout):
        await RisingEdge(dynamic_clock)
        if predicate():
            return
    raise AssertionError(f"condition not reached within {timeout} cycles")
