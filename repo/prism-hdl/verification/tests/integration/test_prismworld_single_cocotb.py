"""The public PrismWorld example executes through DUT frames, not the model sum."""

from __future__ import annotations

import random
from fractions import Fraction
from typing import Any

import cocotb
from ccl.examples import reduce_example, shared_port_world, single_example, single_world
from ccl.world import (
    CocotbSingleBackend,
    CompiledFramePorts,
    compile_single,
    rank_data_frames,
)
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import ExactValue, combine_exact, decode_native, round_native
from prism_ccl.wire.control import ControlCommand, decode_control_frame
from prism_ccl.wire.data import DataPacket, PacketClass, decode_data_frame, encode_data_frame


@cocotb.test()
async def prismworld_example_runs_full_single_lifecycle(dut: Any) -> None:
    result = await single_example(dut)
    inputs = ((0x3F800000, 0x40000000), (0x40000000, 0x40400000))
    expected = tuple(
        round_native(
            combine_exact(
                tuple(decode_native(vector[index], ConcreteFormat.FP32) for vector in inputs)
            ),
            ConcreteFormat.FP32,
        )
        for index in range(2)
    )
    assert result.rank_bits == {0: expected, 1: expected}
    assert result.released_context
    assert result.cycles > 0
    assert 0 < result.data_to_result_cycles < result.cycles
    controls = [
        decode_control_frame(frame, mtu=1500)
        for _port, frame in result.frames
        if frame[15] == PacketClass.CONTROL
    ]
    assert [packet.command for packet in controls] == [
        ControlCommand.ACK,
        ControlCommand.ACK,
        ControlCommand.ACK,
    ]
    assert sum(frame[15] == PacketClass.DATA for _port, frame in result.frames) == 0
    assert sum(frame[15] == PacketClass.RESULT for _port, frame in result.frames) == 2
    assert sum(frame[15] == PacketClass.PROGRESS for _port, frame in result.frames) == 0


@cocotb.test()
async def inbound_arithmetic_error_reaches_the_result_rank(dut: Any) -> None:
    world, tree = single_world()
    world.register_reduce(
        "failed-exact-partial",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * 2),
            1: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * 2),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.AUTO,
    )
    scenario = world._scenarios["failed-exact-partial"]
    binding = compile_single(world.network, scenario, "s")
    backend = CocotbSingleBackend(dut, prism_name="s")
    ports = CompiledFramePorts(dut, timeout_cycles=6000)
    await ports.start(binding.node_mac)
    try:
        await backend._control(
            ports, scenario, binding, ControlCommand.STAGE, 10, binding.context.pack()
        )
        await backend._control(ports, scenario, binding, ControlCommand.COMMIT, 11)
        source = binding.ranks[0]
        error = DataPacket(
            PacketClass.DATA,
            scenario.config.key,
            source.peer_endpoint,
            source.local_endpoint,
            source.local_endpoint,
            1,
            0,
            (),
            last=True,
            accumulation_inexact=True,
        )
        await ports.send(
            source.port,
            encode_data_frame(
                error,
                destination_mac=binding.node_mac,
                source_mac=source.peer_mac,
                mtu=scenario.config.mtu,
                kulisch_bits=scenario.config.kulisch_bits,
            ),
        )
        destination = binding.ranks[1]
        frame = await ports.receive(PacketClass.RESULT, port=destination.port)
        result = decode_data_frame(
            frame, mtu=scenario.config.mtu, kulisch_bits=scenario.config.kulisch_bits
        )
        assert result.accumulation_inexact
        assert result.groups == ()
        assert result.operation == scenario.config.key
        assert result.source_endpoint == destination.local_endpoint
        assert result.destination_endpoint == destination.peer_endpoint
        await backend._control(ports, scenario, binding, ControlCommand.RELEASE, 12)
    finally:
        ports.stop()


@cocotb.test()
async def prismworld_reduce_routes_only_to_explicit_destination(dut: Any) -> None:
    result = await reduce_example(dut)
    inputs = (
        (ConcreteFormat.FP16, (0x3C00, 0x4000)),
        (ConcreteFormat.BF16, (0x4000, 0x4040)),
    )
    expected = tuple(
        round_native(
            combine_exact(tuple(decode_native(bits[index], fmt) for fmt, bits in inputs)),
            ConcreteFormat.FP32,
        )
        for index in range(2)
    )
    assert result.rank_bits == {1: expected}
    assert result.released_context
    assert sum(frame[15] == PacketClass.RESULT for _port, frame in result.frames) == 1


@cocotb.test()
async def full_vector_exact_result_uses_kulisch_wire(dut: Any) -> None:
    world, tree = single_world()
    elements = 4096
    world.register_reduce(
        "exact-result",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * elements),
            1: TypedVector(ConcreteFormat.FP32, (0x33800000,) * elements),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.KULISCH,
        kulisch_bits=320,
        mtu=1500,
    )
    result = await world.run_async(
        "exact-result",
        backend=CocotbSingleBackend(dut, prism_name="s", timeout_cycles=100_000),
    )
    value = ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24))
    assert result.rank_bits is None
    assert result.rank_values == {1: (value,) * elements}
    frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
    assert frames and all(len(frame) <= 1500 for frame in frames)
    numeric_gbps = elements * 320 / (result.timing.result_window_cycles * 4)
    dut._log.info("integrated Kulisch RESULT payload %.2f Gb/s", numeric_gbps)
    assert numeric_gbps >= 100


