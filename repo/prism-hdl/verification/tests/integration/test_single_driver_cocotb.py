"""The library driver of one SINGLE operation runs against the RTL and its recording."""

from __future__ import annotations

from typing import Any

import cocotb
from ccl.world import CompiledFramePorts
from prism_ccl.application.single import (
    ReplayTransport,
    compile_single,
    run_single,
    script_single,
)
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native

from tests.integration.test_u280_profile_cocotb import one_port_world

# Shortest frame a 100G MAC sends without padding it: 60 bytes before the FCS.
MINIMUM_FRAME_BYTES = 60


@cocotb.test()
async def library_driver_runs_an_operation_and_replays_its_recording(dut: Any) -> None:
    fmt = ConcreteFormat.FP32
    source = tuple(
        round_native(decode_native(x & 255, ConcreteFormat.INT8), fmt)
        for x in (-3, 1, 2, 0, 3, -1, -2, 0)
    )
    left = source * 64
    right = tuple(reversed(source)) * 64
    expected = tuple(
        combine_exact((decode_native(a, fmt), decode_native(b, fmt)))
        for a, b in zip(left, right, strict=True)
    )
    for output in (ResultWirePolicy.FP32, ResultWirePolicy.AUTO):
        world, tree = one_port_world()
        world.register_reduce(
            "driver",
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
        network = world.network
        scenario = world.scenario("driver")
        binding = compile_single(network, scenario, "s", physical_ports=1)
        ports = CompiledFramePorts(dut, timeout_cycles=30000, physical_ports=1)
        await ports.start(binding.node_mac, start_clock=output == ResultWirePolicy.FP32)
        try:
            outcome = await run_single(scenario, binding, ports)
        finally:
            ports.stop()
        assert outcome.rank_values == {1: expected}
        if output == ResultWirePolicy.FP32:
            assert outcome.rank_bits == {1: tuple(round_native(x, fmt) for x in expected)}

        # Every frame the node sent can leave a 100G MAC as it is.
        short = [len(frame) for _port, frame in ports.history if len(frame) < MINIMUM_FRAME_BYTES]
        assert not short, f"frames shorter than {MINIMUM_FRAME_BYTES} bytes: {short}"

        # The recording gives the same outcome, and the frames the driver
        # sent are those of the script for a simulation without a manager.
        replay = ReplayTransport(ports.history)
        assert await run_single(scenario, binding, replay) == outcome
        assert not replay.untaken()
        assert replay.sent == list(ports.transmitted)
        scripted = [
            (step.port, step.frame)
            for step in script_single(scenario, binding)
            if step.kind == "send"
        ]
        assert scripted == list(ports.transmitted)
