"""Cocotb callback: real DUT frames, exact independent SUM check, raw counters."""

from __future__ import annotations

import json
import os
import random
import struct
from collections import Counter
from pathlib import Path
from typing import Any

import cocotb
from ccl.examples import shared_port_world, single_world
from ccl.world import CocotbSingleBackend
from prism_ccl.application.reordering import ReorderPlan
from prism_ccl.domain.model import (
    FORMAT_BYTES,
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.wire.data import PacketClass, decode_data_frame
from prism_experiments.artifacts import write_json

from .workloads import one_wide_vectors


def fp32_bits(value: int) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def fp32_ulp_distance(left: int, right: int) -> int:
    def key(bits: int) -> int:
        return (~bits & 0xFFFFFFFF) if bits & 0x80000000 else bits | 0x80000000

    return abs(key(left) - key(right))


@cocotb.test()
async def measure_single(dut: Any) -> None:
    run_dir = Path(os.environ["PRISM_EXPERIMENT_RUN"])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    seed = manifest["seed"]
    count = manifest["elements_per_rank"]
    ranks = manifest.get("ranks", 2)
    input_format = ConcreteFormat[manifest["input_format"]]
    output_format = ResultWirePolicy[manifest["output_format"]]
    generator = random.Random(seed)
    if manifest.get("workload") == "one_wide":
        source_bits = one_wide_vectors(input_format, count)
    elif manifest.get("workload", "ordinary") == "half_ulp":
        signs = tuple(generator.randrange(2) for _ in range(count))
        source_bits = (
            tuple(0xBF800000 if sign else 0x3F800000 for sign in signs),
            tuple(0xB3800000 if sign else 0x33800000 for sign in signs),
        )
        if ranks == 3:
            source_bits += (tuple(0x3F800000 if sign else 0xBF800000 for sign in signs),)
    else:
        source_bits = tuple(
            tuple(
                round_native(
                    decode_native(fp32_bits(generator.randrange(-8, 9)), ConcreteFormat.FP32),
                    input_format,
                )
                for _ in range(count)
            )
            for _ in range(ranks)
        )
        if manifest.get("workload") == "sparse_exact":
            mixed = [list(bits) for bits in source_bits]
            mixed[0][0] = 0x3F800000
            mixed[1][0] = 0x33800000
            source_bits = tuple(tuple(bits) for bits in mixed)
    vectors = {rank: TypedVector(input_format, bits) for rank, bits in enumerate(source_bits)}
    exact_values = tuple(
        combine_exact(
            tuple(decode_native(vector.bits[index], vector.format) for vector in vectors.values())
        )
        for index in range(count)
    )
    expected = tuple(round_native(value, ConcreteFormat.FP32) for value in exact_values)

    def arrival_result(index: int) -> int:
        state = decode_native(vectors[0].bits[index], ConcreteFormat.FP32)
        for rank in range(1, len(vectors)):
            term = decode_native(vectors[rank].bits[index], ConcreteFormat.FP32)
            state = decode_native(
                round_native(combine_exact((state, term)), ConcreteFormat.FP32),
                ConcreteFormat.FP32,
            )
        return round_native(state, ConcreteFormat.FP32)

    arrival_expected = (
        tuple(arrival_result(index) for index in range(count))
        if input_format == ConcreteFormat.FP32
        else None
    )
    samples = []
    reorder_config = manifest["reorder"]
    reorder = ReorderPlan.data(
        reorder_config["probability"],
        window_packets=reorder_config["window_packets"],
        seed=reorder_config["seed"],
        edges=((f"r{rank}", "s") for rank in range(ranks)),
    )
    profiles = [
        (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH),
    ]
    if input_format == ConcreteFormat.FP32 and output_format in (
        ResultWirePolicy.FP32,
        ResultWirePolicy.AUTO,
    ):
        profiles.extend(
            (
                (AccumulatorPolicy.FP32_ARRIVAL, PartialWirePolicy.FP32),
            )
        )
    for profile_index, (accumulator, partial_wire) in enumerate(profiles):
        world, tree = shared_port_world() if ranks == 3 else single_world()
        settings = {
            "tree": tree,
            "vectors": vectors,
            "management_paths": {"s": ("am", "forward", "s")},
            "accumulator": accumulator,
            "partial_wire": partial_wire,
            "output_format": output_format,
        }
        if output_format in (ResultWirePolicy.KULISCH, ResultWirePolicy.AUTO):
            settings["kulisch_bits"] = 320
        expected_ranks = set(range(ranks))
        if manifest["collective"] == "reduce":
            world.register_reduce("measure", destination_rank=1, **settings)
            expected_ranks = {1}
        else:
            world.register_allreduce("measure", **settings)
        result = await world.run_async(
            "measure",
            backend=CocotbSingleBackend(
                dut,
                prism_name="s",
                timeout_cycles=200_000,
                output_stall_period=manifest.get("output_stall_period", 0),
                start_clock=profile_index == 0,
                capture_dir=(
                    run_dir / "captures" / accumulator.name.lower()
                    if manifest.get("capture_pcaps", False)
                    else None
                ),
                reorder=reorder,
                preload_first_rank=manifest.get("preload_first_rank", False),
                preload_settle_cycles=manifest.get("preload_settle_cycles", 64),
            ),
        )
        if (
            result.rank_values is None
            or set(result.rank_values) != expected_ranks
            or not result.released_context
        ):
            raise AssertionError(f"seed={seed}: RESULT destinations or resource release mismatched")
        if output_format in (ResultWirePolicy.KULISCH, ResultWirePolicy.AUTO):
            wanted_values = (
                tuple(decode_native(bits, ConcreteFormat.FP32) for bits in arrival_expected)
                if accumulator == AccumulatorPolicy.FP32_ARRIVAL
                and arrival_expected is not None
                else exact_values
            )
            for rank, actual in result.rank_values.items():
                if actual != wanted_values:
                    raise AssertionError(f"seed={seed} rank={rank}: RESULT value differs")
        else:
            assert result.rank_bits is not None
            wanted_vector = (
                arrival_expected
                if accumulator == AccumulatorPolicy.FP32_ARRIVAL
                else tuple(
                    round_native(value, ConcreteFormat(output_format)) for value in exact_values
                )
            )
            assert wanted_vector is not None
            for rank, actual in result.rank_bits.items():
                for index, (observed, wanted) in enumerate(zip(actual, wanted_vector, strict=True)):
                    if observed != wanted:
                        raise AssertionError(
                            f"seed={seed} policy={accumulator.name} rank={rank} index={index}: "
                            f"input={','.join(f'0x{bits[index]:x}' for bits in source_bits)} "
                            f"expected=0x{wanted:x} received=0x{observed:x}"
                        )

        observed_bits = tuple(
            round_native(value, ConcreteFormat.FP32)
            for value in next(iter(result.rank_values.values()))
        )
        exact_ulp_errors = tuple(
            fp32_ulp_distance(actual, reference)
            for actual, reference in zip(observed_bits, expected, strict=True)
        )
        absolute_errors = tuple(
            abs(
                decode_native(actual, ConcreteFormat.FP32).value
                - decode_native(reference, ConcreteFormat.FP32).value
            )
            for actual, reference in zip(observed_bits, expected, strict=True)
        )

        all_frames = (*result.sent_frames, *result.frames)
        packet_count: Counter[str] = Counter()
        frame_bytes: Counter[str] = Counter()
        group_count: Counter[str] = Counter()
        result_format_elements: Counter[str] = Counter()
        result_numeric_bits = 0
        for _port, frame in all_frames:
            packet_class = PacketClass(frame[15])
            packet_count[packet_class.name] += 1
            frame_bytes[packet_class.name] += len(frame)
            if packet_class in (PacketClass.DATA, PacketClass.RESULT):
                decoded = decode_data_frame(frame, mtu=1500, kulisch_bits=320)
                group_count[packet_class.name] += len(decoded.groups)
                if packet_class == PacketClass.RESULT:
                    for group in decoded.groups:
                        result_format_elements[group.format.name] += len(group.values)
                    result_numeric_bits += sum(
                        len(group.values)
                        * (
                            320
                            if group.format == ConcreteFormat.KULISCH
                            else 8 * FORMAT_BYTES[group.format]
                        )
                        for group in decoded.groups
                    )
        data_positions: dict[str, list[int]] = {}
        for _port, frame in result.sent_frames:
            if PacketClass(frame[15]) == PacketClass.DATA:
                source = frame[6:12].hex()
                packet = decode_data_frame(frame, mtu=1500, kulisch_bits=320)
                data_positions.setdefault(source, []).append(packet.first_element)
        reordered_packets = 0
        max_displacement = 0
        data_packets = 0
        for positions in data_positions.values():
            sorted_positions = sorted(positions)
            expected_index = {position: index for index, position in enumerate(sorted_positions)}
            data_packets += len(positions)
            reordered_packets += sum(
                position < max(positions[:index], default=-1)
                for index, position in enumerate(positions)
            )
            displacements = (
                abs(index - expected_index[position]) for index, position in enumerate(positions)
            )
            max_displacement = max(max_displacement, *displacements)
        samples.append(
            {
                "accumulator": accumulator.name,
                "partial_wire": partial_wire.name,
                "input_format": input_format.name,
                "output_format": output_format.name,
                "seed": seed,
                "traffic_order": manifest["traffic_order"],
                "reorder": reorder_config,
                "data_packets": data_packets,
                "data_reordered_packets": reordered_packets,
                "data_max_displacement_packets": max_displacement,
                "workload": manifest.get("workload", "ordinary"),
                "source_bits": source_bits,
                "expected_fp32_bits": expected,
                "arrival_expected_fp32_bits": arrival_expected,
                "result_fp32_bits": result.rank_bits
                if output_format == ResultWirePolicy.FP32
                else None,
                "precision_reference": "FP32-rounded exact sum",
                "precision_mismatched_elements": sum(error != 0 for error in exact_ulp_errors),
                "precision_max_ulp": max(exact_ulp_errors),
                "precision_mean_ulp": sum(exact_ulp_errors) / count,
                "precision_max_absolute_error": float(max(absolute_errors)),
                "precision_mean_absolute_error": float(sum(absolute_errors) / count),
                "lifecycle_cycles": result.cycles,
                "collective_cycles": result.timing.collective_cycles,
                "setup_cycles": result.timing.setup_cycles,
                "commit_to_data_gap_cycles": (
                    result.timing.data_first_cycle - result.timing.commit_ack_last_cycle - 1
                ),
                "data_to_result_cycles": result.data_to_result_cycles,
                "data_input_window_cycles": result.timing.data_window_cycles,
                "preload_first_rank": manifest.get("preload_first_rank", False),
                "final_contribution_latency_cycles": result.final_contribution_latency_cycles,
                "final_contribution_ingress_cycles": result.final_contribution_ingress_cycles,
                "result_output_window_cycles": result.timing.result_window_cycles,
                "collective_elements_per_second_at_4ns": (
                    count * 250_000_000 / result.timing.collective_cycles
                ),
                "collective_output_gbps_at_4ns": (
                    result_numeric_bits
                    / len(expected_ranks)
                    / (4 * result.timing.collective_cycles)
                ),
                "input_aggregate_gbps_at_4ns": (
                    ranks
                    * count
                    * 8
                    * FORMAT_BYTES[input_format]
                    / (4 * result.timing.data_window_cycles)
                ),
                "result_aggregate_gbps_at_4ns": (
                    result_numeric_bits / (4 * result.timing.result_window_cycles)
                ),
                "packet_count": dict(packet_count),
                "frame_bytes": dict(frame_bytes),
                "numbergroups": dict(group_count),
                "result_format_elements": dict(result_format_elements),
                "output_stalled_beats": result.stalled_output_beats,
                "input_stalled_beats_by_port": result.stalled_input_beats,
                "peak_state_bytes": None,
                "stall_cycles": None,
            }
        )
    write_json(run_dir / "samples.json", samples)
