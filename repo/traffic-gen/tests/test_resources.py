from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prism_protocol.constants import (
    MAX_BITMAP_BYTES,
    MAX_CHUNKS,
    AccumulationPolicy,
    AccumulatorProfile,
    CollectiveSemantic,
    FeatureFlag,
    NextHopType,
    NodeRole,
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
    ContributorBinding,
    GenerationStore,
    GroupDescriptor,
    NextHopEntry,
    OperationDescriptor,
    PhaseBitmap,
    PhaseBitmapAllocation,
    ReliableOperationModel,
    ReliableSender,
    ReplicationGroup,
    ReplayCache,
    ResourceAllocation,
    ResourcePool,
    UpstreamAction,
)
from prism_protocol.wire import OperationIdentity


def identity(generation: int) -> OperationIdentity:
    return OperationIdentity(0x100, 1, 1, 2, generation)


def operation_descriptor(*, result_role: bool = False, requested_slots: int = 4, chunks: int = 4) -> OperationDescriptor:
    routes = ()
    if result_role:
        from prism_protocol.model import ResultRangeRoute

        routes = (ResultRangeRoute(0, chunks - 1, 1),)
    return OperationDescriptor(
        CollectiveSemantic.REDUCE,
        ReductionOperator.SUM,
        WireFormat.FP32,
        AccumulatorProfile.FP32,
        AccumulationPolicy.CONTRIBUTOR_ORDERED,
        PartialWireFormat.FP32,
        WireFormat.FP32,
        element_count=chunks * 368,
        max_reduction_terms=4,
        requested_window_chunks=requested_slots,
        requested_replay_slots=4,
        timeout_ms=100,
        retry_limit=2,
        result_delivery_role=result_role,
        result_range_routes=routes,
    )


def group_descriptor(*, destination_count: int = 1) -> GroupDescriptor:
    destinations = tuple(
        NextHopEntry(index, index + 1, NextHopType.RANK, bytes.fromhex(f"0200000000{index + 1:02x}"))
        for index in range(destination_count)
    )
    return GroupDescriptor(
        NodeRole.SINGLE,
        1,
        (ContributorBinding(0, 1, bytes.fromhex("020000000001")),),
        UpstreamAction(False, 0, 0, bytes(6)),
        (ReplicationGroup(1, destinations),),
    )


class BitmapAndAdmissionTests(unittest.TestCase):
    def test_group_descriptor_reserves_legacy_quota_bytes(self) -> None:
        descriptor = group_descriptor()
        encoded = descriptor.descriptor_tlv().value
        self.assertEqual(encoded, bytes.fromhex("0400000100000000"))
        malformed = bytearray(encoded)
        malformed[7] = 1
        with self.assertRaisesRegex(ValueError, "reserved field"):
            GroupDescriptor.unpack_descriptor(
                bytes(malformed),
                descriptor.contributors,
                descriptor.upstream,
                descriptor.replication_groups,
            )

    def test_group_admission_uses_actual_replication_records(self) -> None:
        descriptor = group_descriptor(destination_count=2)
        pool = ResourcePool(Capabilities.reference(max_replication_groups=1, max_result_destinations_per_group=2))
        before = pool.snapshot()
        reservation = pool.stage_group((1, 1), descriptor)
        after = pool.snapshot()
        self.assertEqual((reservation.replication_groups, reservation.replication_entries), (1, 2))
        self.assertEqual(before.free_replication_groups - after.free_replication_groups, 1)
        self.assertEqual(before.free_replication_entries - after.free_replication_entries, 2)

        limited = ResourcePool(Capabilities.reference(max_replication_groups=1, max_result_destinations_per_group=1))
        with self.assertRaises(PrismError) as caught:
            limited.stage_group((1, 1), descriptor)
        self.assertEqual(caught.exception.status, Status.NO_REPLICATION_RESOURCE)

    def test_reserved_feature_bits_are_rejected(self) -> None:
        advertised = Capabilities.reference(feature_flags=FeatureFlag(0x80))
        with self.assertRaisesRegex(ValueError, "reserved feature bits"):
            Capabilities.from_tlv(advertised.device_boot_id, advertised.to_tlv())

    def test_resource_allocation_round_trip(self) -> None:
        allocation = ResourceAllocation(
            operation_slots=1,
            phase_bitmap_bytes=17,
            accumulator_ranges=4,
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
        self.assertEqual(before.free_operation_contexts, after.free_operation_contexts + 1)

    def test_no_operation_slot(self) -> None:
        pool = ResourcePool(Capabilities.reference(max_operation_contexts=1))
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
        pool = ResourcePool(Capabilities.reference(max_active_accumulator_ranges_global=2, max_active_accumulator_ranges_per_operation=2))
        reservation = pool.prepare_operation((1, 1, 1, 1), operation_descriptor(requested_slots=8))
        self.assertEqual(reservation.accumulator_ranges, 2)
        with self.assertRaises(PrismError) as caught:
            pool.prepare_operation((1, 1, 2, 1), operation_descriptor())
        self.assertEqual(caught.exception.status, Status.NO_ACCUMULATOR_RANGE)

    def test_release_frees_exact_allocation(self) -> None:
        pool = ResourcePool(Capabilities.reference())
        before = pool.snapshot()
        reservation = pool.prepare_operation((1, 1, 1, 1), operation_descriptor(result_role=True))
        during = pool.snapshot()
        released = pool.release_operation((1, 1, 1, 1))
        after = pool.snapshot()
        self.assertEqual(released, reservation)
        self.assertEqual(before.free_phase_bitmap_bytes, after.free_phase_bitmap_bytes)
        self.assertEqual(before.free_accumulator_ranges, after.free_accumulator_ranges)
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
