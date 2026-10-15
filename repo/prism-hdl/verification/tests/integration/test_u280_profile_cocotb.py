"""End-to-end two-rank, one-port profile; independent numeric oracle."""

from __future__ import annotations

import json
import os
from pathlib import Path

import cocotb
from ccl.world import CocotbSingleBackend, compile_single, rank_data_frames
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode, PrismCapacity
from prism_ccl.wire.control import ControlCommand
from prism_ccl.wire.data import PacketClass
from prism_ccl.world import PrismWorld

from tests.integration.test_prismworld_line_rate_target_cocotb import AxiRateProbe


def one_port_world():
    world = PrismWorld(manager="am")
    world.add_node("am", bytes.fromhex("020000000000"))
    world.add_node("hub", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_prism(
        "s", bytes.fromhex("020000000003"), capacity=PrismCapacity(2, 2, 2, 65536, True, False)
    )
    world.connect("am", 1, "hub", 1)
    world.connect("hub", 2, "s", 0)
    nodes, edges = [LogicalNode("s")], []
    for rank in range(2):
        name = f"r{rank}"
        world.add_node(name, bytes((2, 0, 0, 0, 0, rank + 10)))
        world.connect(name, 1, "hub", rank + 3)
        nodes.append(LogicalNode(name, rank))
        edges.append(LogicalEdge(name, "s", 1, 10 + rank, (name, "hub", "s")))
    return world, CollectiveTree("s", tuple(nodes), tuple(edges))


@cocotb.test()
async def profile_native_formats_exact_auto_and_rates(dut):
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
            "PRISM_PROFILE_RESULTS",
            str(
                Path(__file__).resolve().parents[5]
                / "build/experiments/u280-profile-verification/rates.json"
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
            world, tree = one_port_world()
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
                        physical_ports=1,
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
                incoming = probe.windows[("s", 0, int(PacketClass.DATA))]
                outgoing = probe.windows[("m", 0, int(PacketClass.RESULT))]
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
                row = dict(
                    input=fmt.name,
                    output=output.name,
                    data_gbps=incoming.numeric_gbps(8192 * input_width),
                    result_gbps=outgoing.numeric_gbps(4096 * output_width),
                    result_axi_gbps=outgoing.axi_gbps(),
                    result_cycles=outgoing.cycles,
                    result_elements_s=4096 * 250e6 / outgoing.cycles,
                    input_stalls=probe.input_stalls[0],
                )
                rows.append(row)
                dut._log.info("U280_PROFILE %s", json.dumps(row))
                if row["data_gbps"] < 100 or row["result_gbps"] < 100:
                    misses.append((fmt.name, output.name))
            finally:
                monitor.cancel()
                sequence += 1
                result_path.write_text(json.dumps(rows, indent=2))
    assert not misses, f"100 Gb/s numeric payload gate failed: {misses}"


class ScenarioOf:
    """A backend that hands back what it was asked to run."""

    async def run(self, network, scenario):
        return network, scenario


@cocotb.test()
async def operation_after_an_abort_behind_data_starts_from_nothing(dut):
    fmt = ConcreteFormat.FP32
    length = 4096
    left = tuple(0x3F800000 + index for index in range(length))
    right = (0x40000000,) * length
    expected = tuple(
        combine_exact((decode_native(a, fmt), decode_native(b, fmt)))
        for a, b in zip(left, right, strict=True)
    )
    settings = dict(
        destination_rank=1,
        management_paths={"s": ("am", "hub", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=ResultWirePolicy.KULISCH,
        kulisch_bits=280,
        maximum_original_terms=2,
    )
    # The abort follows this many DATA frames on the same port without a gap.
    for run, frames_before in enumerate((1, 2, 5)):
        world, tree = one_port_world()
        left_behind = TypedVector(fmt, (0x41200000,) * length)
        world.register_reduce(
            "aborted", tree=tree, vectors={0: left_behind, 1: left_behind}, **settings
        )
        world.register_reduce(
            "next",
            tree=tree,
            vectors={0: TypedVector(fmt, left), 1: TypedVector(fmt, right)},
            **settings,
        )
        network, aborted = await world.run_async("aborted", backend=ScenarioOf())
        backend = CocotbSingleBackend(
            dut, prism_name="s", physical_ports=1, start_clock=run == 0, timeout_cycles=30000
        )

        async def abort_behind_data(
            ports, network=network, aborted=aborted, backend=backend, count=frames_before
        ):
            binding = compile_single(network, aborted, "s", physical_ports=1)
            await backend._control(
                ports, aborted, binding, ControlCommand.STAGE, 10, binding.context.pack()
            )
            await backend._control(ports, aborted, binding, ControlCommand.COMMIT, 11)
            frames, _packets = rank_data_frames(aborted, binding, binding.ranks[0])
            await ports.send_many(0, frames[:count])
            await backend._control(ports, aborted, binding, ControlCommand.ABORT, 13)
            # What the rank still sends afterwards belongs to no operation.
            await ports.send_many(0, frames[count : count + 2])

        backend.prelude = abort_behind_data
        result = await world.run_async("next", backend=backend)
        assert result.released_context
        assert result.rank_values == {1: expected}, frames_before
