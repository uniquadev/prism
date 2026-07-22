"""Public CCL lifecycle tests over the transport-independent in-memory backend."""

from __future__ import annotations

import asyncio
import unittest

from prism_ccl import CollectiveConfig, Communicator, Datatype
from prism_ccl.collectives import CommunicatorClosedError, RequestStatus
from prism_ccl.collectives.reference import evaluate_reference_collective
from prism_ccl.protocol.constants import AccumulatorProfile
from prism_ccl.transport import Endpoint, InMemoryCollectiveNetwork, InMemoryTransport

ONE = 0x3F800000
TWO = 0x40000000
THREE = 0x40400000


class CommunicatorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        network = InMemoryCollectiveNetwork(evaluate_reference_collective)
        self.communicators = tuple(
            Communicator(
                communicator_id="integration",
                ranks=(0, 1),
                rank=rank,
                transport=InMemoryTransport(network, endpoint=Endpoint(port=rank, rank=rank)),
            )
            for rank in (0, 1)
        )
        await asyncio.gather(*(item.start() for item in self.communicators))

    async def asyncTearDown(self) -> None:
        await asyncio.gather(*(item.close() for item in self.communicators))

    async def test_reduce_exposes_result_only_at_explicit_root(self) -> None:
        rank0, rank1 = await asyncio.gather(
            self.communicators[0].reduce((ONE,), root=1),
            self.communicators[1].reduce((TWO,), root=1),
        )
        self.assertIsNone(rank0.values)
        self.assertEqual(rank1.values, (THREE,))

    async def test_allreduce_is_nonblocking_and_reusable(self) -> None:
        request0 = self.communicators[0].iallreduce((ONE, TWO))
        request1 = self.communicators[1].iallreduce((TWO, ONE))
        self.assertEqual(request0.status, RequestStatus.PENDING)
        first0, first1 = await asyncio.gather(request0.wait(), request1.wait())
        self.assertEqual(first0.values, (THREE, THREE))
        self.assertEqual(first1.values, (THREE, THREE))
        self.assertEqual(request0.status, RequestStatus.COMPLETE)

        second = await asyncio.gather(
            self.communicators[0].allreduce((ONE,)),
            self.communicators[1].allreduce((ONE,)),
        )
        self.assertEqual(second[0].values, (TWO,))
        self.assertEqual(second[1].values, (TWO,))

    async def test_kulisch_warning_propagates_through_public_result(self) -> None:
        config = CollectiveConfig(
            datatype=Datatype.FP32,
            output_datatype=Datatype.FP32,
            accumulator=AccumulatorProfile.KULISCH_FP32,
            maximum_terms=2,
            compiled_widths=(64,),
        )
        results = await asyncio.gather(
            self.communicators[0].allreduce((ONE,), config=config),
            self.communicators[1].allreduce((ONE,), config=config),
        )
        self.assertTrue(results[0].accumulation_inexact)
        self.assertTrue(results[1].accumulation_inexact)

    async def test_closed_communicator_rejects_new_work(self) -> None:
        await self.communicators[0].close()
        with self.assertRaises(CommunicatorClosedError):
            self.communicators[0].iallreduce((ONE,))
