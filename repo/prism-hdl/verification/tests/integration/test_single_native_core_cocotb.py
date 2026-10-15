"""In-band SINGLE CONTROL and rank DATA produce exact native RESULT frames."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import ExactValue, encode_kulisch
from prism_ccl.wire.control import ControlCommand
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

from tests.integration.test_single_control_plane_cocotb import CONTEXT, KEY, NODE
from tests.integration.test_single_native_ingress_cocotb import (
    MANAGER,
    RANKS,
    control,
    expect_ack,
    send_control,
    send_data,
)


def reduce_context() -> bytes:
    fixed = bytearray(CONTEXT[:48])
    fixed[2] = 1
    fixed[28] = 1
    bindings = bytearray(CONTEXT[56:])
    bindings[7] = 0
    return bytes(fixed) + CONTEXT[48:52] + CONTEXT[54:56] + bytes(bindings)


def expected_result(slot: int) -> bytes:
    packet = DataPacket(
        PacketClass.RESULT,
        KEY,
        10 + slot,
        1,
        1,
        slot + 1,
        0,
        (NumberGroup(ConcreteFormat.FP32, (0x3F800000,)),),
        last=True,
    )
    return encode_data_frame(
        packet, destination_mac=RANKS[slot], source_mac=NODE, mtu=1500, kulisch_bits=280
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
    dut.m_control_tready.value = 0
    dut.m_result_tready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def scenario(dut: Any, context: bytes, destinations: tuple[int, ...]) -> None:
    await initialize(dut)
    await send_control(dut, control(ControlCommand.STAGE, 10, context))
    await expect_ack(dut, 10)
    assert int(dut.m_context_installed.value) == 1
    await send_control(dut, control(ControlCommand.COMMIT, 11))
    await expect_ack(dut, 11)
    assert int(dut.m_context_active.value) == 1
    await send_data(dut, 1)
    await send_data(dut, 0)
    received = bytearray()
    completed = 0
    for cycle in range(6000):
        await FallingEdge(dut.clk)
        dut.m_result_tready.value = int(cycle % 7 != 3)
        await ReadOnly()
        assert int(dut.m_fault.value) == 0
        if int(dut.m_result_tvalid.value) and int(dut.m_result_tready.value):
            slot = destinations[completed]
            expected = expected_result(slot)
            assert int(dut.m_result_port.value) == 2 + slot
            assert int(dut.m_result_frame_bytes.value) == len(expected)
            size = int(dut.m_result_tkeep.value).bit_count()
            received.extend(int(dut.m_result_tdata.value).to_bytes(64, "little")[:size])
            if int(dut.m_result_tlast.value):
                assert bytes(received) == expected
                received.clear()
                completed += 1
        await RisingEdge(dut.clk)
        if int(dut.m_result_all_sent.value):
            break
    assert completed == len(destinations)
    assert int(dut.m_result_sent_mask.value) == sum(1 << slot for slot in destinations)
    for _ in range(5):
        await FallingEdge(dut.clk)
    assert int(dut.m_context_complete.value) == 1
    await send_control(dut, control(ControlCommand.RELEASE, 12))
    await expect_ack(dut, 12)
    assert int(dut.m_context_installed.value) == 0


@cocotb.test()
async def allreduce_two_rank_frames_and_results(dut: Any) -> None:
    await scenario(dut, CONTEXT, (0, 1))


@cocotb.test()
async def reduce_only_the_selected_rank_receives_result(dut: Any) -> None:
    await scenario(dut, reduce_context(), (1,))


@cocotb.test()
async def exact_result_reaches_both_ranks_without_final_rounding(dut: Any) -> None:
    await initialize(dut)
    context = bytearray(CONTEXT)
    context[20:22] = (320).to_bytes(2, "big")
    context[26] = 0x80
    await send_control(dut, control(ControlCommand.STAGE, 10, bytes(context)))
    await expect_ack(dut, 10)
    assert int(dut.m_context_installed.value) == 1
    await send_control(dut, control(ControlCommand.COMMIT, 11))
    await expect_ack(dut, 11)
    await send_data(dut, 0)
    await send_data(dut, 1)

    value = ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24))
    encoded = encode_kulisch(value, 320)
    expected = [
        encode_data_frame(
            DataPacket(
                PacketClass.RESULT,
                KEY,
                10 + slot,
                1,
                1,
                slot + 1,
                0,
                (NumberGroup(ConcreteFormat.KULISCH, (encoded,)),),
                last=True,
            ),
            destination_mac=RANKS[slot],
            source_mac=NODE,
            mtu=1500,
            kulisch_bits=320,
        )
        for slot in (0, 1)
    ]
    frames: list[bytes] = []
    partial = bytearray()
    for _ in range(10000):
        await FallingEdge(dut.clk)
        dut.m_result_tready.value = 1
        await ReadOnly()
        assert int(dut.m_fault.value) == 0
        if int(dut.m_result_tvalid.value):
            size = int(dut.m_result_tkeep.value).bit_count()
            partial.extend(int(dut.m_result_tdata.value).to_bytes(64, "little")[:size])
            if int(dut.m_result_tlast.value):
                frames.append(bytes(partial))
                partial.clear()
        await RisingEdge(dut.clk)
        if len(frames) == 2 and int(dut.m_result_all_sent.value):
            break
    assert frames == expected
    assert int(dut.m_result_sent_mask.value) == 0b11
