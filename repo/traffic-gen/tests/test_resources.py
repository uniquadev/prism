from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prism_protocol.constants import (
    MAX_BITMAP_BYTES,
    MAX_CHUNKS,
    AccumulatorMode,
    CollectiveSemantic,
    FeatureFlag,
    OperationState,
    PartialWireFormat,
    ReductionOperator,
    Status,
    TlvType,
    WireFormat,
)
from prism_protocol.errors import GenerationWrapRequiresNewJob, InvalidHandleError, PrismError
from prism_protocol.model import (
    Capabilities,
    GenerationStore,
    OperationDescriptor,
    PhaseBitmap,
    PhaseBitmapAllocation,
    ReliableOperationModel,
    ReliableSender,
    ReplayCache,
    ResourceAllocation,
    ResourcePool,
)
from prism_protocol.wire import OperationIdentity


def identity(generation: int) -> OperationIdentity:
    return OperationIdentity(0x100, 1, 1, 2, generation)


def operation_descriptor(*, result_role: bool = False, requested_slots: int = 4, chunks: int = 4) -> OperationDescriptor:
    routes = ()
    if result_role:
        from prism_protocol.model import ResultRoute

        routes = (ResultRoute(0, chunks - 1, 1),)
    return OperationDescriptor(
        CollectiveSemantic.REDUCE,
        ReductionOperator.SUM,
        WireFormat.FP32,
        AccumulatorMode.DETERMINISTIC_FP32,
        PartialWireFormat.FP32,
        WireFormat.FP32,
        element_count=chunks,
        elements_per_chunk=1,
        max_reduction_terms=4,
        requested_window_chunks=requested_slots,
        requested_replay_slots=4,
        timeout_ms=100,
        retry_limit=2,
        result_delivery_role=result_role,
        result_routes=routes,
    )


class BitmapAndAdmissionTests(unittest.TestCase):
    def test_reserved_feature_bits_are_rejected(self) -> None:
        advertised = Capabilities.reference(feature_flags=FeatureFlag(0x80))
        with self.assertRaisesRegex(ValueError, "reserved feature bits"):
            Capabilities.from_tlv(advertised.device_boot_id, advertised.to_tlv())

    def test_resource_allocation_round_trip(self) -> None:
        allocation = ResourceAllocation(
            operation_slots=1,
            phase_bitmap_bytes=17,
            aggregation_slots=4,
            replay_output_slots=8,
        )
        tlv = allocation.to_tlv(TlvType.GRANTED_RESOURCES)
        self.assertEqual(len(tlv.value), 4 * 16)
        self.assertEqual(ResourceAllocation.from_tlv(tlv), allocation)

    def test_exact_bitmap_byte_calculations(self) -> None:
        expected = {0: 0, 1: 1, 7: 1, 8: 1, 9: 2, MAX_CHUNKS: MAX_BITMAP_BYTES}
        for chunks, bytes_ in expected.items():
            with self.subTest(chunks=chunks):
                aggregation = PhaseBitmapAllocation.calculate(chunks, False)
                both = PhaseBitmapAllocation.calculate(chunks, True)
                self.assertEqual(aggregation.total_bytes, bytes_)
                self.assertEqual(both.total_bytes, 2 * bytes_)
        self.assertEqual(PhaseBitmapAllocation.calculate(MAX_CHUNKS, True).total_bytes, 4 * 1024 * 1024)

    def test_phase_bitmap_duplicates_counts_and_completion(self) -> None:
        phase = PhaseBitmap(2, True)
        self.assertTrue(phase.mark_aggregation_done(0))
        self.assertFalse(phase.mark_aggregation_done(0))
        self.assertEqual(phase.aggregation_done_count, 1)
        phase.mark_aggregation_done(1)
        self.assertFalse(phase.complete)
        phase.mark_result_done(0)
        self.assertFalse(phase.complete)
        phase.mark_result_done(1)
        self.assertTrue(phase.complete)
        self.assertEqual(phase.result_done_count, 2)

    def test_snapshot_is_advisory_and_becomes_stale(self) -> None:
        pool = ResourcePool(Capabilities.reference())
        before = pool.snapshot()
        pool.prepare_operation((1, 1, 1, 1), operation_descriptor())
        after = pool.snapshot()
        self.assertGreater(before.free_phase_bitmap_bytes, after.free_phase_bitmap_bytes)
        self.assertEqual(before.free_prepared_operation_slots, after.free_prepared_operation_slots + 1)

    def test_no_operation_slot(self) -> None:
        pool = ResourcePool(Capabilities.reference(max_prepared_operations=1))
        pool.prepare_operation((1, 1, 1, 1), operation_descriptor())
        with self.assertRaises(PrismError) as caught:
            pool.prepare_operation((1, 1, 2, 1), operation_descriptor())
        self.assertEqual(caught.exception.status, Status.NO_OPERATION_SLOT)

    def test_insufficient_bitmap_memory(self) -> None:
        pool = ResourcePool(Capabilities.reference(total_phase_bitmap_pool_bytes=0))
        with self.assertRaises(PrismError) as caught:
            pool.prepare_operation((1, 1, 1, 1), operation_descriptor())
        self.assertEqual(caught.exception.status, Status.NO_BITMAP_MEMORY)

    def test_insufficient_active_slots_and_smaller_grant(self) -> None:
        pool = ResourcePool(Capabilities.reference(max_active_aggregation_slots_global=2, max_active_aggregation_slots_per_operation=2))
        reservation = pool.prepare_operation((1, 1, 1, 1), operation_descriptor(requested_slots=8))
        self.assertEqual(reservation.aggregation_slots, 2)
        with self.assertRaises(PrismError) as caught:
            pool.prepare_operation((1, 1, 2, 1), operation_descriptor())
        self.assertEqual(caught.exception.status, Status.NO_AGGREGATION_SLOT)

    def test_release_frees_exact_allocation(self) -> None:
        pool = ResourcePool(Capabilities.reference())
        before = pool.snapshot()
        reservation = pool.prepare_operation((1, 1, 1, 1), operation_descriptor(result_role=True))
        during = pool.snapshot()
        released = pool.release_operation((1, 1, 1, 1))
        after = pool.snapshot()
        self.assertEqual(released, reservation)
        self.assertEqual(before.free_phase_bitmap_bytes, after.free_phase_bitmap_bytes)
        self.assertEqual(before.free_aggregation_slots, after.free_aggregation_slots)
        self.assertEqual(before.free_phase_bitmap_bytes - during.free_phase_bitmap_bytes, reservation.bitmap_bytes)


