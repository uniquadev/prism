"""End-to-end two-rank, two-port profile; independent numeric oracle."""

from __future__ import annotations

import json
import os
from pathlib import Path

import cocotb
from ccl.world import CocotbSingleBackend
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode, PrismCapacity
from prism_ccl.wire.data import PacketClass
from prism_ccl.world import PrismWorld

from tests.integration.test_prismworld_line_rate_target_cocotb import AxiRateProbe


def two_port_world():
    """Rank 0 and the manager behind a hub on port 0, rank 1 alone on port 1."""
    world = PrismWorld(manager="am")
    world.add_node("am", bytes.fromhex("020000000000"))
    world.add_node("hub", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_prism(
        "s", bytes.fromhex("020000000003"), capacity=PrismCapacity(2, 2, 2, 65536, True, False)
    )
    world.connect("am", 1, "hub", 1)
    world.connect("hub", 2, "s", 0)
    world.add_node("r0", bytes((2, 0, 0, 0, 0, 10)))
    world.add_node("r1", bytes((2, 0, 0, 0, 0, 11)))
    world.connect("r0", 1, "hub", 3)
    world.connect("r1", 1, "s", 1)
    nodes = [LogicalNode("s"), LogicalNode("r0", 0), LogicalNode("r1", 1)]
    edges = [
        LogicalEdge("r0", "s", 1, 10, ("r0", "hub", "s")),
        LogicalEdge("r1", "s", 1, 11, ("r1", "s")),
    ]
    return world, CollectiveTree("s", tuple(nodes), tuple(edges))


@cocotb.test()
async def two_ports_native_formats_exact_auto_and_rates(dut):
    formats = (ConcreteFormat.INT8, ConcreteFormat.FP16, ConcreteFormat.BF16, ConcreteFormat.FP32)
    outputs = (
        ResultWirePolicy.INT8,
        ResultWirePolicy.FP16,
        ResultWirePolicy.BF16,
        ResultWirePolicy.FP32,
        ResultWirePolicy.KULISCH,
        ResultWirePolicy.AUTO,
    )
    result_path = Path(
        os.environ.get(
            "PRISM_TWO_PORT_PROFILE_RESULTS",
            str(
                Path(__file__).resolve().parents[5]
                / "build/experiments/u280-two-port-profile-verification/rates.json"
            ),
        )
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    rows, misses = [], []
    sequence = 0
    for fmt in formats:
        # Integers in [-3,3] are representable in every tested native type.
        source = tuple(
            round_native(decode_native(x & 255, ConcreteFormat.INT8), fmt)
            for x in (-3, 1, 2, 0, 3, -1, -2, 0)
        )
        left = source * 512
        right = tuple(reversed(source)) * 512
        expected = tuple(
            combine_exact((decode_native(a, fmt), decode_native(b, fmt)))
            for a, b in zip(left, right, strict=True)
        )
        for output in outputs:
            world, tree = two_port_world()
            world.register_reduce(
                "profile",
                tree=tree,
                vectors={0: TypedVector(fmt, left), 1: TypedVector(fmt, right)},
                destination_rank=1,
                management_paths={"s": ("am", "hub", "s")},
                accumulator=AccumulatorPolicy.KULISCH_FIXED,
                partial_wire=PartialWirePolicy.AUTO,
                output_format=output,
                kulisch_bits=280,
                maximum_original_terms=2,
            )
            probe = AxiRateProbe(dut)
            monitor = cocotb.start_soon(probe.run())
            try:
                result = await world.run_async(
                    "profile",
                    backend=CocotbSingleBackend(
                        dut,
                        prism_name="s",
                        physical_ports=2,
                        start_clock=sequence == 0,
                        timeout_cycles=30000,
                    ),
                )
                assert result.released_context
                if output in (ResultWirePolicy.AUTO, ResultWirePolicy.KULISCH):
                    assert result.rank_values == {1: expected}
                else:
                    assert result.rank_bits == {
                        1: tuple(round_native(x, ConcreteFormat(output)) for x in expected)
                    }
                input_width = (
                    1 if fmt == ConcreteFormat.INT8 else 4 if fmt == ConcreteFormat.FP32 else 2
                )
                output_width = (
                    36
                    if output == ResultWirePolicy.KULISCH
                    else 4
                    if output == ResultWirePolicy.FP32
                    else 2
                    if output in (ResultWirePolicy.FP16, ResultWirePolicy.BF16)
                    else 1
                )
                # Each port carries the vector of one rank; the result leaves
                # on the port of its destination.
                data = [
                    probe.windows[("s", port, int(PacketClass.DATA))].numeric_gbps(
                        4096 * input_width
                    )
                    for port in range(2)
                ]
                outgoing = probe.windows[("m", 1, int(PacketClass.RESULT))]
                row = dict(
                    input=fmt.name,
                    output=output.name,
                    data_gbps_port0=data[0],
                    data_gbps_port1=data[1],
                    result_gbps=outgoing.numeric_gbps(4096 * output_width),
                    result_axi_gbps=outgoing.axi_gbps(),
                    result_cycles=outgoing.cycles,
                    input_stalls=list(probe.input_stalls),
                )
                rows.append(row)
                dut._log.info("U280_TWO_PORT_PROFILE %s", json.dumps(row))
                if min(data) < 100 or row["result_gbps"] < 100:
                    misses.append((fmt.name, output.name))
            finally:
                monitor.cancel()
                sequence += 1
                result_path.write_text(json.dumps(rows, indent=2))
    assert not misses, f"100 Gb/s numeric payload gate failed: {misses}"
