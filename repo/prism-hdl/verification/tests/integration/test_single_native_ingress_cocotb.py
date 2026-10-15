"""CONTROL-installed rank bindings drive two physical DATA ports into exact RAM."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
    decode_control_frame,
    encode_control_frame,
)
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

from tests.integration.test_single_control_plane_cocotb import CONTEXT

KEY = OperationKey(1, 1, 0, 1, 1)
NODE = bytes.fromhex("020000000003")
MANAGER = bytes.fromhex("020000000000")
RANKS = (bytes.fromhex("020000000001"), bytes.fromhex("020000000002"))


def key_bits() -> int:
    return (1 << 80) | (1 << 64) | (1 << 32) | 1


def control(command: ControlCommand, transaction: int, body: bytes = b"") -> bytes:
    packet = ControlPacket(KEY, transaction, 0xFFFE, 0xFFFE, command, body=body)
    return encode_control_frame(packet, destination_mac=NODE, source_mac=MANAGER, mtu=1500)


def data(rank: int) -> bytes:
    value = 0x3F800000 if rank == 0 else 0x33800000
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        1,
        10 + rank,
        10 + rank,
        rank + 1,
        0,
        (NumberGroup(ConcreteFormat.FP32, (value,)),),
        last=True,
    )
    return encode_data_frame(
        packet, destination_mac=NODE, source_mac=RANKS[rank], mtu=1500, kulisch_bits=280
    )


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_control_tdata.value = 0
    dut.s_control_tkeep.value = 0
    dut.s_control_tlast.value = 0
    dut.s_control_tuser.value = 0
    dut.s_control_tvalid.value = 0
    for port in range(2):
        dut.s_data_tdata[port].value = 0
        dut.s_data_tkeep[port].value = 0
    dut.s_data_tlast.value = 0
    dut.s_data_tuser.value = 0
    dut.s_data_tvalid.value = 0
    dut.s_local_mac.value = int.from_bytes(NODE, "big")
    dut.s_manager_mac.value = int.from_bytes(MANAGER, "big")
    dut.s_manager_port.value = 1
    dut.s_control_endpoint.value = 0xFFFE
    dut.s_link_mtu.value = 1500
    dut.s_usable_port_mask.value = 0xE
    dut.s_shared_port_demux.value = 0
    dut.s_result_complete_operation.value = 0
    dut.s_result_complete_valid.value = 0
    dut.s_fast_result_read_slot.value = 0
    dut.s_fast_result_read_valid.value = 0
    dut.m_fast_tile_ready.value = 0
    dut.m_control_tready.value = 0
    dut.m_data_event_ready.value = 0b11
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send_control(dut: Any, frame: bytes) -> None:
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        for _ in range(4000):
            await FallingEdge(dut.clk)
            dut.s_control_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            dut.s_control_tkeep.value = (1 << len(beat)) - 1
            dut.s_control_tlast.value = int(offset + len(beat) == len(frame))
            dut.s_control_tvalid.value = 1
            await ReadOnly()
            if int(dut.s_control_tready.value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError("CONTROL input stalled")
    await FallingEdge(dut.clk)
    dut.s_control_tvalid.value = 0


async def expect_ack(dut: Any, transaction: int, status: int = 0) -> None:
    for _ in range(4000):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_control_tvalid.value):
            frame = int(dut.m_control_tdata.value).to_bytes(64, "little")[:60]
            ack = decode_control_frame(frame, mtu=1500)
            assert ack.transaction_id == transaction and ack.status == status
            break
    else:
        raise AssertionError(f"no ACK for {transaction}")
    await FallingEdge(dut.clk)
    dut.m_control_tready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_control_tready.value = 0


async def send_data(dut: Any, rank: int) -> None:
    frame = data(rank)
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        for _ in range(4000):
            await FallingEdge(dut.clk)
            dut.s_data_tdata[rank].value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            dut.s_data_tkeep[rank].value = (1 << len(beat)) - 1
            dut.s_data_tlast.value = int(offset + len(beat) == len(frame)) << rank
            dut.s_data_tvalid.value = 1 << rank
            await ReadOnly()
            if (int(dut.s_data_tready.value) >> rank) & 1:
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"DATA port {rank} stalled")
    await FallingEdge(dut.clk)
    dut.s_data_tvalid.value = 0


async def run_order(dut: Any, order: tuple[int, int]) -> None:
    await initialize(dut)
    await send_control(dut, control(ControlCommand.STAGE, 10, CONTEXT))
    await expect_ack(dut, 10)
    assert int(dut.m_context_installed.value) == 1
    assert int(dut.m_child_count.value) == 2
    await send_control(dut, control(ControlCommand.COMMIT, 11))
    await expect_ack(dut, 11)
    assert int(dut.m_context_active.value) == 1
    for rank in order:
        await send_data(dut, rank)
    for _ in range(5000):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.m_inputs_drained.value):
            break
    else:
        raise AssertionError("DATA did not drain")
    assert int(dut.m_receive_complete.value) & 0x303 == 0x201
    assert int(dut.m_result_store_fault.value) == 0
    await FallingEdge(dut.clk)
    dut.s_fast_result_read_slot.value = 0
    dut.s_fast_result_read_valid.value = 1
    await ReadOnly()
    assert int(dut.s_fast_result_read_ready.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_fast_result_read_valid.value = 0
    for _ in range(500):
        await ReadOnly()
        if int(dut.m_fast_tile_valid.value):
            break
        await FallingEdge(dut.clk)
    else:
        raise AssertionError("no rounded result tile")
    assert int(dut.m_fast_tile_first_element.value) == 0
    assert int(dut.m_fast_tile_keep.value) == 1
    assert int(dut.m_fast_tile_bits.value) & 0xFFFFFFFF == 0x3F800000
    assert int(dut.m_fast_tile_error.value) == 0
    await FallingEdge(dut.clk)
    dut.m_fast_tile_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.m_fast_tile_ready.value = 0
    await FallingEdge(dut.clk)
    dut.s_result_complete_operation.value = key_bits()
    dut.s_result_complete_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.s_result_complete_valid.value = 0
    assert int(dut.m_context_complete.value) == 1
    await send_control(dut, control(ControlCommand.RELEASE, 12))
    await expect_ack(dut, 12)
    assert int(dut.m_context_installed.value) == 0
    for _ in range(20):
        await FallingEdge(dut.clk)
    assert int(dut.m_receive_complete.value) == 0
    assert int(dut.m_fast_tile_valid.value) == 0


@cocotb.test()
async def rank_zero_then_rank_one(dut: Any) -> None:
    await run_order(dut, (0, 1))


@cocotb.test()
async def rank_one_then_rank_zero(dut: Any) -> None:
    await run_order(dut, (1, 0))


@cocotb.test()
async def unassigned_arithmetic_policy_is_rejected(dut: Any) -> None:
    await initialize(dut)
    # The canonical encoder refuses an unassigned policy, so patch the wire bytes.
    frame = bytearray(control(ControlCommand.STAGE, 20, bytes(CONTEXT)))
    body = frame.index(bytes(CONTEXT))
    frame[body + 24 : body + 26] = bytes((0x02, 0x04))
    await send_control(dut, bytes(frame))
    await expect_ack(dut, 20, 2)
    assert int(dut.m_context_installed.value) == 0