@cocotb.test()
async def auto_result_reassembles_mixed_lossless_groups_at_rank(dut: Any) -> None:
    world, tree = single_world()
    left = (
        0x3F800000,
        0x3F802000,
        0x49800000,
        0x3F800001,
        0x3F800000,
        0x7F800000,
        0x7F800000,
        0x80000000,
        0x00000001,
    )
    right = (
        0,
        0,
        0,
        0,
        0x33800000,
        0x3F800000,
        0xFF800000,
        0x80000000,
        0,
    )
    world.register_reduce(
        "auto-result",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, left),
            1: TypedVector(ConcreteFormat.FP32, right),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.AUTO,
        kulisch_bits=320,
        mtu=576,
    )
    result = await world.run_async(
        "auto-result",
        backend=CocotbSingleBackend(dut, prism_name="s", output_stall_period=5),
    )
    expected = tuple(
        combine_exact(
            (
                decode_native(left[index], ConcreteFormat.FP32),
                decode_native(right[index], ConcreteFormat.FP32),
            )
        )
        for index in range(len(left))
    )
    assert result.rank_bits is None
    assert result.rank_values == {1: expected}
    assert result.released_context
    frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
    groups = tuple(
        group
        for payload in frames
        for group in decode_data_frame(payload, mtu=576, kulisch_bits=320).groups
    )
    assert {group.format for group in groups} == {
        ConcreteFormat.INT8,
        ConcreteFormat.FP16,
        ConcreteFormat.BF16,
        ConcreteFormat.FP32,
        ConcreteFormat.KULISCH,
    }