class ReliabilityTests(unittest.TestCase):
    def test_duplicate_contribution_active_and_after_done(self) -> None:
        current = identity(3)
        model = ReliableOperationModel(current, expected_chunks=2, contributors=2, admitted_window_chunks=2, slot_count=2)
        self.assertEqual(model.receive_data(current, 0, 0), Status.OK)
        self.assertEqual(model.receive_data(current, 0, 0), Status.ALREADY_EXISTS)
        self.assertEqual(model.receive_data(current, 1, 0), Status.OK)
        self.assertFalse(model.phase.aggregation_done(0))
        model.acknowledge_upstream(0)
        self.assertTrue(model.phase.aggregation_done(0))
        self.assertEqual(model.receive_data(current, 0, 0), Status.ALREADY_EXISTS)

    def test_reordering_window_no_slot_and_stale_generation(self) -> None:
        current = identity(5)
        model = ReliableOperationModel(current, expected_chunks=4, contributors=1, admitted_window_chunks=2, slot_count=1)
        self.assertEqual(model.receive_data(current, 0, 1), Status.OK)
        self.assertEqual(model.receive_data(current, 0, 0), Status.RETRY)
        self.assertEqual(model.receive_data(current, 0, 2), Status.OUT_OF_WINDOW)
        self.assertEqual(model.receive_data(identity(4), 0, 0), Status.GENERATION_MISMATCH)

    def test_result_waits_for_every_replica_and_duplicate_result_ack(self) -> None:
        current = identity(1)
        model = ReliableOperationModel(current, expected_chunks=1, contributors=1, admitted_window_chunks=1, slot_count=1, result_paths=(10, 11))
        model.receive_data(current, 0, 0)
        model.acknowledge_upstream(0)
        model.begin_result(0)
        self.assertFalse(model.acknowledge_result_path(0, 10))
        self.assertFalse(model.phase.result_done(0))
        self.assertTrue(model.acknowledge_result_path(0, 11))
        self.assertTrue(model.phase.result_done(0))
        self.assertFalse(model.acknowledge_result_path(0, 11))
        self.assertTrue(model.complete)

    def test_lost_ack_retransmission_and_timeout(self) -> None:
        sender = ReliableSender(timeout_seconds=1.0, retry_limit=2)
        sender.retain(7, 3, b"payload", now=0.0)
        self.assertEqual(sender.due(0.5), ())
        self.assertEqual(sender.due(1.0)[0].retries, 1)
        self.assertEqual(sender.due(2.0)[0].retries, 2)
        self.assertTrue(sender.acknowledge(7, 3))
        self.assertFalse(sender.acknowledge(7, 3))

        sender.retain(8, 4, b"payload", now=0.0)
        sender.due(1.0)
        sender.due(2.0)
        with self.assertRaises(PrismError) as caught:
            sender.due(3.0)
        self.assertEqual(caught.exception.status, Status.TIMEOUT)


class ReplayAndGenerationTests(unittest.TestCase):
    def test_idempotent_replay_and_transaction_conflict(self) -> None:
        cache = ReplayCache(depth=2, retention_seconds=10)
        calls = 0

        def action() -> bytes:
            nonlocal calls
            calls += 1
            return b"response"

        self.assertEqual(cache.execute(1, 2, 3, b"payload", action), b"response")
        self.assertEqual(cache.execute(1, 2, 3, b"payload", action), b"response")
        self.assertEqual(calls, 1)
        with self.assertRaises(PrismError) as caught:
            cache.execute(1, 2, 3, b"different", action)
        self.assertEqual(caught.exception.status, Status.TXN_CONFLICT)

    def test_generation_reuse_requires_release_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generations.json"
            store = GenerationStore(path)
            self.assertEqual(store.allocate("group", 7, 16), 1)
            with self.assertRaises(InvalidHandleError):
                store.allocate("group", 7, 16)
            store.release("group", 7)
            self.assertEqual(store.allocate("group", 7, 16), 2)
            restored = GenerationStore(path)
            with self.assertRaises(InvalidHandleError):
                restored.allocate("group", 7, 16)

    def test_generation_wrap_requires_new_job(self) -> None:
        store = GenerationStore()
        store._state["operation:1"] = {"generation": (1 << 32) - 1, "in_use": False}
        with self.assertRaises(GenerationWrapRequiresNewJob):
            store.allocate("operation", 1, 32)


if __name__ == "__main__":
    unittest.main()
