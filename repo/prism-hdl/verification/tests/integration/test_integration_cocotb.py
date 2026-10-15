"""Full active-top lifecycle regression across two operation generations."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import cocotb
from cocotb.utils import get_sim_time
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
    ControlStatus,
    decode_control_frame,
    encode_control_frame,
)
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)

from tests.integration.test_numbergroup_top_cocotb import (
    capture,
    initialize,
    send,
    top_context,
    wait_class,
)
from tests.integration.test_single_native_ingress_cocotb import KEY, MANAGER, NODE, RANKS


def control_frame(
    key: OperationKey, command: ControlCommand, transaction: int, element_count: int = 1
) -> bytes:
    packet = ControlPacket(
        key,
        transaction,
        0xFFFE,
        0xFFFE,
        command,
        body=top_context(element_count) if command == ControlCommand.STAGE else b"",
    )
    return encode_control_frame(packet, destination_mac=NODE, source_mac=MANAGER, mtu=1500)


def rank_frame(key: OperationKey, rank: int, values: tuple[int, ...]) -> bytes:
    packet = DataPacket(
        PacketClass.DATA,
        key,
        1,
        10 + rank,
        10 + rank,
        rank + 1,
        0,
        (NumberGroup(ConcreteFormat.FP32, values),),
        last=True,
    )
    return encode_data_frame(
        packet, destination_mac=NODE, source_mac=RANKS[rank], mtu=1500, kulisch_bits=280
    )


async def run_generation(
    dut: Any,
    frames: list[tuple[int, bytes]],
    key: OperationKey,
    iteration: int,
    values: tuple[int, int],
    expected: int,
) -> None:
    start_control = 3 * (iteration - 1)
    for offset, command in enumerate((ControlCommand.STAGE, ControlCommand.COMMIT), start=1):
        await send(dut, 0, control_frame(key, command, 10 + offset))
        replies = await wait_class(dut, frames, PacketClass.CONTROL, start_control + offset)
        reply = decode_control_frame(replies[-1][1], mtu=1500)
        assert (reply.operation, reply.transaction_id, reply.command, reply.status) == (
            key,
            10 + offset,
            ControlCommand.ACK,
            ControlStatus.OK,
        )

    for rank in (1, 0):
        await send(dut, rank, rank_frame(key, rank, (values[rank],)))
    results = await wait_class(dut, frames, PacketClass.RESULT, 2 * iteration)
    assert {port for port, _frame in results[-2:]} == {0, 1}
    for _port, frame in results[-2:]:
        result_packet = decode_data_frame(frame, mtu=1500, kulisch_bits=280)
        assert result_packet.operation == key
        assert result_packet.groups == (NumberGroup(ConcreteFormat.FP32, (expected,)),)
        assert result_packet.first_element == 0 and result_packet.last

    await send(dut, 0, control_frame(key, ControlCommand.RELEASE, 13))
    replies = await wait_class(dut, frames, PacketClass.CONTROL, start_control + 3)
    reply = decode_control_frame(replies[-1][1], mtu=1500)
    assert (reply.operation, reply.transaction_id, reply.status) == (
        key,
        13,
        ControlStatus.OK,
    )


@cocotb.test()
async def release_reuses_single_resources_for_higher_generation(dut: Any) -> None:
    await initialize(dut)
    frames: list[tuple[int, bytes]] = []
    monitor = cocotb.start_soon(capture(dut, frames))
    await run_generation(dut, frames, KEY, 1, (0x3F800000, 0x3F800000), 0x40000000)
    newer = replace(KEY, operation_generation=KEY.operation_generation + 1)
    await run_generation(dut, frames, newer, 2, (0x3F800000, 0x40000000), 0x40400000)
    monitor.cancel()


@cocotb.test()
async def full_vector_result_rate_is_reported_without_a_physical_claim(dut: Any) -> None:
    await initialize(dut)
    frames: list[tuple[int, bytes]] = []
    monitor = cocotb.start_soon(capture(dut, frames))
    await send(dut, 0, control_frame(KEY, ControlCommand.STAGE, 11, 64))
    assert (
        decode_control_frame(
            (await wait_class(dut, frames, PacketClass.CONTROL, 1))[0][1], mtu=1500
        ).status
        == ControlStatus.OK
    )
    await send(dut, 0, control_frame(KEY, ControlCommand.COMMIT, 12))
    assert (
        decode_control_frame(
            (await wait_class(dut, frames, PacketClass.CONTROL, 2))[1][1], mtu=1500
        ).status
        == ControlStatus.OK
    )
    start_ns = int(get_sim_time(unit="ns"))
    await send(dut, 0, rank_frame(KEY, 0, (0x3F800000,) * 64))
    await send(dut, 1, rank_frame(KEY, 1, (0x40000000,) * 64))
    results = await wait_class(dut, frames, PacketClass.RESULT, 2)
    elapsed_cycles = (int(get_sim_time(unit="ns")) - start_ns) // 4
    assert elapsed_cycles > 0
    for _port, frame in results:
        packet = decode_data_frame(frame, mtu=1500, kulisch_bits=280)
        assert packet.groups == (NumberGroup(ConcreteFormat.FP32, (0x40400000,) * 64),)
        assert len(frame) == 316
    dut._log.info(
        "NumberGroup SINGLE simulated 64-element AllReduce: %d cycles to both "
        "RESULT frames, %d total RESULT frame bytes; not routed timing",
        elapsed_cycles,
        sum(len(frame) for _, frame in results),
    )
    await send(dut, 0, control_frame(KEY, ControlCommand.RELEASE, 13))
    assert (
        decode_control_frame(
            (await wait_class(dut, frames, PacketClass.CONTROL, 3))[2][1], mtu=1500
        ).status
        == ControlStatus.OK
    )
    monitor.cancel()
