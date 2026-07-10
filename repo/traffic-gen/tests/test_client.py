from __future__ import annotations

import unittest
from dataclasses import replace

from fakes import FakeSwitchClient
from prism_protocol.client import PrismManager
from prism_protocol.constants import (
    AccumulatorMode,
    CollectiveSemantic,
    ControlCommand,
    GroupState,
    NodeRole,
    OperationState,
    ReductionOperator,
    Status,
    WireFormat,
)
from prism_protocol.errors import InvalidHandleError, PrismError
from prism_protocol.model import (
    ContributorBinding,
    GroupDescriptor,
    OperationDescriptor,
    UpstreamAction,
)


def group_descriptor() -> GroupDescriptor:
    return GroupDescriptor(
        node_role=NodeRole.SINGLE,
        expected_local_contributors=1,
        max_replication_groups=0,
        max_replication_entries=0,
        contributors=(ContributorBinding(0, 1, bytes.fromhex("020000000001")),),
        upstream=UpstreamAction(False, 0, 0, bytes(6)),
    )


def operation_descriptor() -> OperationDescriptor:
    return OperationDescriptor(
        semantic=CollectiveSemantic.REDUCE,
        reduction_operator=ReductionOperator.SUM,
        input_format=WireFormat.FP32,
        accumulator_mode=AccumulatorMode.DETERMINISTIC_FP32,
        output_format=WireFormat.FP32,
        element_count=16,
        elements_per_chunk=4,
        max_reduction_terms=1,
        requested_window_chunks=2,
        requested_replay_slots=2,
        timeout_ms=100,
        retry_limit=3,
        result_delivery_role=False,
    )


class ManagerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.switches = {name: FakeSwitchClient(name) for name in ("s0", "l0")}
        self.manager = PrismManager(self.switches)
        self.session = self.manager.open_session(0x1234)
        descriptors = {name: group_descriptor() for name in self.switches}
        self.group = self.manager.create_group(self.session, 7, descriptors)

    def prepare(self, operation_id: int = 9):
        descriptors = {name: operation_descriptor() for name in self.switches}
        return self.manager.prepare_operation(self.group, operation_id, descriptors)

    def test_partial_tree_prepare_rolls_back_and_releases(self) -> None:
        self.switches["l0"].fail_once[ControlCommand.OP_PREPARE] = Status.NO_BITMAP_MEMORY
        with self.assertRaises(PrismError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.status, Status.NO_BITMAP_MEMORY)
        self.assertEqual(self.switches["s0"].calls[ControlCommand.OP_ABORT], 1)
        self.assertEqual(self.switches["s0"].calls[ControlCommand.OP_RELEASE], 1)
        retried = self.prepare()
        self.assertEqual(retried.wire.generation, 2)

    def test_commit_status_recovery_complete_retention_release_and_reuse(self) -> None:
        operation = self.prepare()
        self.switches["s0"].lose_after_apply_once.add(ControlCommand.OP_COMMIT)
        self.manager.commit_operation(operation)
        self.assertEqual(operation.state, OperationState.ACTIVE)
        self.assertGreaterEqual(self.switches["s0"].calls[ControlCommand.OP_STATUS], 1)

        key = (operation.wire.operation_id, operation.wire.generation)
        for switch in self.switches.values():
            switch.operations[key] = OperationState.COMPLETE
        self.manager.wait_operation(operation, timeout_seconds=0.01, poll_seconds=0)
        self.assertTrue(operation.valid)
        self.assertEqual(operation.state, OperationState.COMPLETE)
        with self.assertRaises(PrismError) as busy:
            self.manager.destroy_group(self.group)
        self.assertEqual(busy.exception.status, Status.GROUP_BUSY)
        with self.assertRaises(InvalidHandleError):
            self.prepare(operation.wire.operation_id)

        self.manager.release_operation(operation)
        reused = self.prepare(operation.wire.operation_id)
        self.assertEqual(reused.wire.generation, operation.wire.generation + 1)

    def test_commit_failure_aborts_every_prepared_switch(self) -> None:
        operation = self.prepare()
        self.switches["l0"].fail_once[ControlCommand.OP_COMMIT] = Status.INVALID_STATE
        with self.assertRaises(PrismError):
            self.manager.commit_operation(operation)
        self.assertEqual(operation.state, OperationState.ABORTED)
        for switch in self.switches.values():
            self.assertEqual(switch.calls[ControlCommand.OP_ABORT], 1)

    def test_release_can_be_retried_after_lost_response(self) -> None:
        operation = self.prepare()
        self.manager.abort_operation(operation)
        self.switches["s0"].lose_after_apply_once.add(ControlCommand.OP_RELEASE)
        with self.assertRaises(PrismError):
            self.manager.release_operation(operation)
        self.assertTrue(operation.valid)
        self.manager.release_operation(operation)
        self.assertFalse(operation.valid)

    def test_group_reuse_increments_generation(self) -> None:
        self.manager.destroy_group(self.group)
        descriptors = {name: group_descriptor() for name in self.switches}
        reused = self.manager.create_group(self.session, 7, descriptors)
        self.assertEqual(reused.wire.generation, self.group.wire.generation + 1)
        self.assertEqual(reused.state, GroupState.INSTALLED)

    def test_session_expiry_invalidates_access(self) -> None:
        self.session.lease_deadlines = {name: 0.0 for name in self.switches}
        with self.assertRaises(PrismError) as raised:
            self.manager.query_resources(self.session)
        self.assertEqual(raised.exception.status, Status.STALE_SESSION)
        self.assertFalse(self.session.valid)

    def test_changed_device_boot_id_invalidates_cached_handles(self) -> None:
        switch = self.switches["s0"]
        switch.capabilities = replace(switch.capabilities, device_boot_id=switch.capabilities.device_boot_id + 1)
        with self.assertRaises(PrismError) as raised:
            self.manager.query_capabilities(("s0",))
        self.assertEqual(raised.exception.status, Status.STALE_DEVICE_BOOT_ID)
        self.assertFalse(self.session.valid)
        self.assertFalse(self.group.valid)


if __name__ == "__main__":
    unittest.main()