@cocotb.test()
async def mixed_auto_result_sustains_axi_frame_rate(dut: Any) -> None:
    elements = 4096
    left = tuple(0x3F800001 if index % 2 == 0 else 0x3F800000 for index in range(elements))
    right = tuple(0 if index % 2 == 0 else 0x33800000 for index in range(elements))
    world, tree = single_world()
    world.register_reduce(
        "mixed-auto-result-rate",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, left),
            1: TypedVector(ConcreteFormat.FP32, right),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.AUTO,
        kulisch_bits=320,
        mtu=1500,
    )
    result = await world.run_async(
        "mixed-auto-result-rate",
        backend=CocotbSingleBackend(dut, prism_name="s", timeout_cycles=200_000),
    )
    exact_even = decode_native(0x3F800001, ConcreteFormat.FP32)
    exact_odd = combine_exact(
        (
            decode_native(0x3F800000, ConcreteFormat.FP32),
            decode_native(0x33800000, ConcreteFormat.FP32),
        )
    )
    assert result.rank_values == {1: (exact_even, exact_odd) * (elements // 2)}
    frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
    assert len(frames) > 1
    packets = [decode_data_frame(frame, mtu=1500, kulisch_bits=320) for frame in frames]
    next_element = 0
    numeric_bits = 0
    seen_formats: set[ConcreteFormat] = set()
    for packet in packets:
        assert packet.first_element == next_element
        next_element += packet.element_count
        for group in packet.groups:
            seen_formats.add(group.format)
            numeric_bits += len(group.values) * (
                320 if group.format == ConcreteFormat.KULISCH else 32
            )
    assert next_element == elements and packets[-1].last
    assert seen_formats == {ConcreteFormat.FP32, ConcreteFormat.KULISCH}
    cycles = result.timing.result_window_cycles
    frame_bits = sum(map(len, frames)) * 8
    numeric_gbps = numeric_bits / (cycles * 4)
    frame_gbps = frame_bits / (cycles * 4)
    numeric_ceiling = 128 * numeric_bits / frame_bits
    dut._log.info(
        "integrated mixed AUTO RESULT numeric %.2f Gb/s; AXI frame %.2f Gb/s; "
        "numeric wire ceiling %.2f Gb/s; %.2f M elements/s",
        numeric_gbps,
        frame_gbps,
        numeric_ceiling,
        elements * 250 / cycles,
    )
    assert frame_gbps >= 120
    assert numeric_gbps <= numeric_ceiling + 0.01


@cocotb.test()
async def full_vector_auto_result_sustains_fp32_payload_rate(dut: Any) -> None:
    world, tree = single_world()
    elements = 4096
    egress = dut.u_core.u_single.u_exact_result_egress
    counters = {
        name: 0
        for name in (
            "read",
            "read_stall",
            "tile",
            "tile_stall",
            "auto",
            "auto_stall",
            "segment",
            "segment_stall",
            "frame",
            "frame_stall",
        )
    }
    stamps: dict[str, int] = {}

    async def count_egress_handshakes() -> None:
        while True:
            await RisingEdge(dut.clk)
            if int(egress.m_store_read_valid.value) and int(egress.m_store_read_ready.value):
                counters["read"] += 1
                stamps.setdefault("first_read_ns", int(get_sim_time(unit="ns")))
            elif int(egress.m_store_read_valid.value):
                counters["read_stall"] += 1
            if int(egress.s_tile_valid.value) and int(egress.s_tile_ready.value):
                counters["tile"] += 1
            elif int(egress.s_tile_valid.value):
                counters["tile_stall"] += 1
            # A classified tile is always taken: its reader slot was reserved with the read.
            if int(egress.auto_valid.value):
                counters["auto"] += 1
            if int(egress.segment_valid.value) and int(egress.segment_ready.value):
                counters["segment"] += 1
            elif int(egress.segment_valid.value):
                counters["segment_stall"] += 1
            if int(egress.m_axis_tvalid.value) and int(egress.m_axis_tready.value):
                counters["frame"] += 1
                stamps["last_output_ns"] = int(get_sim_time(unit="ns"))
            elif int(egress.m_axis_tvalid.value):
                counters["frame_stall"] += 1

    monitor = cocotb.start_soon(count_egress_handshakes())
    world.register_reduce(
        "auto-fp32-result",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800001,) * elements),
            1: TypedVector(ConcreteFormat.FP32, (0,) * elements),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.AUTO,
        kulisch_bits=320,
        mtu=1500,
    )
    result = await world.run_async(
        "auto-fp32-result",
        backend=CocotbSingleBackend(dut, prism_name="s", timeout_cycles=100_000),
    )
    monitor.cancel()
    expected = decode_native(0x3F800001, ConcreteFormat.FP32)
    assert result.rank_values == {1: (expected,) * elements}
    frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
    packets = [decode_data_frame(frame, mtu=1500, kulisch_bits=320) for frame in frames]
    assert sum(packet.element_count for packet in packets) == elements
    assert all(
        group.format == ConcreteFormat.FP32 and all(value == 0x3F800001 for value in group.values)
        for packet in packets
        for group in packet.groups
    )
    assert all(counters[name] == elements // 128 for name in ("read", "tile", "auto", "segment"))
    assert counters["frame"] == sum((len(frame) + 63) // 64 for frame in frames)
    assert "first_read_ns" in stamps and "last_output_ns" in stamps
    path_cycles = (stamps["last_output_ns"] - stamps["first_read_ns"]) // 4 + 1
    path_gbps = elements * 32 / (path_cycles * 4)
    numeric_gbps = elements * 32 / (result.timing.result_window_cycles * 4)
    frame_gbps = sum(map(len, frames)) * 8 / (result.timing.result_window_cycles * 4)
    dut._log.info(
        "integrated AUTO RESULT FP32 read-to-last %.2f Gb/s; output burst numeric %.2f Gb/s; "
        "AXI frame %.2f Gb/s; %.2f M elements/s",
        path_gbps,
        numeric_gbps,
        frame_gbps,
        elements * 250 / result.timing.result_window_cycles,
    )
    dut._log.info("AUTO RESULT handshakes: %s", counters)
    # The bound is the sustained rate of the output, from its first to its
    # last beat. The time from the first read to the first beat is latency
    # and has its own limit, as in the tests below.
    assert numeric_gbps >= 100
    assert path_cycles - result.timing.result_window_cycles <= 96


@cocotb.test()
async def auto_result_uniform_formats_preserve_values_and_report_rates(dut: Any) -> None:
    elements = 4096
    shortfalls: list[str] = []
    cases = (
        ("int8", 0x3F800000, 0, ConcreteFormat.INT8, 8),
        ("fp16", 0x3FC00000, 0, ConcreteFormat.FP16, 16),
        ("bf16", 0x4E800000, 0, ConcreteFormat.BF16, 16),
        ("kulisch", 0x3F800000, 0x33800000, ConcreteFormat.KULISCH, 320),
    )
    for index, (name, left, right, wire_format, bits) in enumerate(cases):
        world, tree = single_world()
        egress = dut.u_core.u_single.u_exact_result_egress
        stamps: dict[str, int] = {}

        async def measure_result_path(egress: Any, stamps: dict[str, int]) -> None:
            while True:
                await RisingEdge(dut.clk)
                if int(egress.m_store_read_valid.value) and int(egress.m_store_read_ready.value):
                    stamps.setdefault("first_read_ns", int(get_sim_time(unit="ns")))
                if int(egress.m_axis_tvalid.value) and int(egress.m_axis_tready.value):
                    stamps.setdefault("first_output_ns", int(get_sim_time(unit="ns")))
                    stamps["last_output_ns"] = int(get_sim_time(unit="ns"))
                    stamps["output_beats"] = stamps.get("output_beats", 0) + 1

        monitor = cocotb.start_soon(measure_result_path(egress, stamps))
        world.register_reduce(
            f"auto-{name}-result",
            tree=tree,
            vectors={
                0: TypedVector(ConcreteFormat.FP32, (left,) * elements),
                1: TypedVector(ConcreteFormat.FP32, (right,) * elements),
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.AUTO,
            output_format=ResultWirePolicy.AUTO,
            kulisch_bits=320,
            mtu=1500,
        )
        result = await world.run_async(
            f"auto-{name}-result",
            backend=CocotbSingleBackend(
                dut, prism_name="s", timeout_cycles=100_000, start_clock=index == 0
            ),
        )
        monitor.cancel()
        expected = combine_exact(
            (decode_native(left, ConcreteFormat.FP32), decode_native(right, ConcreteFormat.FP32))
        )
        assert result.rank_values == {1: (expected,) * elements}
        frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
        packets = [decode_data_frame(frame, mtu=1500, kulisch_bits=320) for frame in frames]
        assert sum(packet.element_count for packet in packets) == elements
        assert all(len(packet.groups) == 1 for packet in packets)
        assert all(group.format == wire_format for packet in packets for group in packet.groups)
        assert "first_read_ns" in stamps and "last_output_ns" in stamps
        path_cycles = (stamps["last_output_ns"] - stamps["first_read_ns"]) // 4 + 1
        numeric_gbps = elements * bits / (path_cycles * 4)
        frame_gbps = sum(map(len, frames)) * 8 / (path_cycles * 4)
        output_burst_gbps = elements * bits / (result.timing.result_window_cycles * 4)
        dut._log.info(
            "integrated AUTO RESULT %s read-to-last numeric %.2f Gb/s; AXI frame %.2f Gb/s; "
            "output burst %.2f Gb/s; %.2f M elements/s; first-output +%d cycles, "
            "%d beats, %d frames",
            name,
            numeric_gbps,
            frame_gbps,
            output_burst_gbps,
            elements * 250 / path_cycles,
            (stamps["first_output_ns"] - stamps["first_read_ns"]) // 4,
            stamps["output_beats"],
            len(frames),
        )
        # The bound is the sustained output rate, from the first to the last
        # RESULT beat. The cycles from the first read to the first beat are
        # latency and have their own limit.
        if output_burst_gbps < 100:
            shortfalls.append(f"{name}={output_burst_gbps:.2f} Gb/s")
        assert (stamps["first_output_ns"] - stamps["first_read_ns"]) // 4 <= 96, name
    assert not shortfalls, "AUTO RESULT 100 Gb/s sustained output: " + ", ".join(shortfalls)


@cocotb.test()
async def rounded_policies_auto_encode_the_already_rounded_result(dut: Any) -> None:
    for index, policy in enumerate((AccumulatorPolicy.FP32_ARRIVAL,)):
        world, tree = shared_port_world()
        world.register_reduce(
            f"rounded-{policy.name.lower()}-auto",
            tree=tree,
            vectors={
                0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * 64),
                1: TypedVector(ConcreteFormat.FP32, (0x33800000,) * 64),
                2: TypedVector(ConcreteFormat.FP32, (0xBF800000,) * 64),
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=policy,
            partial_wire=PartialWirePolicy.FP32,
            output_format=ResultWirePolicy.AUTO,
        )
        result = await world.run_async(
            f"rounded-{policy.name.lower()}-auto",
            backend=CocotbSingleBackend(
                dut,
                prism_name="s",
                start_clock=index == 0,
                output_stall_period=5 if index else 0,
            ),
        )
        assert result.rank_values == {1: (decode_native(0, ConcreteFormat.FP32),) * 64}
        if index:
            assert result.stalled_output_beats > 0
        frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
        packets = [decode_data_frame(frame, mtu=1500, kulisch_bits=280) for frame in frames]
        assert sum(packet.element_count for packet in packets) == 64
        assert all(
            group.format == ConcreteFormat.INT8 and all(value == 0 for value in group.values)
            for packet in packets
            for group in packet.groups
        )


@cocotb.test()
async def rounded_policies_auto_result_preserves_full_fp32_vector(dut: Any) -> None:
    elements = 4096
    for index, policy in enumerate((AccumulatorPolicy.FP32_ARRIVAL,)):
        world, tree = shared_port_world()
        world.register_reduce(
            f"rounded-{policy.name.lower()}-auto-long",
            tree=tree,
            vectors={
                0: TypedVector(ConcreteFormat.FP32, (0x3F800001,) * elements),
                1: TypedVector(ConcreteFormat.FP32, (0,) * elements),
                2: TypedVector(ConcreteFormat.FP32, (0,) * elements),
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=policy,
            partial_wire=PartialWirePolicy.FP32,
            output_format=ResultWirePolicy.AUTO,
        )
        result = await world.run_async(
            f"rounded-{policy.name.lower()}-auto-long",
            backend=CocotbSingleBackend(
                dut, prism_name="s", timeout_cycles=200_000, start_clock=index == 0
            ),
        )
        assert result.rank_values == {
            1: (decode_native(0x3F800001, ConcreteFormat.FP32),) * elements
        }
        frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
        packets = [decode_data_frame(frame, mtu=1500, kulisch_bits=280) for frame in frames]
        assert sum(packet.element_count for packet in packets) == elements
        assert all(
            group.format == ConcreteFormat.FP32
            and all(value == 0x3F800001 for value in group.values)
            for packet in packets
            for group in packet.groups
        )
        numeric_gbps = elements * 32 / (result.timing.result_window_cycles * 4)
        dut._log.info("%s AUTO RESULT FP32 output burst %.2f Gb/s", policy.name, numeric_gbps)
        assert numeric_gbps >= 100


@cocotb.test()
async def rounded_policies_narrow_auto_result_sustain_numeric_rate(dut: Any) -> None:
    elements = 4096
    shortfalls: list[str] = []
    cases = (
        ("int8", 0x3F800000, ConcreteFormat.INT8, 8),
        ("fp16", 0x3F000000, ConcreteFormat.FP16, 16),
        ("bf16", 0x4E800000, ConcreteFormat.BF16, 16),
    )
    run = 0
    for policy in (AccumulatorPolicy.FP32_ARRIVAL,):
        for name, value, wire_format, bits in cases:
            world, tree = shared_port_world()
            egress = dut.u_core.u_single.u_exact_result_egress
            arrival = dut.u_core.u_single.u_ingress.gen_arrival_round.u_arrival
            ingress = dut.u_core.u_single.u_ingress
            rounded_ingress = ingress.gen_arrival_round
            stamps: dict[str, int] = {}
            arrivals: list[list[int]] = [[0] * 16 for _ in range(256)]
            completed: dict[int, int] = {}

            async def measure_result_path(
                stamps: dict[str, int],
                egress: Any,
                arrival: Any,
                ingress: Any,
                rounded_ingress: Any,
                arrivals: list[list[int]],
                completed: dict[int, int],
            ) -> None:
                while True:
                    await RisingEdge(dut.clk)
                    accepted = int(rounded_ingress.arrival_valid.value) & int(
                        ingress.dual_rounded_ready.value
                    )
                    if accepted:
                        stamps.setdefault("first_input_ns", int(get_sim_time(unit="ns")))
                        stamps["last_input_ns"] = int(get_sim_time(unit="ns"))
                        for port in range(2):
                            if accepted & (1 << port):
                                slot = int(ingress.tile_first[port].value) // 16
                                keep = int(ingress.tile_keep[port].value) & 0xFFFF
                                for lane in range(16):
                                    if keep & (1 << lane):
                                        arrivals[slot][lane] += 1
                                if slot not in completed and min(arrivals[slot]) == 3:
                                    completed[slot] = int(get_sim_time(unit="ns"))
                    if int(egress.m_store_read_valid.value) and int(
                        egress.m_store_read_ready.value
                    ):
                        stamps.setdefault("first_read_ns", int(get_sim_time(unit="ns")))
                    if int(arrival.s_valid.value) & int(arrival.s_ready.value):
                        stamps.setdefault("first_update_input_ns", int(get_sim_time(unit="ns")))
                    if int(arrival.m_valid.value) and int(arrival.m_ready.value):
                        stamps.setdefault("first_complete_output_ns", int(get_sim_time(unit="ns")))
                    if int(egress.m_axis_tvalid.value) and int(egress.m_axis_tready.value):
                        stamps.setdefault("first_output_ns", int(get_sim_time(unit="ns")))
                        stamps["last_output_ns"] = int(get_sim_time(unit="ns"))

            monitor = cocotb.start_soon(
                measure_result_path(
                    stamps, egress, arrival, ingress, rounded_ingress, arrivals, completed
                )
            )

            world.register_reduce(
                f"rounded-{policy.name.lower()}-{name}-rate",
                tree=tree,
                vectors={
                    0: TypedVector(ConcreteFormat.FP32, (value,) * elements),
                    1: TypedVector(ConcreteFormat.FP32, (value,) * elements),
                    2: TypedVector(ConcreteFormat.FP32, (value,) * elements),
                },
                destination_rank=1,
                management_paths={"s": ("am", "forward", "s")},
                accumulator=policy,
                partial_wire=PartialWirePolicy.FP32,
                output_format=ResultWirePolicy.AUTO,
                mtu=1500,
            )
            result = await world.run_async(
                f"rounded-{policy.name.lower()}-{name}-rate",
                backend=CocotbSingleBackend(
                    dut, prism_name="s", timeout_cycles=200_000, start_clock=run == 0
                ),
            )
            run += 1
            monitor.cancel()
            input_value = decode_native(value, ConcreteFormat.FP32)
            expected_bits = round_native(
                combine_exact((input_value, input_value, input_value)), ConcreteFormat.FP32
            )
            assert result.rank_values == {
                1: (decode_native(expected_bits, ConcreteFormat.FP32),) * elements
            }
            frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
            packets = [decode_data_frame(frame, mtu=1500, kulisch_bits=280) for frame in frames]
            assert sum(packet.element_count for packet in packets) == elements
            assert all(group.format == wire_format for packet in packets for group in packet.groups)
            assert "first_read_ns" in stamps and "last_output_ns" in stamps
            assert "first_input_ns" in stamps and "last_input_ns" in stamps
            assert len(completed) == 256
            path_cycles = (stamps["last_output_ns"] - stamps["first_read_ns"]) // 4 + 1
            numeric_gbps = elements * bits / (path_cycles * 4)
            frame_gbps = sum(map(len, frames)) * 8 / (path_cycles * 4)
            dut._log.info(
                "%s AUTO RESULT %s read-to-last numeric %.2f Gb/s; AXI frame %.2f "
                "Gb/s; output burst %.2f Gb/s; %.2f M elements/s; "
                "read/update-in/complete-out/first-out/last-out cycles=%s/%s/%s/%s/%s; "
                "input start/end relative to read=%s/%s; "
                "complete first/last relative to read=%s/%s",
                policy.name,
                name,
                numeric_gbps,
                frame_gbps,
                elements * bits / (result.timing.result_window_cycles * 4),
                elements * 250 / path_cycles,
                *(
                    (stamps[key] - stamps["first_read_ns"]) // 4
                    for key in (
                        "first_read_ns",
                        "first_update_input_ns",
                        "first_complete_output_ns",
                        "first_output_ns",
                        "last_output_ns",
                    )
                ),
                (stamps["first_input_ns"] - stamps["first_read_ns"]) // 4,
                (stamps["last_input_ns"] - stamps["first_read_ns"]) // 4,
                (min(completed.values()) - stamps["first_read_ns"]) // 4,
                (max(completed.values()) - stamps["first_read_ns"]) // 4,
            )
            output_burst_gbps = elements * bits / (result.timing.result_window_cycles * 4)
            if output_burst_gbps < 100:
                shortfalls.append(f"{policy.name}/{name}={output_burst_gbps:.2f} Gb/s")
            assert (stamps["first_output_ns"] - stamps["first_read_ns"]) // 4 <= 96, name
    assert not shortfalls, "rounded AUTO RESULT 100 Gb/s sustained output: " + ", ".join(shortfalls)


@cocotb.test()
async def configured_kulisch_width_is_preserved_on_result(dut: Any) -> None:
    expected = ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24))
    cases = (
        (280, ResultWirePolicy.KULISCH),
        (280, ResultWirePolicy.AUTO),
        (384, ResultWirePolicy.KULISCH),
        (384, ResultWirePolicy.AUTO),
        (4096, ResultWirePolicy.KULISCH),
        (4096, ResultWirePolicy.AUTO),
    )
    for run, (wire_bits, output_format) in enumerate(cases):
        world, tree = single_world()
        world.register_reduce(
            "narrow-exact",
            tree=tree,
            vectors={
                0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * 16),
                1: TypedVector(ConcreteFormat.FP32, (0x33800000,) * 16),
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.AUTO,
            output_format=output_format,
            kulisch_bits=wire_bits,
            mtu=576,
        )
        result = await world.run_async(
            "narrow-exact",
            backend=CocotbSingleBackend(dut, prism_name="s", start_clock=run == 0),
        )
        assert result.rank_values == {1: (expected,) * 16}
        frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
        packets = [decode_data_frame(frame, mtu=576, kulisch_bits=wire_bits) for frame in frames]
        assert all(
            group.format == ConcreteFormat.KULISCH for packet in packets for group in packet.groups
        )
        assert all(
            len(value) == 1 + (wire_bits + 7) // 8
            for packet in packets
            for group in packet.groups
            for value in group.values
        )
        if wire_bits > 320:
            assert all(
                value[41:] == bytes((wire_bits + 7) // 8 - 40)
                for packet in packets
                for group in packet.groups
                for value in group.values
            )


@cocotb.test()
async def wide_auto_result_sign_extends_negative_exact_values(dut: Any) -> None:
    world, tree = single_world()
    width = 4096
    world.register_reduce(
        "negative-wide-auto",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0xBF800000,) * 16),
            1: TypedVector(ConcreteFormat.FP32, (0xB3800000,) * 16),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.AUTO,
        kulisch_bits=width,
        mtu=576,
    )
    result = await world.run_async(
        "negative-wide-auto", backend=CocotbSingleBackend(dut, prism_name="s")
    )
    exact = combine_exact(
        (
            decode_native(0xBF800000, ConcreteFormat.FP32),
            decode_native(0xB3800000, ConcreteFormat.FP32),
        )
    )
    assert result.rank_values == {1: (exact,) * 16}
    frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
    packets = [decode_data_frame(frame, mtu=576, kulisch_bits=width) for frame in frames]
    values = [value for packet in packets for group in packet.groups for value in group.values]
    assert len(values) == 16
    assert all(len(value) == 513 and value[41:] == bytes((0xFF,)) * 472 for value in values)


@cocotb.test()
async def widest_exact_results_sustain_numeric_rate_at_minimum_mtu(dut: Any) -> None:
    elements = 4096
    width = 4096
    mtu = 576
    expected = combine_exact(
        (
            decode_native(0x3F800000, ConcreteFormat.FP32),
            decode_native(0x33800000, ConcreteFormat.FP32),
        )
    )
    for run, output_format in enumerate((ResultWirePolicy.AUTO, ResultWirePolicy.KULISCH)):
        world, tree = single_world()
        name = f"widest-{output_format.name.lower()}-rate"
        world.register_reduce(
            name,
            tree=tree,
            vectors={
                0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * elements),
                1: TypedVector(ConcreteFormat.FP32, (0x33800000,) * elements),
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.AUTO,
            output_format=output_format,
            kulisch_bits=width,
            mtu=mtu,
        )
        result = await world.run_async(
            name,
            backend=CocotbSingleBackend(
                dut, prism_name="s", timeout_cycles=200_000, start_clock=run == 0
            ),
        )
        assert result.rank_values == {1: (expected,) * elements}
        frames = [frame for _port, frame in result.frames if frame[15] == PacketClass.RESULT]
        assert len(frames) == elements
        assert all(len(frame) == mtu for frame in frames)
        packets = [decode_data_frame(frame, mtu=mtu, kulisch_bits=width) for frame in frames]
        assert all(
            packet.first_element == index
            and packet.element_count == 1
            and len(packet.groups) == 1
            and packet.groups[0].format == ConcreteFormat.KULISCH
            for index, packet in enumerate(packets)
        )
        assert packets[-1].last and not any(packet.last for packet in packets[:-1])

        cycles = result.timing.result_window_cycles
        numeric_bits = elements * width
        frame_bits = sum(len(frame) * 8 for frame in frames)
        numeric_gbps = numeric_bits / (cycles * 4)
        frame_gbps = frame_bits / (cycles * 4)
        numeric_ceiling = 128 * numeric_bits / frame_bits
        dut._log.info(
            "W=4096 %s RESULT at MTU 576: numeric %.2f Gb/s, AXI frame %.2f Gb/s, "
            "numeric wire ceiling %.2f Gb/s, %.2f M elements/s over %d cycles",
            output_format.name,
            numeric_gbps,
            frame_gbps,
            numeric_ceiling,
            elements * 250 / cycles,
            cycles,
        )
        assert numeric_ceiling >= 100
        assert numeric_gbps >= 100


@cocotb.test()
async def full_mtu_int8_group_and_next_chunk_are_admitted(dut: Any) -> None:
    for index, (mtu, maximum) in enumerate(((576, 528), (1500, 1452))):
        world, tree = single_world()
        elements = maximum + 1
        world.register_reduce(
            "int8-boundary",
            tree=tree,
            vectors={rank: TypedVector(ConcreteFormat.INT8, (1,) * elements) for rank in (0, 1)},
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            output_format=ConcreteFormat.FP32,
            mtu=mtu,
        )
        result = await world.run_async(
            "int8-boundary",
            backend=CocotbSingleBackend(
                dut, prism_name="s", timeout_cycles=200_000, start_clock=index == 0
            ),
        )
        data_counts = [
            decode_data_frame(frame, mtu=mtu, kulisch_bits=280).element_count
            for _port, frame in result.sent_frames
            if frame[15] == PacketClass.DATA
        ]
        assert sorted(data_counts) == [1, 1, maximum, maximum]
        assert result.rank_bits == {1: (0x40000000,) * elements}
        assert result.released_context


@cocotb.test()
async def fixed_kulisch_single_uses_the_same_in_band_lifecycle(dut: Any) -> None:
    world, tree = single_world()
    vectors = {
        0: TypedVector(ConcreteFormat.FP16, (0x3C00, 0xBC00)),
        1: TypedVector(ConcreteFormat.FP16, (0x0001, 0x0001)),
    }
    world.register_allreduce(
        "fixed",
        tree=tree,
        vectors=vectors,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.KULISCH,
    )
    result = await world.run_async("fixed", backend=CocotbSingleBackend(dut, prism_name="s"))
    expected = tuple(
        round_native(
            combine_exact(
                tuple(
                    decode_native(vector.bits[index], vector.format) for vector in vectors.values()
                )
            ),
            ConcreteFormat.FP32,
        )
        for index in range(2)
    )
    assert result.rank_bits == {0: expected, 1: expected}
    assert result.released_context


@cocotb.test()
async def fp32_arrival_single_is_explicitly_negotiated(dut: Any) -> None:
    world, tree = single_world()
    vectors = {
        0: TypedVector(ConcreteFormat.FP32, (0x3F800000, 0x40000000)),
        1: TypedVector(ConcreteFormat.FP32, (0x33800000, 0x40400000)),
    }
    world.register_allreduce(
        "arrival",
        tree=tree,
        vectors=vectors,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.FP32_ARRIVAL,
        partial_wire=PartialWirePolicy.FP32,
    )
    result = await world.run_async("arrival", backend=CocotbSingleBackend(dut, prism_name="s"))
    assert result.rank_bits == {0: (0x3F800000, 0x40A00000), 1: (0x3F800000, 0x40A00000)}
    assert result.released_context


@cocotb.test()
async def shared_port_three_ranks_expose_the_fp32_rounding_difference(dut: Any) -> None:
    vectors = {
        0: TypedVector(ConcreteFormat.FP32, (0x3F800000,)),
        1: TypedVector(ConcreteFormat.FP32, (0x33800000,)),
        2: TypedVector(ConcreteFormat.FP32, (0xBF800000,)),
    }
    for index, (accumulator, partial_wire, expected) in enumerate(
        (
            (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO, 0x33800000),
            (AccumulatorPolicy.FP32_ARRIVAL, PartialWirePolicy.FP32, 0x00000000),
        )
    ):
        world, tree = shared_port_world()
        world.register_allreduce(
            "shared",
            tree=tree,
            vectors=vectors,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=accumulator,
            partial_wire=partial_wire,
        )
        result = await world.run_async(
            "shared", backend=CocotbSingleBackend(dut, prism_name="s", start_clock=index == 0)
        )
        assert result.rank_bits == {rank: (expected,) for rank in vectors}
        assert result.released_context


@cocotb.test()
async def seeded_mixed_rank_formats_match_exact_oracle(dut: Any) -> None:
    seed = 20924
    generator = random.Random(seed)
    values = {
        0: TypedVector(
            ConcreteFormat.FP16,
            tuple(
                (generator.randrange(2) << 15)
                | (generator.randrange(1, 31) << 10)
                | generator.randrange(1 << 10)
                for _ in range(64)
            ),
        ),
        1: TypedVector(
            ConcreteFormat.BF16,
            tuple(
                (generator.randrange(2) << 15)
                | (generator.randrange(1, 255) << 7)
                | generator.randrange(1 << 7)
                for _ in range(64)
            ),
        ),
    }
    world, tree = single_world()
    world.register_allreduce(
        "seeded",
        tree=tree,
        vectors=values,
        management_paths={"s": ("am", "forward", "s")},
    )
    result = await world.run_async(
        "seeded", backend=CocotbSingleBackend(dut, prism_name="s", output_stall_period=5)
    )
    expected = tuple(
        round_native(
            combine_exact(
                tuple(
                    decode_native(vector.bits[index], vector.format) for vector in values.values()
                )
            ),
            ConcreteFormat.FP32,
        )
        for index in range(64)
    )
    for rank in (0, 1):
        assert result.rank_bits[rank] == expected, f"seed={seed} rank={rank}"
    assert result.stalled_output_beats > 0
    assert result.released_context


@cocotb.test()
async def long_dual_port_exact_result_survives_stalls_and_release(dut: Any) -> None:
    for generation, elements in enumerate((4096, 256)):
        world, tree = shared_port_world()
        vectors = {
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * elements),
            1: TypedVector(ConcreteFormat.FP32, (0x33800000,) * elements),
            2: TypedVector(ConcreteFormat.FP32, (0xBF800000,) * elements),
        }
        world.register_reduce(
            "dual-port",
            tree=tree,
            vectors=vectors,
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.AUTO,
            output_format=ConcreteFormat.FP32,
        )
        result = await world.run_async(
            "dual-port",
            backend=CocotbSingleBackend(
                dut,
                prism_name="s",
                start_clock=generation == 0,
                timeout_cycles=200_000,
                output_stall_period=7,
            ),
        )
        assert result.rank_bits == {1: (0x33800000,) * elements}
        assert result.stalled_output_beats > 0
        assert result.released_context


