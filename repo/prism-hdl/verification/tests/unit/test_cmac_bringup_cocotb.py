"""The CMAC is brought up with the driver's register writes, in the driver's order."""

from __future__ import annotations

import json
import os
import random
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

FEC_ENABLE = 0x107C
FEC_MODE = 0x1000
RX_CONFIGURATION = 0x0014
TX_CONFIGURATION = 0x000C
RX_STATUS = 0x0204
ALIGNED = 0x2
# The build of the sequencer: with or without RS-FEC.
RS_FEC = json.loads(os.environ.get("PRISM_PARAMETERS", "{}")).get("RS_FEC", 1)
BRING_UP = [
    ("reset",),
    *([("write", FEC_ENABLE, 0x3), ("write", FEC_MODE, 0x7)] if RS_FEC else []),
    ("write", RX_CONFIGURATION, 0x1),
    ("write", TX_CONFIGURATION, 0x10),
]
TX_ENABLE = ("write", TX_CONFIGURATION, 0x1)
TX_FAULT = ("write", TX_CONFIGURATION, 0x10)


class Subsystem:
    """Reset handshake and register interface of the CMAC subsystem.

    The handshake follows the reset block of the shell: done is low from
    power-up, drops a few cycles after a request and rises when the reset has
    run. The register interface accepts address and data in any order with
    random stalls. Every access while a reset is running is an error of the
    master.
    """

    def __init__(self, dut: Any, *, reset_cycles: int = 20, seed: int = 1) -> None:
        self.dut = dut
        self.reset_cycles = reset_cycles
        self.random = random.Random(seed)
        self.events: list[tuple[Any, ...]] = []
        self.reads = 0
        # Values of the next status reads; afterwards `status` is returned.
        self.queued_status: list[int] = []
        self.status = 0
        self.resetting = False
        dut.s_reset_done.value = 0
        dut.m_awready.value = 0
        dut.m_wready.value = 0
        dut.m_bvalid.value = 0
        dut.m_bresp.value = 0
        dut.m_arready.value = 0
        dut.m_rvalid.value = 0
        dut.m_rdata.value = 0
        dut.m_rresp.value = 0
        cocotb.start_soon(self._reset())
        cocotb.start_soon(self._write())
        cocotb.start_soon(self._read())

    def writes(self) -> list[tuple[Any, ...]]:
        return [event for event in self.events if event[0] != "read"]

    async def _reset(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk)
            if int(dut.rst_n.value) and not int(dut.m_reset_n.value):
                assert not self.resetting, "a reset was asked for while one was running"
                self.events.append(("reset",))
                self.resetting = True
                for _ in range(3):
                    await RisingEdge(dut.clk)
                    assert int(dut.m_reset_n.value), "the reset request is one cycle"
                await FallingEdge(dut.clk)
                dut.s_reset_done.value = 0
                for _ in range(self.reset_cycles):
                    await RisingEdge(dut.clk)
                    assert int(dut.m_reset_n.value), "the reset request is one cycle"
                await FallingEdge(dut.clk)
                dut.s_reset_done.value = 1
                self.resetting = False

    async def _write(self) -> None:
        dut = self.dut
        address: int | None = None
        data: int | None = None
        while True:
            await FallingEdge(dut.clk)
            dut.m_awready.value = int(address is None and self.random.random() < 0.6)
            dut.m_wready.value = int(data is None and self.random.random() < 0.6)
            await RisingEdge(dut.clk)
            if int(dut.m_awvalid.value) and int(dut.m_awready.value):
                address = int(dut.m_awaddr.value)
            if int(dut.m_wvalid.value) and int(dut.m_wready.value):
                data = int(dut.m_wdata.value)
            if address is None or data is None:
                continue
            assert not self.resetting, "a register was written during a reset"
            assert int(dut.s_reset_done.value), "a register was written before the reset was done"
            self.events.append(("write", address, data))
            address = data = None
            await FallingEdge(dut.clk)
            dut.m_awready.value = 0
            dut.m_wready.value = 0
            for _ in range(self.random.randrange(3)):
                await FallingEdge(dut.clk)
            dut.m_bvalid.value = 1
            while True:
                await RisingEdge(dut.clk)
                if int(dut.m_bready.value):
                    break
            await FallingEdge(dut.clk)
            dut.m_bvalid.value = 0

    async def _read(self) -> None:
        dut = self.dut
        while True:
            await FallingEdge(dut.clk)
            dut.m_arready.value = int(self.random.random() < 0.6)
            await RisingEdge(dut.clk)
            if not (int(dut.m_arvalid.value) and int(dut.m_arready.value)):
                continue
            assert not self.resetting, "a register was read during a reset"
            self.events.append(("read", int(dut.m_araddr.value)))
            self.reads += 1
            value = self.queued_status.pop(0) if self.queued_status else self.status
            await FallingEdge(dut.clk)
            dut.m_arready.value = 0
            for _ in range(self.random.randrange(3)):
                await FallingEdge(dut.clk)
            dut.m_rdata.value = value
            dut.m_rvalid.value = 1
            while True:
                await RisingEdge(dut.clk)
                if int(dut.m_rready.value):
                    break
            await FallingEdge(dut.clk)
            dut.m_rvalid.value = 0


