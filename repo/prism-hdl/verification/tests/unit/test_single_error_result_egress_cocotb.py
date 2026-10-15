"""Terminal arithmetic errors reach each configured SINGLE result recipient."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import OperationKey
from prism_ccl.wire.data import PacketClass, decode_data_frame


@cocotb.test()
async def error_results_are_single_beat_and_stable_under_backpressure(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    node_mac = bytes.fromhex("020000000003")
    peer_macs = (bytes.fromhex("020000000001"), bytes.fromhex("020000000002"))
    key = OperationKey(1, 1, 0, 1, 1)
    dut.rst_n.value = 0
    dut.s_start_valid.value = 0
    dut.s_clear.value = 0
    dut.s_operation.value = (1 << 80) | (1 << 64) | (1 << 32) | 1
    dut.s_element_count.value = 16
    dut.s_mtu.value = 1500
    dut.s_kulisch_bits.value = 320
    dut.s_auto_output.value = 0
    dut.s_native_input.value = 0
    dut.s_native_wide.value = 0
    dut.s_error_only.value = 1
    dut.s_child_count.value = 2
    dut.s_result_enabled.value = 3
    dut.s_local_endpoints.value = (11 << 16) | 10
    dut.s_peer_endpoints.value = (2 << 16) | 1
    dut.s_local_ports.value = (3 << 16) | 2
    dut.s_peer_macs.value = (int.from_bytes(peer_macs[1], "big") << 48) | int.from_bytes(
        peer_macs[0], "big"
    )
    dut.s_local_mac.value = int.from_bytes(node_mac, "big")
    dut.m_store_read_ready.value = 0
    dut.s_tile_first_element.value = 0
    dut.s_tile_keep.value = 0
    dut.s_tile_tags.value = 0
    dut.s_tile_integers.value = 0
    dut.s_tile_native_bits.value = 0
    dut.s_tile_error.value = 0
    dut.s_tile_valid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    dut.s_start_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_start_valid.value = 0

    for recipient in range(2):
        for _ in range(20):
            await FallingEdge(dut.clk)
            await ReadOnly()
            if int(dut.m_axis_tvalid.value):
                break
        else:
            raise AssertionError("terminal RESULT did not reach the egress")
        assert int(dut.m_store_read_valid.value) == 0
        assert int(dut.m_axis_frame_bytes.value) == 60
        assert int(dut.m_axis_tkeep.value) == (1 << 60) - 1
        assert int(dut.m_axis_tlast.value) == 1
        assert int(dut.m_egress_port.value) == recipient + 2
        encoded = int(dut.m_axis_tdata.value).to_bytes(64, "little")[:60]
        for _ in range(3):
            await FallingEdge(dut.clk)
            await ReadOnly()
            assert int(dut.m_axis_tvalid.value) == 1
            assert int(dut.m_axis_tdata.value).to_bytes(64, "little")[:60] == encoded
        result = decode_data_frame(encoded, mtu=1500, kulisch_bits=320)
        assert result.packet_class == PacketClass.RESULT
        assert result.operation == key
        assert result.accumulation_inexact
        assert result.source_endpoint == recipient + 10
        assert result.destination_endpoint == recipient + 1
        assert result.stream_id == recipient + 1
        await FallingEdge(dut.clk)
        dut.m_axis_tready.value = 1
        await RisingEdge(dut.clk)
        # The frame is one beat and is offered once: with the output still
        # ready, nothing follows it at once.
        for _ in range(2):
            await FallingEdge(dut.clk)
            await ReadOnly()
            assert int(dut.m_axis_tvalid.value) == 0
        await FallingEdge(dut.clk)
        dut.m_axis_tready.value = 0

    for _ in range(20):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_all_sent.value):
            break
    else:
        raise AssertionError("terminal RESULT send did not finish")
    assert int(dut.m_sent_mask.value) == 3
    assert int(dut.m_fault.value) == 0