class ScenarioOf:
    """A backend that hands back what it was asked to run."""

    async def run(self, network: Any, scenario: Any) -> tuple[Any, Any]:
        return network, scenario


@cocotb.test()
async def operation_after_an_abort_during_data_starts_from_nothing(dut: Any) -> None:
    length = 4096
    management = {"s": ("am", "forward", "s")}
    vectors = {
        0: TypedVector(ConcreteFormat.FP32, tuple(0x3F800000 + index for index in range(length))),
        1: TypedVector(ConcreteFormat.FP32, (0x40000000,) * length),
    }
    expected = tuple(
        round_native(
            combine_exact(
                tuple(
                    decode_native(vector.bits[index], vector.format) for vector in vectors.values()
                )
            ),
            ConcreteFormat.FP32,
        )
        for index in range(length)
    )
    # The abort reaches the node this many cycles after the rank on the other
    # port has begun to send, so tiles of the aborted operation are on their
    # way when it takes effect.
    for run, delay in enumerate((24, 25, 26, 27, 61, 150)):
        world, tree = single_world()
        left_behind = TypedVector(ConcreteFormat.FP32, (0x41200000,) * length)
        world.register_allreduce(
            "aborted",
            tree=tree,
            vectors={0: left_behind, 1: left_behind},
            management_paths=management,
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.KULISCH,
        )
        world.register_allreduce(
            "next",
            tree=tree,
            vectors=vectors,
            management_paths=management,
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.KULISCH,
        )
        network, aborted = await world.run_async("aborted", backend=ScenarioOf())
        backend = CocotbSingleBackend(dut, prism_name="s", start_clock=run == 0)

        async def abort_during_data(
            ports: CompiledFramePorts,
            network: Any = network,
            aborted: Any = aborted,
            backend: CocotbSingleBackend = backend,
            delay: int = delay,
        ) -> None:
            binding = compile_single(network, aborted, "s")
            await backend._control(
                ports, aborted, binding, ControlCommand.STAGE, 10, binding.context.pack()
            )
            await backend._control(ports, aborted, binding, ControlCommand.COMMIT, 11)
            sender = next(rank for rank in binding.ranks if rank.port == 1)
            frames, _packets = rank_data_frames(aborted, binding, sender)
            sending = cocotb.start_soon(ports.send_many(sender.port, frames))
            for _ in range(delay):
                await RisingEdge(dut.clk)
            await backend._control(ports, aborted, binding, ControlCommand.ABORT, 13)
            await sending

        backend.prelude = abort_during_data
        result = await world.run_async("next", backend=backend)
        assert result.rank_bits == {0: expected, 1: expected}, delay
        assert result.released_context


