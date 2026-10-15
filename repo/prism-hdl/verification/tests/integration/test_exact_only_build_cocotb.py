"""The U280 arithmetic build retains numeric I/O but rejects FP32 policies."""

from __future__ import annotations

from typing import Any

import cocotb
from ccl.examples import single_world
from ccl.world import CocotbSingleBackend, CompiledFramePorts, compile_single
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
    ControlStatus,
    decode_control_frame,
    encode_control_frame,
)
from prism_ccl.wire.data import PacketClass

from .test_prismworld_line_rate_target_cocotb import STREAM_ELEMENTS, check_profile


@cocotb.test()
async def kulisch_only_build_preserves_streaming_rate(dut: Any) -> None:
    assert not hasattr(dut.u_core.u_single.u_ingress, "gen_arrival_round")
    await check_profile(
        dut,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.AUTO,
        elements=STREAM_ELEMENTS,
    )


@cocotb.test()
async def kulisch_only_build_accepts_kulisch_partials(dut: Any) -> None:
    await check_profile(
        dut,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.KULISCH,
        elements=STREAM_ELEMENTS,
    )


@cocotb.test()
async def kulisch_only_build_accepts_each_input_and_output_format(dut: Any) -> None:
    native = (
        (ConcreteFormat.INT8, 1, 2),
        (ConcreteFormat.FP16, 0x3C00, 0x4000),
        (ConcreteFormat.BF16, 0x3F80, 0x4000),
        (ConcreteFormat.FP32, 0x3F800000, 0x40000000),
    )
    cases = tuple((fmt, left, right, ResultWirePolicy(fmt)) for fmt, left, right in native)
    cases += (
        (ConcreteFormat.FP16, 0x3C00, 0x4000, ResultWirePolicy.KULISCH),
        (ConcreteFormat.FP32, 0x3F800000, 0x40000000, ResultWirePolicy.AUTO),
    )
    for index, (fmt, left, right, output) in enumerate(cases):
        world, tree = single_world()
        world.register_reduce(
            "exact-only",
            tree=tree,
            vectors={
                0: TypedVector(fmt, (left, right)),
                1: TypedVector(fmt, (right, left)),
            },
            destination_rank=1,
            management_paths={"s": ("am", "forward", "s")},
            accumulator=AccumulatorPolicy.KULISCH_FIXED,
            partial_wire=PartialWirePolicy.AUTO,
            output_format=output,
        )
        result = await world.run_async(
            "exact-only",
            backend=CocotbSingleBackend(dut, prism_name="s", start_clock=index == 0),
        )
        exact = combine_exact((decode_native(left, fmt), decode_native(right, fmt)))
        if output in (ResultWirePolicy.AUTO, ResultWirePolicy.KULISCH):
            assert result.rank_values == {1: (exact, exact)}
        else:
            assert result.rank_bits == {1: (round_native(exact, fmt),) * 2}
        assert result.released_context


@cocotb.test()
async def disabled_fp32_policy_is_rejected_at_stage(dut: Any) -> None:
    world, tree = single_world()
    world.register_reduce(
        "disabled-fp32",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, (0x3F800000,)),
            1: TypedVector(ConcreteFormat.FP32, (0x40000000,)),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=AccumulatorPolicy.FP32_ARRIVAL,
        partial_wire=PartialWirePolicy.FP32,
    )
    scenario = world._scenarios["disabled-fp32"]
    binding = compile_single(world.network, scenario, "s")
    ports = CompiledFramePorts(dut, timeout_cycles=6000)
    await ports.start(binding.node_mac)
    try:
        request = ControlPacket(
            scenario.config.key,
            10,
            0xFFFE,
            0xFFFE,
            ControlCommand.STAGE,
            body=binding.context.pack(),
        )
        await ports.send(
            0,
            encode_control_frame(
                request,
                destination_mac=binding.node_mac,
                source_mac=binding.manager_mac,
                mtu=scenario.config.mtu,
            ),
        )
        response = decode_control_frame(
            await ports.receive(PacketClass.CONTROL, port=0), mtu=scenario.config.mtu
        )
        assert response.command == ControlCommand.ACK
        assert response.transaction_id == 10
        assert response.status != ControlStatus.OK
    finally:
        ports.stop()
