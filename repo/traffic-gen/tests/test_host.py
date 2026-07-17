from __future__ import annotations

import unittest
from dataclasses import replace

from fakes import FakeSwitchClient
from prism_protocol.client import PrismManager
from prism_protocol.constants import (
    AccumulationPolicy,
    AccumulatorProfile,
    CollectiveSemantic,
    ControlCommand,
    NextHopType,
    NodeRole,
    OperationState,
    PartialWireFormat,
    ReductionOperator,
    Status,
    WireFormat,
)
from prism_protocol.errors import PrismError
from prism_protocol.host import HostOperationState, PrismHostCoordinator, RankBinding
from prism_protocol.model import (
    ContributorBinding,
    GroupDescriptor,
    NextHopEntry,
    OperationDescriptor,
    ReplicationGroup,
    ResultRangeRoute,
    UpstreamAction,
)


ROOT_MAC = bytes.fromhex("020000000001")
LEAF_MAC = bytes.fromhex("0200000000a0")
RANK_10_MAC = bytes.fromhex("020000000010")
RANK_20_MAC = bytes.fromhex("020000000011")


def group_descriptors() -> dict[str, GroupDescriptor]:
    return {
        "s0": GroupDescriptor(
            node_role=NodeRole.ROOT,
            expected_local_contributors=1,
            contributors=(ContributorBinding(0, 7, bytes.fromhex("020000000100")),),
            upstream=UpstreamAction(False, 0, 0, bytes(6)),
            replication_groups=(
                ReplicationGroup(1, (NextHopEntry(0, 3, NextHopType.SWITCH, LEAF_MAC),)),
            ),
        ),
        "l0": GroupDescriptor(
            node_role=NodeRole.LEAF,
            expected_local_contributors=2,
            contributors=(
                ContributorBinding(0, 1, RANK_10_MAC),
                ContributorBinding(1, 2, RANK_20_MAC),
            ),
            upstream=UpstreamAction(True, 0, 3, ROOT_MAC),
            replication_groups=(
                ReplicationGroup(2, (NextHopEntry(0, 1, NextHopType.RANK, RANK_10_MAC),)),
            ),
        ),
    }


def operation_descriptor(replication_group_id: int) -> OperationDescriptor:
    return OperationDescriptor(
        semantic=CollectiveSemantic.REDUCE,
        reduction_operator=ReductionOperator.SUM,
        input_format=WireFormat.FP32,
        accumulator_profile=AccumulatorProfile.FP32,
        accumulation_policy=AccumulationPolicy.CONTRIBUTOR_ORDERED,
        partial_format=PartialWireFormat.FP32,
        output_format=WireFormat.FP32,
        element_count=17,
        max_reduction_terms=2,
        requested_window_chunks=3,
        requested_replay_slots=3,
        timeout_ms=100,
        retry_limit=3,
        result_delivery_role=True,
        result_range_routes=(ResultRangeRoute(0, 0, replication_group_id),),
    )


class HostCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.switches = {name: FakeSwitchClient(name) for name in ("s0", "l0")}
        self.manager = PrismManager(self.switches)
        session = self.manager.open_session(0xCAFE)
        self.group = self.manager.create_group(session, 7, group_descriptors())
        self.coordinator = PrismHostCoordinator(self.manager)
        self.descriptors = {
            "s0": operation_descriptor(1),
            "l0": operation_descriptor(2),
        }
        self.bindings = (
            RankBinding(10, "l0", 0, LEAF_MAC, RANK_10_MAC),
            RankBinding(20, "l0", 1, LEAF_MAC, RANK_20_MAC),
        )

    def create_operation(self):
        return self.coordinator.create_operation(
            self.group,
            9,
            self.descriptors,
            self.bindings,
            reduce_root_rank_id=10,
            parent_edges={"l0": "s0"},
        )

    def test_incomplete_rank_barrier_does_not_contact_am_or_publish_grants(self) -> None:
        operation = self.create_operation()

        activated = self.coordinator.rank_arrive(operation, 10)

        self.assertFalse(activated)
        self.assertEqual(operation.state, HostOperationState.WAITING_FOR_RANKS)
        self.assertEqual(operation.pending_rank_ids, (20,))
        self.assertEqual(self.coordinator.start_grants(operation), ())
        self.assertIsNone(self.coordinator.start_grant_for_rank(operation, 10))
        for switch in self.switches.values():
            self.assertEqual(switch.calls[ControlCommand.OP_PREPARE], 0)
            self.assertEqual(switch.calls[ControlCommand.OP_COMMIT], 0)

    def test_last_arrival_commits_every_switch_then_publishes_all_grants(self) -> None:
        operation = self.create_operation()
        self.coordinator.rank_arrive(operation, 10)

        activated = self.coordinator.rank_arrive(operation, 20)

        self.assertTrue(activated)
        self.assertEqual(operation.state, HostOperationState.ACTIVE)
        self.assertEqual(operation.am_operation.state, OperationState.ACTIVE)
        self.assertEqual(operation.pending_rank_ids, ())
        self.assertEqual([grant.rank_id for grant in self.coordinator.start_grants(operation)], [10, 20])
        for switch in self.switches.values():
            self.assertEqual(switch.calls[ControlCommand.OP_PREPARE], 1)
            self.assertEqual(switch.calls[ControlCommand.OP_COMMIT], 1)

    def test_commit_failure_publishes_no_start_grants(self) -> None:
        operation = self.create_operation()
        self.coordinator.rank_arrive(operation, 10)
        self.switches["l0"].fail_once[ControlCommand.OP_COMMIT] = Status.INVALID_STATE

        with self.assertRaises(PrismError) as raised:
            self.coordinator.rank_arrive(operation, 20)

        self.assertEqual(raised.exception.status, Status.INVALID_STATE)
        self.assertEqual(operation.state, HostOperationState.FAILED)
        self.assertIs(operation.failure, raised.exception)
        self.assertEqual(operation.am_operation.state, OperationState.FREE)
        self.assertFalse(operation.am_operation.valid)
        with self.assertRaises(PrismError) as rank_10:
            self.coordinator.start_grant_for_rank(operation, 10)
        with self.assertRaises(PrismError) as rank_20:
            self.coordinator.start_grant_for_rank(operation, 20)
        self.assertEqual(rank_10.exception.status, Status.INVALID_STATE)
        self.assertEqual(rank_20.exception.status, Status.INVALID_STATE)
        for switch in self.switches.values():
            self.assertEqual(switch.calls[ControlCommand.OP_ABORT], 1)
            self.assertEqual(switch.calls[ControlCommand.OP_RELEASE], 1)

    def test_per_rank_grant_carries_identity_geometry_and_leaf_admission(self) -> None:
        operation = self.create_operation()
        self.coordinator.rank_arrive(operation, 10)
        self.coordinator.rank_arrive(operation, 20)

        rank_10 = self.coordinator.start_grant_for_rank(operation, 10)
        rank_20 = self.coordinator.start_grant_for_rank(operation, 20)

        self.assertEqual(
            (
                rank_10.job_id,
                rank_10.group_id,
                rank_10.group_generation,
                rank_10.operation_id,
                rank_10.operation_generation,
            ),
            (
                self.group.session.job_id,
                self.group.wire.group_id,
                self.group.wire.generation,
                operation.am_operation.wire.operation_id,
                operation.am_operation.wire.generation,
            ),
        )
        self.assertEqual((rank_10.leaf_switch_id, rank_10.contributor_id), ("l0", 0))
        self.assertEqual((rank_20.leaf_switch_id, rank_20.contributor_id), ("l0", 1))
        self.assertEqual(rank_10.destination_mac, LEAF_MAC)
        self.assertEqual(rank_20.destination_mac, LEAF_MAC)
        self.assertEqual(rank_10.result_destination_mac, RANK_10_MAC)
        self.assertEqual(rank_20.result_destination_mac, RANK_20_MAC)
        self.assertEqual((rank_10.ingress_port, rank_10.source_mac), (1, bytes.fromhex("020000000010")))
        self.assertEqual((rank_20.ingress_port, rank_20.source_mac), (2, bytes.fromhex("020000000011")))
        self.assertEqual(rank_10.semantic, CollectiveSemantic.REDUCE)
        self.assertEqual(rank_10.reduction_operator, ReductionOperator.SUM)
        self.assertEqual(rank_10.input_format, WireFormat.FP32)
        self.assertEqual(rank_10.output_format, WireFormat.FP32)
        self.assertEqual(rank_10.accumulator_profile, AccumulatorProfile.FP32)
        self.assertEqual(rank_10.accumulation_policy, AccumulationPolicy.CONTRIBUTOR_ORDERED)
        self.assertEqual(
            (
                rank_10.element_count,
                rank_10.input_elements_per_chunk,
                rank_10.input_expected_chunks,
                rank_10.output_elements_per_chunk,
                rank_10.output_expected_chunks,
                rank_10.admitted_window_chunks,
            ),
            (17, 368, 1, 368, 1, 3),
        )
        self.assertEqual(
            rank_10.admitted_window_chunks,
            operation.am_operation.granted_resources["l0"].accumulator_ranges,
        )

    def test_duplicate_arrival_is_idempotent(self) -> None:
        operation = self.create_operation()
        self.assertFalse(self.coordinator.rank_arrive(operation, 10))
        self.assertFalse(self.coordinator.rank_arrive(operation, 10))
        self.assertEqual(operation.pending_rank_ids, (20,))

    def test_complete_and_release_retire_all_start_grants(self) -> None:
        operation = self.create_operation()
        self.coordinator.rank_arrive(operation, 10)
        self.coordinator.rank_arrive(operation, 20)
        key = (operation.am_operation.wire.operation_id, operation.am_operation.wire.generation)
        for switch in self.switches.values():
            switch.operations[key] = OperationState.COMPLETE

        self.coordinator.wait_operation(operation, timeout_seconds=0.01, poll_seconds=0)

        self.assertEqual(operation.state, HostOperationState.COMPLETE)
        self.assertEqual(self.coordinator.start_grants(operation), ())
        self.coordinator.release_operation(operation)
        self.assertEqual(operation.state, HostOperationState.RELEASED)
        self.assertFalse(operation.am_operation.valid)

    def test_reduce_routes_must_reach_the_requested_root_rank(self) -> None:
        with self.assertRaisesRegex(ValueError, "participant semantics"):
            self.coordinator.create_operation(
                self.group,
                11,
                self.descriptors,
                self.bindings,
                reduce_root_rank_id=20,
                parent_edges={"l0": "s0"},
            )

    def test_allreduce_routes_must_reach_every_participant(self) -> None:
        descriptors = {
            switch_id: replace(descriptor, semantic=CollectiveSemantic.ALLREDUCE)
            for switch_id, descriptor in self.descriptors.items()
        }

        with self.assertRaisesRegex(ValueError, "participant semantics"):
            self.coordinator.create_operation(
                self.group,
                12,
                descriptors,
                self.bindings,
                parent_edges={"l0": "s0"},
            )


if __name__ == "__main__":
    unittest.main()
