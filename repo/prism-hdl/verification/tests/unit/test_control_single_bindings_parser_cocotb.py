"""SINGLE binding arrays are read in order and rejected transactionally."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

CONTEXT = bytes.fromhex(
    "01020200ffff0000000200080000200000000001011805dc80ff040802000000"
    "02000000000000010000000208000000"
    "000a000b000a000b"
    "000a00010002010102000000000100000000000108000000"
    "000b00010003010102000000000200010000000108000000"
)


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_child_count.value = 2
    dut.s_result_count.value = 2
    dut.s_rank_mask.value = 8
    dut.s_accepted_mask.value = 8
    dut.s_manager_mac.value = int.from_bytes(bytes.fromhex("020000000000"), "big")
    dut.s_local_mac.value = int.from_bytes(bytes.fromhex("020000000003"), "big")
    dut.s_supported_ports.value = 0xE
    dut.s_shared_port_demux.value = 0
    dut.s_valid.value = 0
    dut.m_read_data.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def parse(dut: Any, context: bytes) -> tuple[int, int]:
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for _ in range(200):
        if int(dut.m_valid.value):
            return int(dut.m_accept.value), int(dut.m_error_code.value)
        address = int(dut.m_read_address.value)
        index = address - 48
        dut.m_read_data.value = context[index] if 0 <= index < len(context) else 0
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    raise AssertionError("SINGLE binding parser failed to finish")


@cocotb.test()
async def independent_single_binding_bytes_retain_rank_ports_and_results(dut: Any) -> None:
    await initialize(dut)
    assert len(CONTEXT) == 104
    assert await parse(dut, CONTEXT) == (1, 0)
    assert int(dut.m_local_endpoints.value) & 0xFFFFFFFF == (11 << 16) | 10
    assert int(dut.m_peer_endpoints.value) & 0xFFFFFFFF == (1 << 16) | 1
    assert int(dut.m_local_ports.value) & 0xFFFFFFFF == (3 << 16) | 2
    assert int(dut.m_rank_ids.value) & 0xFFFFFFFF == 1 << 16
    assert int(dut.m_native_masks.value) & 0xFFFF == 0x0808
    assert int(dut.m_result_enabled.value) & 0b11 == 0b11


@cocotb.test()
async def duplicate_rank_or_wrong_result_list_is_rejected(dut: Any) -> None:
    await initialize(dut)
    body = bytearray(CONTEXT)
    second_binding = 48 + 8 + 24
    body[second_binding + 14 : second_binding + 16] = (0).to_bytes(2, "big")
    assert await parse(dut, bytes(body)) == (0, 4)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    body = bytearray(CONTEXT)
    body[48:50] = (11).to_bytes(2, "big")
    assert await parse(dut, bytes(body)) == (0, 4)


@cocotb.test()
async def unsupported_or_undemultiplexed_shared_port_is_rejected(dut: Any) -> None:
    await initialize(dut)
    body = bytearray(CONTEXT)
    second_binding = 48 + 8 + 24
    body[second_binding + 4 : second_binding + 6] = (2).to_bytes(2, "big")
    assert await parse(dut, bytes(body)) == (0, 4)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    dut.s_shared_port_demux.value = 1
    assert await parse(dut, bytes(body)) == (1, 0)


@cocotb.test()
async def every_reserved_binding_byte_must_be_zero(dut: Any) -> None:
    await initialize(dut)
    for offset in (21, 22, 23):
        body = bytearray(CONTEXT)
        body[48 + 8 + offset] = 1
        assert await parse(dut, bytes(body)) == (0, 4)
        await FallingEdge(dut.clk)
        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.m_ready.value = 0
