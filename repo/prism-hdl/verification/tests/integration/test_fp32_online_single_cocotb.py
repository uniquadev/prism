"""SINGLE must commit FP32 additions before all contributors have arrived."""

from __future__ import annotations

import struct

import cocotb
from ccl.examples import shared_port_world
from ccl.world import CocotbSingleBackend, CompiledFramePorts, compile_single
from cocotb.triggers import ReadOnly, RisingEdge
from prism_ccl.domain.model import AccumulatorPolicy, ConcreteFormat, PartialWirePolicy, TypedVector
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
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


def add32(a, b):
    floats = [struct.unpack(">f", x.to_bytes(4, "big"))[0] for x in (a, b)]
    return int.from_bytes(struct.pack(">f", sum(floats)), "big")


@cocotb.test()
async def online_arrival_order_atomic_rejection_and_release(dut):
    values = {0: 0x3F800000, 1: 0x33800000, 2: 0xBF800000}
    for case, order in enumerate(((0, 1, 2), (0, 2, 1))):
        world, tree = shared_port_world()
        world.register_reduce(
            "online",
            tree=tree,
            vectors={
                rank: TypedVector(ConcreteFormat.FP32, (bits,) * 35)
                for rank, bits in values.items()
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.FP32_ARRIVAL,
            partial_wire=PartialWirePolicy.FP32,
        )
        scenario = world._scenarios["online"]
        binding = compile_single(world.network, scenario, "s")
        backend = CocotbSingleBackend(dut, prism_name="s")
        ports = CompiledFramePorts(dut, timeout_cycles=6000, output_stall_period=5)
        await ports.start(binding.node_mac, start_clock=case == 0)
        commits = {}
        engine = dut.u_core.u_single.u_ingress.gen_arrival_round.u_arrival

        async def observe(engine, commits):
            while True:
                await RisingEdge(dut.clk)
                await ReadOnly()
                for bank in range(4):
                    state = engine.gen_bank[bank].u_state
                    if int(state.m_valid.value) and int(state.m_ready.value):
                        slot = int(state.m_row.value) * 4 + bank
                        bits, counts = commits.get(slot, (0, 0))
                        keep = int(state.m_keep.value)
                        for lane in range(16):
                            if keep & (1 << lane):
                                mask = 0xFFFFFFFF << (lane * 32)
                                bits = (bits & ~mask) | (int(state.m_bits.value) & mask)
                                mask = 15 << (lane * 4)
                                counts = (counts & ~mask) | (int(state.m_counts.value) & mask)
                        commits[slot] = (bits, counts)

        monitor = cocotb.start_soon(observe(engine, commits))
        try:
            # Build a valid control frame, then mutate the policy byte independently
            # of the codec so software validation cannot hide an RTL acceptance bug.
            if case == 0:
                stage = ControlPacket(
                    scenario.config.key,
                    8,
                    0xFFFE,
                    0xFFFE,
                    ControlCommand.STAGE,
                    body=binding.context.pack(),
                )
                invalid = bytearray(
                    encode_control_frame(
                        stage,
                        destination_mac=binding.node_mac,
                        source_mac=binding.manager_mac,
                        mtu=1500,
                    )
                )
                invalid[14 + 2 + 32 + 24] = 0x02
                await ports.send(0, bytes(invalid))
                ack = decode_control_frame(
                    await ports.receive(PacketClass.CONTROL, port=0), mtu=1500
                )
                assert ack.status != 0
            await backend._control(
                ports, scenario, binding, ControlCommand.STAGE, 10, binding.context.pack()
            )
            await backend._control(ports, scenario, binding, ControlCommand.COMMIT, 11)
            running = None
            for number, rank in enumerate(order):
                source = next(item for item in binding.ranks if item.rank == rank)
                packet = DataPacket(
                    PacketClass.DATA,
                    scenario.config.key,
                    source.peer_endpoint,
                    source.local_endpoint,
                    source.local_endpoint,
                    rank + 1,
                    0,
                    (
                        NumberGroup(ConcreteFormat.FP32, (values[rank],) * 17),
                        NumberGroup(ConcreteFormat.FP32, (values[rank],) * 18),
                    ),
                    last=True,
                )
                frame = encode_data_frame(
                    packet,
                    destination_mac=binding.node_mac,
                    source_mac=source.peer_mac,
                    mtu=1500,
                    kulisch_bits=320,
                )
                if number == 0:
                    await ports.send(source.port, frame[:-5])
                    for _ in range(40):
                        await RisingEdge(dut.clk)
                    assert not commits, "rejected frame mutated the arithmetic state"
                await ports.send(source.port, frame)
                running = values[rank] if running is None else add32(running, values[rank])
                # Every element must be committed now, before the next rank is sent.
                # The existing multi-group reader consumes one byte per cycle;
                # allow its frame traversal plus validation and tile write-back.
                # This is an online-state test, not the separate line-rate gate.
                for _ in range(2 * len(frame)):
                    await RisingEdge(dut.clk)
                    await ReadOnly()
                    complete = True
                    for slot in range(3):
                        if slot not in commits:
                            complete = False
                            continue
                        bits, counts = commits[slot]
                        for lane in range(min(16, 35 - slot * 16)):
                            if (counts >> (lane * 4)) & 15 != number + 1:
                                complete = False
                            elif (bits >> (lane * 32)) & 0xFFFFFFFF != running:
                                raise AssertionError(
                                    "online FP32 state disagrees with independent oracle"
                                )
                    if complete:
                        break
                else:
                    raise AssertionError(
                        f"FP32 online commit timeout after rank {rank}: {commits}; "
                        f"fault={int(engine.m_fault.value)}"
                    )
                # Leave ReadOnly before the next driver writes its signals.
                await RisingEdge(dut.clk)
            destination = next(item for item in binding.ranks if item.rank == 1)
            raw = await ports.receive(PacketClass.RESULT, port=destination.port)
            result = decode_data_frame(raw, mtu=1500, kulisch_bits=320)
            assert result.first_element == 0 and result.last
            assert tuple(v for group in result.groups for v in group.values) == (running,) * 35
            assert running == (0 if case == 0 else 0x33800000)
            await backend._control(ports, scenario, binding, ControlCommand.RELEASE, 12)
        finally:
            monitor.cancel()
            ports.stop()
