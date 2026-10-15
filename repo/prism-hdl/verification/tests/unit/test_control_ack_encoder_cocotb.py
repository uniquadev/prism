"""CONTROL ACK bytes and backpressure match the independent wire contract."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 01 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0a0b0c0d 0304 0102 05 03 0000 00 01 "
    "000000000000000000000000"
)


def operation() -> int:
    return (
        (0x0102030405060708 << 80) | (0x1122 << 64) | (0x3344 << 48) | (0x5566 << 32) | 0x778899AA
    )


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_operation.value = operation()
    dut.s_transaction_id.value = 0x0A0B0C0D
    dut.s_source_endpoint.value = 0x0304
    dut.s_destination_endpoint.value = 0x0102
    dut.s_source_mac.value = int.from_bytes(bytes.fromhex("66778899aabb"), "big")
    dut.s_destination_mac.value = int.from_bytes(bytes.fromhex("001122334455"), "big")
    dut.s_status.value = 3
    dut.s_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


@cocotb.test()
async def golden_ack_one_beat_and_held_under_stall(dut: Any) -> None:
    await initialize(dut)
    assert len(GOLDEN) == 60
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(4):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_axis_tvalid.value) == 1
        assert int(dut.m_axis_tlast.value) == 1
        assert int(dut.m_axis_tkeep.value) == (1 << 60) - 1
        assert int(dut.m_frame_bytes.value) == 60
        payload = int(dut.m_axis_tdata.value).to_bytes(64, "little")
        assert payload[:60] == GOLDEN
        assert payload[60:] == bytes(4)
    await FallingEdge(dut.clk)
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.m_axis_tvalid.value) == 0


@cocotb.test()
async def ready_valid_turnover_retains_new_status(dut: Any) -> None:
    await initialize(dut)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_status.value = 7
    dut.m_axis_tready.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    dut.m_axis_tready.value = 0
    assert int(dut.m_axis_tvalid.value) == 1
    assert (int(dut.m_axis_tdata.value) >> (43 * 8)) & 0xFF == 7