@cocotb.test()
async def operation_after_an_abort_during_result_starts_from_nothing(dut: Any) -> None:
    length = 4096
    management = {"s": ("am", "forward", "s")}
    vectors = {
        0: TypedVector(ConcreteFormat.FP32, tuple(0x3F800000 + index for index in range(length))),
        1: TypedVector(ConcreteFormat.FP32, (0x40000000,) * length),
    }
    exact = tuple(
        combine_exact(
            tuple(decode_native(vector.bits[index], vector.format) for vector in vectors.values())
        )
        for index in range(length)
    )
    run = 0
    # The sums of the aborted operation need the exact format on an AUTO
    # result, so its RESULT is long: about a hundred frames per rank.
    cases = (
        (ResultWirePolicy.FP32, (20, 70, 71, 140, 400)),
        (ResultWirePolicy.AUTO, (70, 115, 160, 250, 341, 432, 523, 614, 1500)),
    )
    for output, delays in cases:
        # The abort comes this many cycles after the last DATA frame of the
        # aborted operation: while its results are read and rounded, and
        # while its RESULT frames are built and leave.
        for delay in delays:
            world, tree = single_world()
            left_behind = TypedVector(ConcreteFormat.FP32, (0x3F800000,) * length)
            behind_too = TypedVector(ConcreteFormat.FP32, (0x32000000,) * length)
            settings: dict[str, Any] = dict(
                tree=tree,
                management_paths=management,
                accumulator=AccumulatorPolicy.KULISCH_FIXED,
                partial_wire=PartialWirePolicy.KULISCH,
                output_format=output,
            )
            world.register_allreduce("aborted", vectors={0: left_behind, 1: behind_too}, **settings)
            world.register_allreduce("next", vectors=vectors, **settings)
            network, aborted = await world.run_async("aborted", backend=ScenarioOf())
            backend = CocotbSingleBackend(dut, prism_name="s", start_clock=run == 0)
            run += 1

            async def abort_during_result(
                ports: CompiledFramePorts,
                network: Any = network,
                aborted: Any = aborted,
                backend: CocotbSingleBackend = backend,
                delay: int = delay,
            ) -> None:
                binding = compile_single(network, aborted, "s")
                await backend._control(
                    ports, aborted, binding, ControlCommand.STAGE, 10, binding.context.pack()
                )
                await backend._control(ports, aborted, binding, ControlCommand.COMMIT, 11)
                senders = [
                    cocotb.start_soon(
                        ports.send_many(rank.port, rank_data_frames(aborted, binding, rank)[0])
                    )
                    for rank in binding.ranks
                ]
                for sender in senders:
                    await sender
                for _ in range(delay):
                    await RisingEdge(dut.clk)
                await backend._control(ports, aborted, binding, ControlCommand.ABORT, 13)
                answered = ports.cycles
                for _ in range(200):
                    await RisingEdge(dut.clk)
                # The RESULT frame that was leaving is sent to its end; no
                # frame of the aborted operation begins after the answer.
                late = [
                    seen.first_cycle
                    for seen in ports.observations
                    if seen.direction == "tx"
                    and seen.frame[15] == PacketClass.RESULT
                    and seen.first_cycle > answered
                ]
                assert not late, (delay, answered, late)

            backend.prelude = abort_during_result
            result = await world.run_async("next", backend=backend)
            if output == ResultWirePolicy.AUTO:
                assert result.rank_values == {0: exact, 1: exact}, delay
            else:
                rounded = tuple(round_native(value, ConcreteFormat.FP32) for value in exact)
                assert result.rank_bits == {0: rounded, 1: rounded}, delay
            assert result.released_context


