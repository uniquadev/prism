"""The active two-port top routes in-band SINGLE frames without an old ABI."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.wire.control import (
    ContextRecord,
    ControlCommand,
    decode_control_frame,
)
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)

from tests.integration.test_single_control_plane_cocotb import CONTEXT, KEY, NODE
from tests.integration.test_single_native_core_cocotb import expected_result
from tests.integration.test_single_native_ingress_cocotb import (
    RANKS,
    control,
    data,
)


def top_context(element_count: int = 1) -> bytes:
    old = ContextRecord.unpack(CONTEXT)
    return replace(
        old,
        element_count=element_count,
        manager_port=0,
        bindings=tuple(
            replace(binding, local_port=slot) for slot, binding in enumerate(old.bindings)
        ),
    ).pack()


async def initialize(dut: Any) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.millisecond_tick.value = 0
    dut.laboratory_extension_enabled.value = 0
    dut.local_mac_0.value = int.from_bytes(NODE, "big")
    dut.local_mac_1.value = int.from_bytes(NODE, "big")
    for port in range(2):
        getattr(dut, f"s{port}_tdata").value = 0
        getattr(dut, f"s{port}_tkeep").value = 0
        getattr(dut, f"s{port}_tlast").value = 0
        getattr(dut, f"s{port}_tuser").value = 0
        getattr(dut, f"s{port}_tvalid").value = 0
        getattr(dut, f"m{port}_tready").value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def send(dut: Any, port: int, frame: bytes) -> None:
    for offset in range(0, len(frame), 64):
        beat = frame[offset : offset + 64]
        for _ in range(5000):
            await FallingEdge(dut.clk)
            getattr(dut, f"s{port}_tdata").value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            getattr(dut, f"s{port}_tkeep").value = (1 << len(beat)) - 1
            getattr(dut, f"s{port}_tlast").value = int(offset + len(beat) == len(frame))
            getattr(dut, f"s{port}_tvalid").value = 1
            await ReadOnly()
            if int(getattr(dut, f"s{port}_tready").value):
                await RisingEdge(dut.clk)
                break
        else:
            raise AssertionError(f"physical port {port} stalled")
    await FallingEdge(dut.clk)
    getattr(dut, f"s{port}_tvalid").value = 0


async def capture(dut: Any, frames: list[tuple[int, bytes]]) -> None:
    partial = [bytearray(), bytearray()]
    while True:
        await FallingEdge(dut.clk)
        await ReadOnly()
        for port in range(2):
            if int(getattr(dut, f"m{port}_tvalid").value) and int(
                getattr(dut, f"m{port}_tready").value
            ):
                width = int(getattr(dut, f"m{port}_tkeep").value).bit_count()
                partial[port].extend(
                    int(getattr(dut, f"m{port}_tdata").value).to_bytes(64, "little")[:width]
                )
                if int(getattr(dut, f"m{port}_tlast").value):
                    assert len(partial[port]) == int(getattr(dut, f"m{port}_frame_bytes").value)
                    frames.append((port, bytes(partial[port])))
                    partial[port].clear()


async def wait_class(
    dut: Any, frames: list[tuple[int, bytes]], packet_class: int, count: int
) -> list[tuple[int, bytes]]:
    for _ in range(6000):
        await FallingEdge(dut.clk)
        found = [(port, frame) for port, frame in frames if frame[15] == packet_class]
        if len(found) >= count:
            return found
    raise AssertionError(f"only {len(found)} class-{packet_class} frames")


@cocotb.test()
async def physical_port_mux_single_allreduce(dut: Any) -> None:
    await initialize(dut)
    frames: list[tuple[int, bytes]] = []
    monitor = cocotb.start_soon(capture(dut, frames))
    await send(dut, 0, control(ControlCommand.STAGE, 10, top_context()))
    ack = await wait_class(dut, frames, 1, 1)
    assert ack[0][0] == 0
    assert decode_control_frame(ack[0][1], mtu=1500).status == 0
    await send(dut, 0, control(ControlCommand.COMMIT, 11))
    ack = await wait_class(dut, frames, 1, 2)
    assert decode_control_frame(ack[1][1], mtu=1500).status == 0
    await send(dut, 1, data(1))
    await send(dut, 0, data(0))
    results = await wait_class(dut, frames, 3, 2)
    for port, frame in results:
        assert frame == expected_result(port)
        assert decode_data_frame(frame, mtu=1500, kulisch_bits=280).packet_id == port + 1
    await send(dut, 0, control(ControlCommand.RELEASE, 12))
    ack = await wait_class(dut, frames, 1, 3)
    assert decode_control_frame(ack[2][1], mtu=1500).status == 0
    monitor.cancel()


def rank_chunk(
    rank: int, first: int, values: tuple[int, ...], packet_id: int, *, last: bool
) -> bytes:
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        1,
        10 + rank,
        10 + rank,
        packet_id,
        first,
        (NumberGroup(ConcreteFormat.FP32, values),),
        last=last,
    )
    return encode_data_frame(
        packet, destination_mac=NODE, source_mac=RANKS[rank], mtu=1500, kulisch_bits=280
    )


@cocotb.test()
async def unequal_rank_chunking_keeps_global_positions(dut: Any) -> None:
    await initialize(dut)
    frames: list[tuple[int, bytes]] = []
    monitor = cocotb.start_soon(capture(dut, frames))
    await send(dut, 0, control(ControlCommand.STAGE, 10, top_context(2)))
    assert decode_control_frame((await wait_class(dut, frames, 1, 1))[0][1], mtu=1500).status == 0
    await send(dut, 0, control(ControlCommand.COMMIT, 11))
    assert decode_control_frame((await wait_class(dut, frames, 1, 2))[1][1], mtu=1500).status == 0
    await send(dut, 0, rank_chunk(0, 0, (0x3F800000,), 1, last=False))
    await send(dut, 1, rank_chunk(1, 0, (0x40000000, 0x40400000), 2, last=True))
    await send(dut, 0, rank_chunk(0, 1, (0x40000000,), 3, last=True))
    results = await wait_class(dut, frames, 3, 2)
    for _port, frame in results:
        packet = decode_data_frame(frame, mtu=1500, kulisch_bits=280)
        assert packet.first_element == 0 and packet.element_count == 2 and packet.last
        assert packet.groups == (NumberGroup(ConcreteFormat.FP32, (0x40400000, 0x40A00000)),)
    await send(dut, 0, control(ControlCommand.RELEASE, 12))
    assert decode_control_frame((await wait_class(dut, frames, 1, 3))[2][1], mtu=1500).status == 0
    monitor.cancel()


@cocotb.test()
async def capability_query_is_not_implemented_in_single(dut: Any) -> None:
    await initialize(dut)
    frames: list[tuple[int, bytes]] = []
    monitor = cocotb.start_soon(capture(dut, frames))
    query = control(ControlCommand.CAPS_QUERY, 7)
    for count in (1, 2):
        await send(dut, 0, query)
        responses = await wait_class(dut, frames, 1, count)
        assert len(responses) == count
        response = decode_control_frame(responses[-1][1], mtu=1500)
        assert response.command == ControlCommand.ACK
        assert response.transaction_id == 7 and response.status == 1
    monitor.cancel()