async def start(dut: Any, **arguments: Any) -> Subsystem:
    cocotb.start_soon(Clock(dut.clk, 8, unit="ns").start())
    dut.rst_n.value = 0
    subsystem = Subsystem(dut, **arguments)
    for _ in range(4):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    return subsystem


async def until(dut: Any, condition: Any, *, cycles: int = 4000) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        if condition():
            return
    raise AssertionError("the expected state was not reached")


@cocotb.test()
async def link_comes_up_with_the_writes_of_the_driver_in_their_order(dut: Any) -> None:
    subsystem = await start(dut, reset_cycles=60)
    subsystem.status = ALIGNED
    await until(dut, lambda: int(dut.m_link_up.value) == 1)
    assert subsystem.writes() == [*BRING_UP, TX_ENABLE]
    # The status is read twice before it is believed, and nothing else is read.
    reads = [event for event in subsystem.events if event[0] == "read"]
    assert reads == [("read", RX_STATUS)] * 2
    # The transmitter is enabled only after the status has been read.
    assert subsystem.events.index(TX_ENABLE) > subsystem.events.index(("read", RX_STATUS))


@cocotb.test()
async def latched_first_read_does_not_enable_the_transmitter(dut: Any) -> None:
    """The first read of a look returns what the MAC latched earlier."""
    subsystem = await start(dut)
    subsystem.queued_status = [ALIGNED, 0, ALIGNED, 0, ALIGNED, 0, 0, ALIGNED]
    await until(dut, lambda: subsystem.reads == 6)
    assert int(dut.m_link_up.value) == 0
    assert subsystem.writes() == BRING_UP
    await until(dut, lambda: int(dut.m_link_up.value) == 1)
    assert subsystem.writes() == [*BRING_UP, TX_ENABLE]
    # Three looks ended on a value without alignment; the fourth is the
    # first whose second read is aligned, and only then the transmitter
    # is enabled.
    before = subsystem.events[: subsystem.events.index(TX_ENABLE)]
    assert before.count(("read", RX_STATUS)) == 8


@cocotb.test()
async def lost_alignment_returns_to_remote_fault_until_aligned_again(dut: Any) -> None:
    subsystem = await start(dut)
    subsystem.status = ALIGNED
    await until(dut, lambda: int(dut.m_link_up.value) == 1)
    # The link stays up while the receiver stays aligned.
    watched = subsystem.reads
    await until(dut, lambda: subsystem.reads >= watched + 6)
    assert int(dut.m_link_up.value) == 1
    assert subsystem.writes() == [*BRING_UP, TX_ENABLE]

    subsystem.status = 0
    await until(dut, lambda: int(dut.m_link_up.value) == 0)
    await until(dut, lambda: subsystem.writes()[-1] == TX_FAULT)
    assert subsystem.writes() == [*BRING_UP, TX_ENABLE, TX_FAULT]
    lost = subsystem.reads
    await until(dut, lambda: subsystem.reads >= lost + 6)
    assert int(dut.m_link_up.value) == 0
    assert subsystem.writes() == [*BRING_UP, TX_ENABLE, TX_FAULT]

    subsystem.status = ALIGNED
    await until(dut, lambda: int(dut.m_link_up.value) == 1)
    assert subsystem.writes() == [*BRING_UP, TX_ENABLE, TX_FAULT, TX_ENABLE]