@cocotb.test()
async def operation_started_while_the_aborted_rank_still_sends_is_complete(dut: Any) -> None:
    length = 4096
    management = {"s": ("am", "forward", "s")}
    vectors = {
        0: TypedVector(ConcreteFormat.FP32, tuple(0x3F800000 + index for index in range(length))),
        1: TypedVector(ConcreteFormat.FP32, (0x40000000,) * length),
    }
    expected = tuple(
        round_native(
            combine_exact(
                tuple(
                    decode_native(vector.bits[index], vector.format) for vector in vectors.values()
                )
            ),
            ConcreteFormat.FP32,
        )
        for index in range(length)
    )
    world, tree = single_world()
    left_behind = TypedVector(ConcreteFormat.FP32, (0x41200000,) * length)
    settings: dict[str, Any] = dict(
        tree=tree,
        management_paths=management,
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.KULISCH,
    )
    world.register_allreduce("aborted", vectors={0: left_behind, 1: left_behind}, **settings)
    world.register_allreduce("next", vectors=vectors, **settings)
    network, aborted = await world.run_async("aborted", backend=ScenarioOf())
    backend = CocotbSingleBackend(dut, prism_name="s", timeout_cycles=12000)

    async def abort_and_keep_sending(ports: CompiledFramePorts) -> None:
        binding = compile_single(network, aborted, "s")
        await backend._control(
            ports, aborted, binding, ControlCommand.STAGE, 10, binding.context.pack()
        )
        await backend._control(ports, aborted, binding, ControlCommand.COMMIT, 11)
        sender = next(rank for rank in binding.ranks if rank.port == 1)
        frames, _packets = rank_data_frames(aborted, binding, sender)
        # The rank on the other port sends its vector five times over, without
        # a gap, long past the abort and into the next operation.
        send_many = ports.send_many
        still_sending = cocotb.start_soon(send_many(sender.port, frames * 5))
        for _ in range(40):
            await RisingEdge(dut.clk)
        await backend._control(ports, aborted, binding, ControlCommand.ABORT, 13)

        async def after_the_aborted_rank(port: int, later: Any) -> None:
            if port == sender.port and not still_sending.done():
                await still_sending
            await send_many(port, later)

        # The next operation begins at once; only its own rank on that port
        # has to wait for the wire.
        ports.send_many = after_the_aborted_rank  # type: ignore[method-assign]

    backend.prelude = abort_and_keep_sending
    result = await world.run_async("next", backend=backend)
    assert result.rank_bits == {0: expected, 1: expected}
    assert result.released_context
