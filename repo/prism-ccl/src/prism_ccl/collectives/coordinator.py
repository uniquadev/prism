"""Host/runtime coordination layered above the PRISM Aggregation Manager.

This module intentionally defines no wire messages.  A deployment may keep the
host coordinator and :class:`~prism_ccl.collectives.control.PrismManager` in one process
or connect them through an RPC transport.  In either case, rank start grants are
host-control-plane objects and are published only after the AM has committed the
operation on the complete switch tree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Protocol

from ..protocol.constants import (
    AccumulatorProfile,
    CollectiveSemantic,
    NextHopType,
    NodeRole,
    OperationState,
    ReductionOperator,
    WireFormat,
)
from ..protocol.errors import InvalidHandleError
from ..protocol.models import OperationDescriptor
from .control import CollectiveGroupHandle, CollectiveOperationHandle


class AggregationManager(Protocol):
    """The AM operations required by the host coordinator.

    ``PrismManager`` implements this protocol directly.  The narrow interface
    also permits a future RPC proxy without coupling rank coordination to the
    PRISM Ethernet wire ABI.
    """

    def prepare_operation(
        self,
        group: CollectiveGroupHandle,
        operation_id: int,
        descriptors: Mapping[str, OperationDescriptor],
        *,
        parent_edges: Mapping[str, str] | None = None,
    ) -> CollectiveOperationHandle: ...

    def commit_operation(self, operation: CollectiveOperationHandle) -> None: ...

    def abort_operation(self, operation: CollectiveOperationHandle) -> None: ...

    def wait_operation(
        self,
        operation: CollectiveOperationHandle,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Mapping[str, OperationState]: ...

    def release_operation(self, operation: CollectiveOperationHandle) -> None: ...


@dataclass(frozen=True, slots=True)
class RankBinding:
    """Host-side assignment of one application rank to one leaf contributor."""

    rank_id: int
    leaf_switch_id: str
    contributor_id: int
    leaf_destination_mac: bytes
    result_destination_mac: bytes


@dataclass(frozen=True, slots=True)
class RankStartGrant:
    """Information a runtime gives one rank before its first DATA packet.

    The identity fields prevent a rank from using a stale collective instance;
    the geometry fields ensure every rank constructs the same chunk intervals.
    ``admitted_window_chunks`` is the leaf's actual grant, which can be smaller
    than the window requested by the operation descriptor.
    """

    rank_id: int
    job_id: int
    group_id: int
    group_generation: int
    operation_id: int
    operation_generation: int
    leaf_switch_id: str
    destination_mac: bytes
    result_destination_mac: bytes
    contributor_id: int
    ingress_port: int
    source_mac: bytes
    semantic: CollectiveSemantic
    reduction_operator: ReductionOperator
    input_format: WireFormat
    output_format: WireFormat
    accumulator_profile: AccumulatorProfile
    element_count: int
    input_elements_per_chunk: int
    input_expected_chunks: int
    output_elements_per_chunk: int
    output_expected_chunks: int
    admitted_window_chunks: int


class HostOperationState(Enum):
    """Lifecycle of a host-side collective request, outside the wire ABI."""

    WAITING_FOR_RANKS = "waiting_for_ranks"
    CONFIGURING_SWITCHES = "configuring_switches"
    ACTIVE = "active"
    COMPLETE = "complete"
    RELEASED = "released"
    FAILED = "failed"


@dataclass(slots=True, eq=False)
class HostCollectiveOperation:
    """One host barrier and its eventual AM operation."""

    group: CollectiveGroupHandle
    operation_id: int
    descriptors: dict[str, OperationDescriptor]
    rank_bindings: dict[int, RankBinding]
    parent_edges: dict[str, str]
    reduce_root_rank_id: int | None
    state: HostOperationState = HostOperationState.WAITING_FOR_RANKS
    arrived_rank_ids: set[int] = field(default_factory=set)
    am_operation: CollectiveOperationHandle | None = None
    failure: Exception | None = None
    cleanup_failure: Exception | None = None
    _start_grants: dict[int, RankStartGrant] = field(default_factory=dict, repr=False)

    @property
    def pending_rank_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self.rank_bindings.keys() - self.arrived_rank_ids))


class PrismHostCoordinator:
    """SHARP-like host coordinator placed logically above the AM.

    Rank-arrival messages are expected to reach this object through the host
    runtime's own channel.  The final arrival causes the coordinator to ask the
    AM to prepare and commit the whole switch tree.  Start grants become visible
    atomically only if that global commit succeeds.
    """

    def __init__(self, manager: AggregationManager) -> None:
        self.manager = manager
        self.operations: list[HostCollectiveOperation] = []
        self._lock = RLock()

    def create_operation(
        self,
        group: CollectiveGroupHandle,
        operation_id: int,
        descriptors: Mapping[str, OperationDescriptor],
        rank_bindings: Iterable[RankBinding],
        *,
        reduce_root_rank_id: int | None = None,
        parent_edges: Mapping[str, str] | None = None,
    ) -> HostCollectiveOperation:
        """Create a local barrier without contacting any switch."""

        with self._lock:
            if not group.valid:
                raise InvalidHandleError("group handle is invalid")
            if not 0 <= operation_id < (1 << 16):
                raise ValueError("operation_id exceeds the 16-bit wire field")
            if set(descriptors) != set(group.switch_ids):
                raise ValueError("operation descriptors must cover the complete group tree")
            if any(
                item.group is group
                and item.operation_id == operation_id
                and (
                    item.state
                    in (
                        HostOperationState.WAITING_FOR_RANKS,
                        HostOperationState.CONFIGURING_SWITCHES,
                    )
                    or (item.am_operation is not None and item.am_operation.valid)
                )
                for item in self.operations
            ):
                raise InvalidHandleError(
                    "host operation already exists for this group and Operation ID"
                )

            bindings = self._validate_rank_bindings(group, rank_bindings)
            edges = dict(parent_edges or {})
            self._validate_result_delivery(
                group,
                descriptors,
                bindings,
                edges,
                reduce_root_rank_id,
            )
            operation = HostCollectiveOperation(
                group=group,
                operation_id=operation_id,
                descriptors=dict(descriptors),
                rank_bindings=bindings,
                parent_edges=edges,
                reduce_root_rank_id=reduce_root_rank_id,
            )
            self.operations.append(operation)
            return operation

    def rank_arrive(self, operation: HostCollectiveOperation, rank_id: int) -> bool:
        """Record one rank at the barrier.

        Returns ``True`` only for the arrival that successfully activates the
        operation.  Repeated arrivals are idempotent.  An AM failure is raised to
        the runtime and leaves the operation in ``FAILED`` with no start grants.
        """

        with self._lock:
            self._require_operation(operation)
            if rank_id not in operation.rank_bindings:
                raise ValueError(f"rank {rank_id} is not a participant in this operation")
            if operation.state is HostOperationState.FAILED:
                self._raise_failure(operation)
            if (
                operation.state is HostOperationState.ACTIVE
                or rank_id in operation.arrived_rank_ids
            ):
                return False

            operation.arrived_rank_ids.add(rank_id)
            if operation.pending_rank_ids:
                return False

            self._activate(operation)
            return True

    def start_grants(self, operation: HostCollectiveOperation) -> tuple[RankStartGrant, ...]:
        """Return the grants ready for delivery, or an empty tuple before ACTIVE."""

        with self._lock:
            self._require_operation(operation)
            if operation.state is HostOperationState.FAILED:
                self._raise_failure(operation)
            if not self._grants_are_live(operation):
                return ()
            return tuple(
                operation._start_grants[rank_id] for rank_id in sorted(operation._start_grants)
            )

    def start_grant_for_rank(
        self,
        operation: HostCollectiveOperation,
        rank_id: int,
    ) -> RankStartGrant | None:
        """Return one rank's grant; ``None`` means the global barrier is not ready."""

        with self._lock:
            self._require_operation(operation)
            if rank_id not in operation.rank_bindings:
                raise ValueError(f"rank {rank_id} is not a participant in this operation")
            if operation.state is HostOperationState.FAILED:
                self._raise_failure(operation)
            if not self._grants_are_live(operation):
                return None
            return operation._start_grants[rank_id]

    def wait_operation(
        self,
        operation: HostCollectiveOperation,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Mapping[str, OperationState]:
        """Wait for tree-wide completion and retire every published start grant."""

        with self._lock:
            self._require_operation(operation)
            if operation.state is HostOperationState.FAILED:
                self._raise_failure(operation)
            if operation.state is not HostOperationState.ACTIVE or operation.am_operation is None:
                raise InvalidHandleError("host operation is not ACTIVE")
            try:
                states = self.manager.wait_operation(
                    operation.am_operation,
                    timeout_seconds=timeout_seconds,
                    poll_seconds=poll_seconds,
                )
            except Exception as exc:
                if operation.am_operation.state is OperationState.ABORTED:
                    operation._start_grants.clear()
                    operation.failure = exc
                    operation.state = HostOperationState.FAILED
                raise
            if operation.am_operation.state is not OperationState.COMPLETE:
                raise InvalidHandleError("AM returned from wait without a COMPLETE operation")
            operation._start_grants.clear()
            operation.state = HostOperationState.COMPLETE
            return states

    def release_operation(self, operation: HostCollectiveOperation) -> None:
        """Release a completed operation or retry cleanup after failed startup."""

        with self._lock:
            self._require_operation(operation)
            am_operation = operation.am_operation
            if am_operation is None or not am_operation.valid:
                if operation.state is HostOperationState.FAILED:
                    return
                raise InvalidHandleError("host operation has no releasable AM handle")
            if operation.state not in (HostOperationState.COMPLETE, HostOperationState.FAILED):
                raise InvalidHandleError(
                    "host operation may be released only after COMPLETE or FAILED"
                )
            self.manager.release_operation(am_operation)
            operation._start_grants.clear()
            operation.cleanup_failure = None
            if operation.state is HostOperationState.COMPLETE:
                operation.state = HostOperationState.RELEASED

    def _activate(self, operation: HostCollectiveOperation) -> None:
        operation.state = HostOperationState.CONFIGURING_SWITCHES
        am_operation: CollectiveOperationHandle | None = None
        try:
            am_operation = self.manager.prepare_operation(
                operation.group,
                operation.operation_id,
                operation.descriptors,
                parent_edges=operation.parent_edges,
            )
            operation.am_operation = am_operation
            candidate_grants = self._build_start_grants(operation, am_operation)
            self.manager.commit_operation(am_operation)
            if am_operation.state is not OperationState.ACTIVE:
                raise InvalidHandleError("AM returned from commit without an ACTIVE operation")
        except Exception as exc:
            if am_operation is not None:
                try:
                    if am_operation.state is OperationState.PREPARED:
                        self.manager.abort_operation(am_operation)
                    if am_operation.state in (OperationState.ABORTED, OperationState.COMPLETE):
                        self.manager.release_operation(am_operation)
                except Exception as cleanup_exc:
                    operation.cleanup_failure = cleanup_exc
            operation._start_grants.clear()
            operation.failure = exc
            operation.state = HostOperationState.FAILED
            raise

        # This assignment is the publication point.  No rank can observe a
        # partial grant set or a grant for a merely PREPARED switch tree.
        operation._start_grants = candidate_grants
        operation.state = HostOperationState.ACTIVE

    @staticmethod
    def _build_start_grants(
        operation: HostCollectiveOperation,
        am_operation: CollectiveOperationHandle,
    ) -> dict[int, RankStartGrant]:
        grants: dict[int, RankStartGrant] = {}
        group = operation.group
        for rank_id, rank in operation.rank_bindings.items():
            group_descriptor = group.descriptors[rank.leaf_switch_id]
            contributor = group_descriptor.contributors[rank.contributor_id]
            descriptor = operation.descriptors[rank.leaf_switch_id]
            admitted_window = am_operation.granted_resources[rank.leaf_switch_id].accumulator_ranges
            if admitted_window <= 0:
                raise InvalidHandleError(
                    "AM granted no receive-window slots to a participating leaf"
                )
            grants[rank_id] = RankStartGrant(
                rank_id=rank_id,
                job_id=group.session.job_id,
                group_id=group.wire.group_id,
                group_generation=group.wire.generation,
                operation_id=am_operation.wire.operation_id,
                operation_generation=am_operation.wire.generation,
                leaf_switch_id=rank.leaf_switch_id,
                destination_mac=rank.leaf_destination_mac,
                result_destination_mac=rank.result_destination_mac,
                contributor_id=rank.contributor_id,
                ingress_port=contributor.ingress_port,
                source_mac=contributor.source_mac,
                semantic=descriptor.semantic,
                reduction_operator=descriptor.reduction_operator,
                input_format=descriptor.input_format,
                output_format=descriptor.output_format,
                accumulator_profile=descriptor.accumulator_profile,
                element_count=descriptor.element_count,
                input_elements_per_chunk=descriptor.input_elements_per_chunk,
                input_expected_chunks=descriptor.input_expected_chunks,
                output_elements_per_chunk=descriptor.output_elements_per_chunk,
                output_expected_chunks=descriptor.expected_chunks,
                admitted_window_chunks=admitted_window,
            )
        return grants

    @staticmethod
    def _validate_rank_bindings(
        group: CollectiveGroupHandle,
        rank_bindings: Iterable[RankBinding],
    ) -> dict[int, RankBinding]:
        bindings = tuple(rank_bindings)
        if not bindings:
            raise ValueError("at least one rank binding is required")
        by_rank: dict[int, RankBinding] = {}
        assigned_contributors: set[tuple[str, int]] = set()
        for binding in bindings:
            if binding.rank_id < 0:
                raise ValueError("rank_id must be non-negative")
            if binding.rank_id in by_rank:
                raise ValueError("rank_id must be unique")
            if len(binding.leaf_destination_mac) != 6:
                raise ValueError("leaf destination MAC must be exactly 6 bytes")
            if len(binding.result_destination_mac) != 6:
                raise ValueError("rank result destination MAC must be exactly 6 bytes")
            if binding.leaf_switch_id not in group.descriptors:
                raise ValueError("rank binding references an unknown switch")
            descriptor = group.descriptors[binding.leaf_switch_id]
            if descriptor.node_role not in (NodeRole.LEAF, NodeRole.SINGLE):
                raise ValueError("application ranks may bind only to LEAF or SINGLE nodes")
            if not 0 <= binding.contributor_id < descriptor.expected_local_contributors:
                raise ValueError(
                    "rank binding Contributor ID is outside the leaf's dense local range"
                )
            contributor_key = (binding.leaf_switch_id, binding.contributor_id)
            if contributor_key in assigned_contributors:
                raise ValueError("a leaf Contributor ID may be assigned to only one rank")
            by_rank[binding.rank_id] = binding
            assigned_contributors.add(contributor_key)

        expected_contributors = {
            (switch_id, contributor_id)
            for switch_id, descriptor in group.descriptors.items()
            if descriptor.node_role in (NodeRole.LEAF, NodeRole.SINGLE)
            for contributor_id in range(descriptor.expected_local_contributors)
        }
        if assigned_contributors != expected_contributors:
            raise ValueError(
                "rank bindings must cover every configured leaf contributor exactly once"
            )
        return by_rank

    @staticmethod
    def _validate_result_delivery(
        group: CollectiveGroupHandle,
        descriptors: Mapping[str, OperationDescriptor],
        bindings: Mapping[int, RankBinding],
        parent_edges: Mapping[str, str],
        reduce_root_rank_id: int | None,
    ) -> None:
        switch_ids = set(group.switch_ids)
        if set(descriptors) != switch_ids:
            raise ValueError("operation descriptors must cover the complete group tree")

        semantic_values = {descriptor.semantic for descriptor in descriptors.values()}
        operator_values = {descriptor.reduction_operator for descriptor in descriptors.values()}
        if len(semantic_values) != 1 or len(operator_values) != 1:
            raise ValueError("all switches must use one collective semantic and reduction operator")
        semantic = next(iter(semantic_values))
        if semantic not in (CollectiveSemantic.REDUCE, CollectiveSemantic.ALLREDUCE):
            raise ValueError("the Protocol 1.0 host coordinator supports REDUCE and ALLREDUCE")
        if semantic is CollectiveSemantic.REDUCE:
            if reduce_root_rank_id not in bindings:
                raise ValueError("REDUCE requires one participating reduce_root_rank_id")
            expected_destinations = {reduce_root_rank_id}
        else:
            if reduce_root_rank_id is not None:
                raise ValueError("ALLREDUCE must not specify a reduce_root_rank_id")
            expected_destinations = set(bindings)

        if len(switch_ids) == 1:
            root = next(iter(switch_ids))
            if parent_edges:
                raise ValueError("a SINGLE-node operation must not contain parent edges")
        else:
            roots = [
                switch_id
                for switch_id, descriptor in group.descriptors.items()
                if descriptor.node_role is NodeRole.ROOT
            ]
            if len(roots) != 1:
                raise ValueError("result validation requires exactly one ROOT switch")
            root = roots[0]
            if set(parent_edges) != switch_ids - {root}:
                raise ValueError(
                    "result validation requires one parent edge for every non-root switch"
                )

        rank_by_destination: dict[tuple[str, bytes], int] = {}
        all_rank_destination_macs: set[bytes] = set()
        switch_mac_candidates: dict[str, set[bytes]] = {
            switch_id: set() for switch_id in switch_ids
        }
        for rank_id, binding in bindings.items():
            key = (binding.leaf_switch_id, binding.result_destination_mac)
            if key in rank_by_destination:
                raise ValueError("rank result destination MAC must be unique on its leaf")
            if binding.result_destination_mac in all_rank_destination_macs:
                raise ValueError("rank result destination MACs must be unique across the operation")
            rank_by_destination[key] = rank_id
            all_rank_destination_macs.add(binding.result_destination_mac)
            switch_mac_candidates[binding.leaf_switch_id].add(binding.leaf_destination_mac)
        for child, parent in parent_edges.items():
            if child not in switch_ids or parent not in switch_ids or child == parent:
                raise ValueError("parent edge references an invalid switch")
            switch_mac_candidates[parent].add(group.descriptors[child].upstream.parent_mac)

        switch_by_mac: dict[bytes, str] = {}
        for switch_id, candidates in switch_mac_candidates.items():
            if not candidates:
                raise ValueError("each switch needs at least one known PRISM termination MAC")
            for mac in candidates:
                owner = switch_by_mac.setdefault(mac, switch_id)
                if owner != switch_id:
                    raise ValueError("a PRISM termination MAC cannot belong to two switches")

        route_points = {0}
        for descriptor in descriptors.values():
            descriptor.validate()
            route_points.update(route.chunk_first for route in descriptor.result_range_routes)
            route_points.update(route.chunk_last for route in descriptor.result_range_routes)

        replication = {
            switch_id: {
                item.group_id: item for item in group.descriptors[switch_id].replication_groups
            }
            for switch_id in switch_ids
        }

        def destinations(switch_id: str, chunk: int, visited: frozenset[str]) -> list[int]:
            if switch_id in visited:
                raise ValueError("result routes contain a switch cycle")
            descriptor = descriptors[switch_id]
            matches = [
                route
                for route in descriptor.result_range_routes
                if route.chunk_first <= chunk <= route.chunk_last
            ]
            if not descriptor.result_delivery_role or len(matches) != 1:
                raise ValueError("every traversed result switch needs exactly one route per chunk")
            group_id = matches[0].replication_group_id
            action = replication[switch_id].get(group_id)
            if action is None:
                raise ValueError("result route references an unknown local replication group")

            result: list[int] = []
            for entry in action.entries:
                if entry.next_hop_type is NextHopType.RANK:
                    rank_id = rank_by_destination.get((switch_id, entry.dst_mac))
                    if rank_id is None:
                        raise ValueError("result route targets an unknown or non-local rank MAC")
                    result.append(rank_id)
                elif entry.next_hop_type is NextHopType.SWITCH:
                    child = switch_by_mac.get(entry.dst_mac)
                    if child is None or parent_edges.get(child) != switch_id:
                        raise ValueError(
                            "result route targets a switch that is not a configured child"
                        )
                    result.extend(destinations(child, chunk, visited | {switch_id}))
                else:
                    raise ValueError("result route uses an unsupported next-hop type")
            return result

        for chunk in route_points:
            delivered = destinations(root, chunk, frozenset())
            if len(delivered) != len(set(delivered)):
                raise ValueError("a result chunk reaches the same rank more than once")
            if set(delivered) != expected_destinations:
                raise ValueError("result routes do not match the collective participant semantics")

    @staticmethod
    def _grants_are_live(operation: HostCollectiveOperation) -> bool:
        return (
            operation.state is HostOperationState.ACTIVE
            and operation.am_operation is not None
            and operation.am_operation.valid
            and operation.am_operation.state is OperationState.ACTIVE
        )

    @staticmethod
    def _raise_failure(operation: HostCollectiveOperation) -> None:
        if operation.failure is not None:
            raise operation.failure
        raise InvalidHandleError("host operation failed")

    def _require_operation(self, operation: HostCollectiveOperation) -> None:
        if operation not in self.operations:
            raise InvalidHandleError("host operation does not belong to this coordinator")
