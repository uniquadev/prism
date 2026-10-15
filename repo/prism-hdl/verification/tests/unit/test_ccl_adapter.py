"""Validate the active PrismWorld-to-compiled-SINGLE binding."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ccl.examples import shared_port_world, single_world
from ccl.world import FrameObservation, SingleBinding, compile_single, summarize_timing
from prism_ccl.application.software import Scenario
from prism_ccl.domain.model import ConcreteFormat, TypedVector
from prism_ccl.domain.topology import PhysicalNetwork
from prism_ccl.wire.control import ControlCommand
from prism_ccl.wire.data import PacketClass


class TimingSummaryTests(unittest.TestCase):
    def test_uses_accepted_beat_boundaries_across_ports(self) -> None:
        def frame(packet_class: PacketClass) -> bytes:
            return bytes(15) + bytes([packet_class])

        observations = (
            FrameObservation("rx", 0, 10, 12, frame(PacketClass.CONTROL)),
            FrameObservation("tx", 0, 20, 20, frame(PacketClass.CONTROL)),
            FrameObservation("rx", 0, 25, 27, frame(PacketClass.DATA)),
            FrameObservation("rx", 1, 26, 30, frame(PacketClass.DATA)),
            FrameObservation("tx", 1, 35, 38, frame(PacketClass.RESULT)),
            FrameObservation("tx", 0, 34, 40, frame(PacketClass.RESULT)),
        )
        controls = (
            SimpleNamespace(command=ControlCommand.STAGE, transaction_id=10),
            SimpleNamespace(command=ControlCommand.ACK, transaction_id=11),
        )
        with patch("ccl.world.decode_control_frame", side_effect=controls):
            timing = summarize_timing(observations, mtu=1500)
        self.assertEqual(timing.collective_cycles, 31)
        self.assertEqual(timing.setup_cycles, 11)
        self.assertEqual(timing.data_to_result_cycles, 16)
        self.assertEqual(timing.data_window_cycles, 6)
        self.assertEqual(timing.result_window_cycles, 7)

    def test_missing_result_is_not_a_measurement(self) -> None:
        with self.assertRaisesRegex(AssertionError, "incomplete"):
            summarize_timing((), mtu=1500)


class BindingBackend:
    def __init__(self, prism_name: str) -> None:
        self.prism_name = prism_name

    async def run(self, network: PhysicalNetwork, scenario: Scenario) -> SingleBinding:
        return compile_single(network, scenario, self.prism_name)


def register(world, tree, *, elements: int = 2) -> None:
    world.register_allreduce(
        "binding",
        tree=tree,
        vectors={
            node.rank_id: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * elements)
            for node in tree.nodes
            if node.rank_id is not None
        },
        management_paths={"s": ("am", "forward", "s")},
    )


class CompiledSingleBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_port_uses_distinct_logical_endpoints(self) -> None:
        world, tree = shared_port_world()
        register(world, tree)
        binding = await world.run_async("binding", backend=BindingBackend("s"))
        self.assertEqual(
            [(rank.rank, rank.port) for rank in binding.ranks], [(0, 0), (1, 1), (2, 0)]
        )
        self.assertEqual([rank.local_endpoint for rank in binding.ranks], [10, 11, 12])
        self.assertEqual(binding.context.mtu, 1500)
        self.assertEqual(len(binding.context.bindings), 3)

    async def test_rejects_unbound_prism_and_oversize_vector(self) -> None:
        world, tree = single_world()
        register(world, tree)
        with self.assertRaisesRegex(ValueError, "exactly one SINGLE"):
            await world.run_async("binding", backend=BindingBackend("other"))

        world, tree = single_world()
        register(world, tree, elements=4097)
        with self.assertRaisesRegex(ValueError, "not advertised"):
            await world.run_async("binding", backend=BindingBackend("s"))


if __name__ == "__main__":
    unittest.main()
