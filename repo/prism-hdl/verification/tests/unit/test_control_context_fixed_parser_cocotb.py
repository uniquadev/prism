"""The 48-byte SINGLE context precheck follows the independent CCL record bytes."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

GOLDEN = bytes.fromhex(
    "01020200ffff0000000200080000200000000001011805dc80ff040802000000"
    "02000000000000010000000208000000"
    "000a000b000a000b"
    "000a00010002010102000000000100000000000108000000"
    "000b00010003010102000000000200010000000108000000"
)


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_body_bytes.value = len(GOLDEN)
    dut.s_manager_mac.value = int.from_bytes(bytes.fromhex("020000000000"), "big")
    dut.s_manager_port.value = 1
    dut.s_link_mtu.value = 1500
    dut.s_max_elements.value = 64
    dut.s_max_original_terms.value = 16
    dut.s_max_kulisch_bits.value = 320
    dut.s_max_window_intervals.value = 16
    dut.s_max_window_bytes.value = 65536
    dut.s_valid.value = 0
    dut.m_read_data.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def parse(dut: Any, body: bytes) -> tuple[int, int]:
    assert len(body) >= 48
    await FallingEdge(dut.clk)
    dut.s_valid.value = 1
    await ReadOnly()
    assert int(dut.s_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_valid.value = 0
    for index, octet in enumerate(body[:48]):
        assert int(dut.m_read_address.value) == 48 + index
        dut.m_read_data.value = octet
        await RisingEdge(dut.clk)
        if index != 47:
            await FallingEdge(dut.clk)
    for _ in range(4):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_valid.value):
            return int(dut.m_accept.value), int(dut.m_error_code.value)
    raise AssertionError("fixed context parser did not complete")


@cocotb.test()
async def golden_single_allreduce_context_preserves_fields_and_report(dut: Any) -> None:
    await initialize(dut)
    assert len(GOLDEN) == 104
    assert await parse(dut, GOLDEN) == (1, 0)
    assert int(dut.m_child_count.value) == 2
    assert int(dut.m_result_count.value) == 2
    assert int(dut.m_original_terms.value) == 2
    assert int(dut.m_maximum_original_terms.value) == 2
    assert int(dut.m_element_count.value) == 1
    assert int(dut.m_kulisch_bits.value) == 280
    assert int(dut.m_accumulator.value) == 0x80
    assert int(dut.m_partial_wire.value) == 0xFF
    assert int(dut.m_output_format.value) == 4
    assert int(dut.m_rank_mask.value) == 8
    for _ in range(3):
        await FallingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_accept.value) == 1


@cocotb.test()
async def insufficient_exact_width_rejected_before_stage_commit(dut: Any) -> None:
    await initialize(dut)
    body = bytearray(GOLDEN)
    body[20:22] = (8).to_bytes(2, "big")
    assert await parse(dut, bytes(body)) == (0, 2)


@cocotb.test()
async def trusted_manager_and_resource_limits_are_checked(dut: Any) -> None:
    await initialize(dut)
    dut.s_manager_port.value = 2
    assert await parse(dut, GOLDEN) == (0, 4)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    dut.s_manager_port.value = 1
    dut.s_max_window_bytes.value = 1024
    assert await parse(dut, GOLDEN) == (0, 3)


@cocotb.test()
async def incompatible_role_or_record_length_rejected(dut: Any) -> None:
    await initialize(dut)
    body = bytearray(GOLDEN)
    body[0] = 2
    assert await parse(dut, bytes(body)) == (0, 1)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_ready.value = 0
    dut.s_body_bytes.value = 103
    assert await parse(dut, GOLDEN) == (0, 1)


@cocotb.test()
async def only_explicit_arithmetic_policy_pairs_are_admitted(dut: Any) -> None:
    await initialize(dut)
    for accumulator, partial, output, rank_mask in (
        (0xFF, 0xFF, 0x04, 0x08),
        (0x80, 0x04, 0x04, 0x08),
        (0x01, 0x04, 0x01, 0x08),
        (0x02, 0x04, 0x04, 0x02),
        (0x02, 0x04, 0x04, 0x08),
    ):
        body = bytearray(GOLDEN)
        body[24:27] = bytes((accumulator, partial, output))
        body[27] |= rank_mask
        body[44] = rank_mask
        assert await parse(dut, bytes(body)) == (0, 2)
        await FallingEdge(dut.clk)
        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.m_ready.value = 0
    for accumulator, partial in ((0x80, 0x80), (0x80, 0xFF), (0x01, 0x04)):
        body = bytearray(GOLDEN)
        body[24:26] = bytes((accumulator, partial))
        assert await parse(dut, bytes(body)) == (1, 0)
        await FallingEdge(dut.clk)
        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.m_ready.value = 0
