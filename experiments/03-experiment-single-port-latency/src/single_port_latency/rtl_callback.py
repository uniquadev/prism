"""Run eight-rank SINGLE operations and record accepted AXI beat milestones."""

from __future__ import annotations

import json
import os
import random
import struct
from pathlib import Path
from typing import Any

import cocotb
from ccl.world import CocotbSingleBackend
from prism_ccl.application.packing import group_cost
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode, PrismCapacity
from prism_ccl.wire.data import CONTROL_WORD_BYTES, DATA_HEADER_BYTES, PacketClass
from prism_ccl.world import PrismWorld
from prism_experiments.artifacts import write_json


def fp32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def one_port_world() -> tuple[PrismWorld, CollectiveTree]:
    world = PrismWorld(manager="am")
    world.add_node("am", bytes.fromhex("020000000000"))
    world.add_node("hub", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_prism(
        "s",
        bytes.fromhex("020000000003"),
        capacity=PrismCapacity(8, 8, 8, 65536, True, False),
    )
    world.connect("am", 1, "hub", 1)
    world.connect("hub", 2, "s", 0)
    nodes = [LogicalNode("s")]
    edges = []
    for rank in range(8):
        name = f"r{rank}"
        world.add_node(name, bytes((2, 0, 0, 0, 0, rank + 10)))
        world.connect(name, 1, "hub", rank + 3)
        nodes.append(LogicalNode(name, rank))
        edges.append(LogicalEdge(name, "s", 1, 10 + rank, (name, "hub", "s")))
    return world, CollectiveTree("s", tuple(nodes), tuple(edges))


def vectors_for_case(case: dict[str, Any], seed: int) -> dict[int, TypedVector]:
    fmt = ConcreteFormat[case["input_format"]]
    count = case["length"]
    generator = random.Random(seed)
    vectors = {}
    for rank in range(8):
        if case["workload"] == "sensitive":
            values = (1.0, 2**-24, -1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
            bits = tuple(fp32_bits(values[rank] if index % 2 == 0 else -values[rank])
                         for index in range(count))
        else:
            bits = tuple(
                round_native(
                    decode_native(
                        fp32_bits(float((rank + 1) * ((index % 7) - 3) + generator.randrange(2))),
                        ConcreteFormat.FP32,
                    ),
                    fmt,
                )
                for index in range(count)
            )
        vectors[rank] = TypedVector(fmt, bits)
    return vectors


def expected_values(
    vectors: dict[int, TypedVector], accumulator: AccumulatorPolicy
) -> tuple[Any, ...]:
    count = len(vectors[0].bits)
    output = []
    for index in range(count):
        terms = tuple(
            decode_native(vectors[rank].bits[index], vectors[rank].format)
            for rank in range(8)
        )
        if accumulator == AccumulatorPolicy.KULISCH_FIXED:
            output.append(combine_exact(terms))
        else:
            state = terms[0]
            for term in terms[1:]:
                bits = round_native(combine_exact((state, term)), ConcreteFormat.FP32)
                state = decode_native(bits, ConcreteFormat.FP32)
            output.append(state)
    return tuple(output)


@cocotb.test()
async def measure_one_port(dut: Any) -> None:
    run_dir = Path(os.environ["PRISM_EXPERIMENT_RUN"])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    samples = []
    for index, case in enumerate(manifest["cases"]):
        accumulator = AccumulatorPolicy[case["accumulator"]]
        exact = accumulator == AccumulatorPolicy.KULISCH_FIXED
        output_format = ResultWirePolicy.KULISCH if exact else ResultWirePolicy.FP32
        partial_wire = PartialWirePolicy.KULISCH if exact else PartialWirePolicy.FP32
        vectors = vectors_for_case(case, manifest["seed"])
        expected = expected_values(vectors, accumulator)
        if case["workload"] == "sensitive" and exact:
            rounded = expected_values(vectors, AccumulatorPolicy.FP32_ARRIVAL)
            if expected == rounded:
                raise AssertionError("sensitive vectors must expose FP32 rounding")
        world, tree = one_port_world()
        world.register_allreduce(
            f"latency-{index}",
            tree=tree,
            vectors=vectors,
            management_paths={"s": ("am", "hub", "s")},
            accumulator=accumulator,
            partial_wire=partial_wire,
            output_format=output_format,
            kulisch_bits=320,
        )
        result = await world.run_async(
            f"latency-{index}",
            backend=CocotbSingleBackend(
                dut,
                prism_name="s",
                physical_ports=1,
                preload_all_but_last=True,
                preload_settle_cycles=manifest["preload_settle_cycles"],
                output_stall_period=manifest["output_stall_period"],
                timeout_cycles=200_000,
                start_clock=index == 0,
            ),
        )
        if not result.released_context or result.rank_values is None:
            raise AssertionError("RESULT delivery or context release failed")
        if set(result.rank_values) != set(range(8)):
            raise AssertionError("all eight rank destinations must receive the result")
        for rank, values in result.rank_values.items():
            if values != expected:
                raise AssertionError(f"{case}: rank {rank} differs from the independent oracle")
        data_packets = sum(frame[15] == PacketClass.DATA for _, frame in result.sent_frames)
        result_packets = sum(frame[15] == PacketClass.RESULT for _, frame in result.frames)
        output_type = ConcreteFormat.KULISCH if exact else ConcreteFormat.FP32
        body_budget = manifest["mtu_bytes"] - CONTROL_WORD_BYTES - DATA_HEADER_BYTES
        packet_capacity = max(
            count
            for count in range(1, case["length"] + 1)
            if group_cost(output_type, count, 320) <= body_budget
        )
        expected_result_packets = 8 * ((case["length"] + packet_capacity - 1)
                                       // packet_capacity)
        if data_packets != 8 or result_packets != expected_result_packets:
            raise AssertionError("unexpected DATA or RESULT packet count")
        final_source_mac = world.network.nodes["r7"].mac
        final_frames = [
            frame
            for _, frame in result.sent_frames
            if frame[15] == PacketClass.DATA and frame[6:12] == final_source_mac
        ]
        if len(final_frames) != 1:
            raise AssertionError("the final rank must send exactly one DATA packet")
        final_packet_latency = result.final_packet_to_result_cycles
        first_beat_latency = result.final_contribution_latency_cycles
        ingress_cycles = result.final_contribution_ingress_cycles
        if (
            final_packet_latency is None
            or first_beat_latency is None
            or ingress_cycles is None
            or final_packet_latency <= 0
            or first_beat_latency != final_packet_latency + ingress_cycles - 1
        ):
            raise AssertionError("final DATA and first RESULT timestamps are inconsistent")
        expected_beats = (len(final_frames[0]) + 63) // 64
        if not expected_beats <= ingress_cycles <= expected_beats + result.stalled_input_beats[0]:
            raise AssertionError("final DATA ingress interval includes another rank or idle time")
        samples.append(
            {
                **case,
                "output_format": output_format.name,
                "partial_wire": partial_wire.name,
                "final_packet_to_result_cycles": final_packet_latency,
                "final_packet_to_result_ns_at_4ns": 4 * final_packet_latency,
                "final_first_beat_to_result_cycles": first_beat_latency,
                "final_ingress_cycles": ingress_cycles,
                "data_packets": data_packets,
                "result_packets": result_packets,
                "input_stalled_beats": result.stalled_input_beats[0],
                "output_stalled_beats": result.stalled_output_beats,
                "oracle_mismatches": 0,
            }
        )
        write_json(run_dir / "samples.json", samples)
