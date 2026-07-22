from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


async def reset(dut) -> None:
    dut.rst_n.value = 0
    dut.s_awvalid.value = 0
    dut.s_wvalid.value = 0
    dut.s_bready.value = 0
    dut.s_arvalid.value = 0
    dut.s_rready.value = 0
    dut.s_awaddr.value = 0
    dut.s_wdata.value = 0
    dut.s_araddr.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1


@cocotb.test()
async def independent_windows_accept_split_writes_and_stalled_reads(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    await reset(dut)

    # Interface 0 receives AW before W; interface 1 receives W before AW.
    dut.s_awvalid.value = 0b01
    dut.s_wvalid.value = 0b10
    await Timer(1, unit="ps")
    assert int(dut.s_awready.value) == 0b11
    assert int(dut.s_wready.value) == 0b11
    await RisingEdge(dut.clk)
    dut.s_awvalid.value = 0
    dut.s_wvalid.value = 0

    dut.s_awvalid.value = 0b10
    dut.s_wvalid.value = 0b01
    await Timer(1, unit="ps")
    assert int(dut.s_awready.value) == 0b10
    assert int(dut.s_wready.value) == 0b01
    await RisingEdge(dut.clk)
    dut.s_awvalid.value = 0
    dut.s_wvalid.value = 0
    await Timer(1, unit="ps")
    assert int(dut.s_bvalid.value) == 0b11
    assert int(dut.s_bresp.value) == 0

    for _ in range(3):
        await RisingEdge(dut.clk)
        assert int(dut.s_bvalid.value) == 0b11
    dut.s_bready.value = 0b11
    await RisingEdge(dut.clk)
    dut.s_bready.value = 0
    await Timer(1, unit="ps")
    assert int(dut.s_bvalid.value) == 0

    dut.s_araddr.value = (0x04 << 32) | 0x00
    dut.s_arvalid.value = 0b11
    await Timer(1, unit="ps")
    assert int(dut.s_arready.value) == 0b11
    await RisingEdge(dut.clk)
    dut.s_arvalid.value = 0
    await Timer(1, unit="ps")
    assert int(dut.s_rvalid.value) == 0b11
    assert int(dut.s_rdata.value) & 0xFFFFFFFF == 0x50524953
    assert (int(dut.s_rdata.value) >> 32) & 0xFFFFFFFF == 0x00010000
    assert int(dut.s_rresp.value) == 0

    dut.s_rready.value = 0b01
    await RisingEdge(dut.clk)
    dut.s_rready.value = 0
    await Timer(1, unit="ps")
    assert int(dut.s_rvalid.value) == 0b10
    assert (int(dut.s_rdata.value) >> 32) & 0xFFFFFFFF == 0x00010000

    dut.s_rready.value = 0b10
    await RisingEdge(dut.clk)
    dut.s_rready.value = 0
    await Timer(1, unit="ps")
    assert int(dut.s_rvalid.value) == 0

    # Reset must retire partially assembled writes and held responses.
    dut.s_awvalid.value = 0b01
    await RisingEdge(dut.clk)
    dut.s_awvalid.value = 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ps")
    assert int(dut.s_bvalid.value) == 0
    assert int(dut.s_rvalid.value) == 0
