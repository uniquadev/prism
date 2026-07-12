"""Transport-neutral PRISM 1.0 switch client and multi-switch AM helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol

from .constants import (
    CHUNK_PAYLOAD_BYTES,
    RESPONSE_FOR,
    VERSION_MAJOR,
    VERSION_MINOR,
    ControlCommand,
    ControlFlag,
    FeatureFlag,
    GroupState,
    NodeRole,
    OperationState,
    SecurityProfile,
    Status,
    TlvType,
)
from .errors import InvalidHandleError, PrismError, ProtocolDecodeError
from .model import (
    Capabilities,
    GenerationStore,
    GroupDescriptor,
    OperationDescriptor,
    ResourceAllocation,
    ResourceSnapshot,
    group_handle_tlv,
    operation_handle_tlv,
)
from .wire import (
    ControlFrame,
    ControlHeader,
    ControlReassembler,
    GroupHandleWire,
    OperationHandleWire,
    ProtocolVersionRange,
    Tlv,
    pack_tlvs,
    parse_tlvs,
    validate_tlv_schema,
)


class ControlTransport(Protocol):
    """Deployment-specific management transport; raw sockets are intentionally absent."""

    def exchange(self, frames: tuple[bytes, ...], timeout_seconds: float) -> tuple[bytes, ...]: ...


@dataclass(frozen=True, slots=True)
class ControlResponse:
    header: ControlHeader
    tlvs: tuple[Tlv, ...]


class SwitchControlClient(Protocol):
    switch_id: str

    def call(
        self,
        command: ControlCommand,
        tlvs: Iterable[Tlv] = (),
        *,
        session_cookie: int = 0,
        transaction_id: int | None = None,
    ) -> ControlResponse: ...


class WireSwitchClient:
    def __init__(
        self,
        switch_id: str,
        transport: ControlTransport,
        *,
        timeout_seconds: float = 1.0,
        retries: int = 3,
        max_fragment_payload: int = CHUNK_PAYLOAD_BYTES,
        max_response_bytes: int = 1 << 20,
    ) -> None:
        self.switch_id = switch_id
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.max_fragment_payload = max_fragment_payload
        self.max_response_bytes = max_response_bytes
        self._next_transaction_id = 1

    def call(
        self,
        command: ControlCommand,
        tlvs: Iterable[Tlv] = (),
        *,
        session_cookie: int = 0,
        transaction_id: int | None = None,
    ) -> ControlResponse:
        transaction_id = self._allocate_transaction_id() if transaction_id is None else transaction_id
        payload = pack_tlvs(tuple(tlvs))
        fragments = self._fragment_request(command, session_cookie, transaction_id, payload)
        last_error: Exception | None = None
        for _attempt in range(self.retries + 1):
            try:
                response_frames = self.transport.exchange(fragments, self.timeout_seconds)
                return self._parse_response(command, session_cookie, transaction_id, response_frames)
            except TimeoutError as exc:
                last_error = exc
                continue
        raise PrismError(Status.TIMEOUT, f"no response after {self.retries + 1} attempts", self.switch_id, transaction_id) from last_error

    def _fragment_request(
        self,
        command: ControlCommand,
        session_cookie: int,
        transaction_id: int,
        payload: bytes,
    ) -> tuple[bytes, ...]:
        if self.max_fragment_payload <= 0:
            raise ValueError("max_fragment_payload must be positive")
        parts = tuple(
            payload[offset : offset + self.max_fragment_payload]
            for offset in range(0, len(payload), self.max_fragment_payload)
        ) or (b"",)
        return tuple(
            ControlFrame(
                ControlHeader(
                    session_cookie,
                    transaction_id,
                    command,
                    ControlFlag.REQUEST | ControlFlag.ACK_REQUIRED,
                    Status.OK,
                    index,
                    len(parts),
                ),
                part,
            ).pack()
            for index, part in enumerate(parts)
        )

    def _parse_response(
        self,
        request_command: ControlCommand,
        request_cookie: int,
        transaction_id: int,
        frames: tuple[bytes, ...],
    ) -> ControlResponse:
        if not frames:
            raise TimeoutError("empty response")
        expected_command = RESPONSE_FOR[request_command]
        reassembler = ControlReassembler(self.max_response_bytes, self.timeout_seconds)
        response_header: ControlHeader | None = None
        response_tlvs: tuple[Tlv, ...] | None = None
        for encoded in frames:
            frame = ControlFrame.unpack(encoded)
            header = frame.header
            if header.transaction_id != transaction_id or header.command != expected_command:
                raise ProtocolDecodeError("response transaction or command mismatch")
            if not header.flags & ControlFlag.RESPONSE:
                raise ProtocolDecodeError("control response lacks RESPONSE flag")
            if request_command not in (ControlCommand.CAPS_QUERY, ControlCommand.SESSION_OPEN):
                if header.session_cookie != request_cookie:
                    raise ProtocolDecodeError("response Session Cookie mismatch")
            response_header = header
            if header.fragment_count == 1:
                parsed = parse_tlvs(frame.payload)
                response_tlvs = validate_tlv_schema(header.command, parsed) if header.status == Status.OK else parsed
            else:
                response_tlvs = reassembler.add(frame)
        if response_header is None or response_tlvs is None:
            raise ProtocolDecodeError("incomplete fragmented response")
        if response_header.status != Status.OK:
            detail = _optional_tlv(response_tlvs, TlvType.ERROR_DETAIL)
            message = detail.value.decode("utf-8", errors="replace") if detail else response_header.status.name
            raise PrismError(response_header.status, message, self.switch_id, transaction_id)
        return ControlResponse(response_header, response_tlvs)

    def _allocate_transaction_id(self) -> int:
        value = self._next_transaction_id
        self._next_transaction_id = (self._next_transaction_id + 1) & ((1 << 64) - 1)
        if self._next_transaction_id == 0:
            self._next_transaction_id = 1
        return value


@dataclass(slots=True)
class SessionHandle:
    job_id: int
    cookies: dict[str, int]
    device_boot_ids: dict[str, int]
    lease_deadlines: dict[str, float]
    valid: bool = True


@dataclass(slots=True)
class CollectiveGroupHandle:
    session: SessionHandle
    wire: GroupHandleWire
    switch_ids: tuple[str, ...]
    descriptors: dict[str, GroupDescriptor]
    reservations: dict[str, ResourceAllocation]
    state: GroupState = GroupState.INSTALLED
    valid: bool = True


@dataclass(slots=True)
class CollectiveOperationHandle:
    group: CollectiveGroupHandle
    wire: OperationHandleWire
    switch_ids: tuple[str, ...]
    descriptors: dict[str, OperationDescriptor]
    granted_resources: dict[str, ResourceAllocation]
    state: OperationState = OperationState.PREPARED
    valid: bool = True


class PrismManager:
    """AM-side switch orchestrator for sessions, groups, and operations."""

    def __init__(
        self,
        clients: Mapping[str, SwitchControlClient],
        *,
        generation_store: GenerationStore | None = None,
    ) -> None:
        if not clients:
            raise ValueError("at least one switch client is required")
        self.clients = dict(clients)
        self.generations = generation_store or GenerationStore()
        self.capabilities: dict[str, Capabilities] = {}
        self.protocol_versions: dict[str, ProtocolVersionRange] = {}
        self.device_boot_ids: dict[str, int] = {}
        self.sessions: list[SessionHandle] = []
        self.groups: list[CollectiveGroupHandle] = []
        self.operations: list[CollectiveOperationHandle] = []

    def query_capabilities(self, switch_ids: Iterable[str] | None = None) -> dict[str, Capabilities]:
        result: dict[str, Capabilities] = {}
        for switch_id in self._switches(switch_ids):
            response = self.clients[switch_id].call(ControlCommand.CAPS_QUERY)
            boot = _required_tlv(response.tlvs, TlvType.DEVICE_BOOT_ID).as_u64()
            version_range = ProtocolVersionRange.unpack(
                _required_tlv(response.tlvs, TlvType.PROTOCOL_VERSION_RANGE).value
            )
            if not version_range.supports(VERSION_MAJOR, VERSION_MINOR):
                raise PrismError(Status.UNSUPPORTED_VERSION, "switch does not support PRISM Protocol 1.0", switch_id)
            capabilities = Capabilities.from_tlv(boot, _required_tlv(response.tlvs, TlvType.CAPABILITIES))
            previous = self.device_boot_ids.get(switch_id)
            if previous is not None and previous != boot:
                self._invalidate_switch(switch_id)
                self.device_boot_ids[switch_id] = boot
                self.capabilities[switch_id] = capabilities
                raise PrismError(Status.STALE_DEVICE_BOOT_ID, "Device Boot ID changed", switch_id)
            self.device_boot_ids[switch_id] = boot
            self.capabilities[switch_id] = capabilities
            self.protocol_versions[switch_id] = version_range
            result[switch_id] = capabilities
        return result

    def open_session(
        self,
        job_id: int,
        *,
        switch_ids: Iterable[str] | None = None,
        security_profile: SecurityProfile = SecurityProfile.LAB_UNAUTHENTICATED,
        lease_ms: int = 30_000,
        auth_data: bytes | None = None,
    ) -> SessionHandle:
        targets = self._switches(switch_ids)
        self.query_capabilities(targets)
        for switch_id in targets:
            if security_profile not in self.capabilities[switch_id].security_profiles:
                raise PrismError(Status.UNSUPPORTED_FEATURE, "security profile is not supported", switch_id)
        cookies: dict[str, int] = {}
        boots: dict[str, int] = {}
        deadlines: dict[str, float] = {}
        opened: list[str] = []
        try:
            for switch_id in targets:
                tlvs = [
                    Tlv.u64(TlvType.JOB_ID, job_id),
                    Tlv.u64(TlvType.SECURITY_PROFILE, int(security_profile)),
                    Tlv.u64(TlvType.LEASE_MS, lease_ms),
                ]
                if auth_data is not None:
                    tlvs.append(Tlv(TlvType.AUTH_DATA, auth_data))
                response = self.clients[switch_id].call(ControlCommand.SESSION_OPEN, tlvs)
                cookie = _required_tlv(response.tlvs, TlvType.SESSION_COOKIE).as_u64()
                boot = _required_tlv(response.tlvs, TlvType.DEVICE_BOOT_ID).as_u64()
                granted_lease = _required_tlv(response.tlvs, TlvType.LEASE_MS).as_u64()
                cookies[switch_id] = cookie
                boots[switch_id] = boot
                deadlines[switch_id] = time.monotonic() + granted_lease / 1000
                opened.append(switch_id)
        except Exception:
            for switch_id in opened:
                try:
                    self.clients[switch_id].call(ControlCommand.SESSION_CLOSE, session_cookie=cookies[switch_id])
                except Exception:
                    pass
            raise
        session = SessionHandle(job_id, cookies, boots, deadlines)
        self.sessions.append(session)
        return session

    def query_resources(self, session: SessionHandle) -> dict[str, ResourceSnapshot]:
        self._require_session(session)
        result: dict[str, ResourceSnapshot] = {}
        for switch_id, cookie in session.cookies.items():
            response = self.clients[switch_id].call(ControlCommand.RESOURCE_QUERY, session_cookie=cookie)
            result[switch_id] = ResourceSnapshot.from_tlvs(
                _required_tlv(response.tlvs, TlvType.RESOURCE_SNAPSHOT_ID),
                _required_tlv(response.tlvs, TlvType.RESOURCE_SNAPSHOT),
            )
        return result

    def renew_session(self, session: SessionHandle, lease_ms: int = 30_000) -> None:
        self._require_session(session)
        for switch_id, cookie in session.cookies.items():
            response = self.clients[switch_id].call(
                ControlCommand.SESSION_RENEW,
                [Tlv.u64(TlvType.LEASE_MS, lease_ms)],
                session_cookie=cookie,
            )
            granted = _required_tlv(response.tlvs, TlvType.LEASE_MS).as_u64()
            session.lease_deadlines[switch_id] = time.monotonic() + granted / 1000

    def close_session(self, session: SessionHandle) -> None:
        self._require_session(session)
        active = [operation for operation in self.operations if operation.valid and operation.group.session is session]
        for operation in active:
            self.abort_operation(operation)
            self.release_operation(operation)
        for group in [group for group in self.groups if group.valid and group.session is session]:
            self.destroy_group(group)
        for switch_id, cookie in session.cookies.items():
            self.clients[switch_id].call(ControlCommand.SESSION_CLOSE, session_cookie=cookie)
        session.valid = False

    def create_group(
        self,
        session: SessionHandle,
        group_id: int,
        descriptors: Mapping[str, GroupDescriptor],
    ) -> CollectiveGroupHandle:
        self._require_session(session)
        targets = self._validate_descriptor_targets(session, descriptors)
        generation = self.generations.allocate(f"job:{session.job_id}:group", group_id, 16)
        wire = GroupHandleWire(group_id, generation)
        staged: list[str] = []
        committed: list[str] = []
        reservations: dict[str, ResourceAllocation] = {}
        try:
            for switch_id in targets:
                descriptor = descriptors[switch_id]
                self.capabilities[switch_id].validate_group(descriptor)
                response = self.clients[switch_id].call(
                    ControlCommand.GROUP_STAGE,
                    (group_handle_tlv(wire), *descriptor.management_tlvs()),
                    session_cookie=session.cookies[switch_id],
                )
                reservations[switch_id] = ResourceAllocation.from_tlv(
                    _required_tlv(response.tlvs, TlvType.RESOURCE_RESERVATION)
                )
                staged.append(switch_id)
            for switch_id in targets:
                try:
                    response = self.clients[switch_id].call(
                        ControlCommand.GROUP_COMMIT,
                        [group_handle_tlv(wire)],
                        session_cookie=session.cookies[switch_id],
                    )
                except PrismError as commit_error:
                    try:
                        state = self._group_status_one(session, wire, switch_id)
                    except Exception:
                        raise commit_error
                    if state != GroupState.INSTALLED:
                        raise commit_error
                else:
                    state = GroupState(_required_tlv(response.tlvs, TlvType.GROUP_STATUS).as_u64())
                    if state != GroupState.INSTALLED:
                        raise PrismError(
                            Status.INVALID_STATE,
                            f"GROUP_COMMIT returned {state.name}, expected INSTALLED",
                            switch_id,
                        )
                committed.append(switch_id)
        except Exception:
            rollback_complete = True
            for switch_id in reversed(staged):
                try:
                    installed = switch_id in committed
                    if not installed:
                        try:
                            installed = self._group_status_one(session, wire, switch_id) == GroupState.INSTALLED
                        except Exception:
                            pass
                    self.clients[switch_id].call(
                        ControlCommand.GROUP_DESTROY if installed else ControlCommand.GROUP_ABORT,
                        [group_handle_tlv(wire)],
                        session_cookie=session.cookies[switch_id],
                    )
                except Exception:
                    rollback_complete = False
            if rollback_complete:
                self.generations.release(f"job:{session.job_id}:group", group_id)
            raise
        group = CollectiveGroupHandle(session, wire, targets, dict(descriptors), reservations)
        self.groups.append(group)
        return group

    def group_status(self, group: CollectiveGroupHandle) -> dict[str, GroupState]:
        self._require_group(group)
        result: dict[str, GroupState] = {}
        for switch_id in group.switch_ids:
            result[switch_id] = self._group_status_one(group.session, group.wire, switch_id)
        return result

    def destroy_group(self, group: CollectiveGroupHandle) -> None:
        self._require_group(group)
        if any(operation.valid and operation.group is group for operation in self.operations):
            raise PrismError(Status.GROUP_BUSY, "group still owns operations")
        for switch_id in group.switch_ids:
            self.clients[switch_id].call(
                ControlCommand.GROUP_DESTROY,
                [group_handle_tlv(group.wire)],
                session_cookie=group.session.cookies[switch_id],
            )
        self.generations.release(f"job:{group.session.job_id}:group", group.wire.group_id)
        group.state = GroupState.FREE
        group.valid = False

    def prepare_operation(
        self,
        group: CollectiveGroupHandle,
        operation_id: int,
        descriptors: Mapping[str, OperationDescriptor],
        *,
        parent_edges: Mapping[str, str] | None = None,
    ) -> CollectiveOperationHandle:
        self._require_group(group)
        targets = tuple(group.switch_ids)
        if set(descriptors) != set(targets):
            raise ValueError("operation descriptors must cover the complete group tree")
        if any(switch_id not in self.capabilities for switch_id in targets):
            self.query_capabilities(targets)
        self._validate_operation_tree(group.descriptors, descriptors, parent_edges or {})
        for switch_id, descriptor in descriptors.items():
            required_reliability = (
                FeatureFlag.RELIABLE_HOP_BY_HOP | FeatureFlag.SELECTIVE_ACK | FeatureFlag.RESULT_ACK
            )
            if self.capabilities[switch_id].feature_flags & required_reliability != required_reliability:
                raise PrismError(Status.UNSUPPORTED_FEATURE, "mandatory reliable-transfer profile is absent", switch_id)
            self.capabilities[switch_id].validate_operation(descriptor)
        namespace = f"job:{group.session.job_id}:group:{group.wire.group_id}:{group.wire.generation}:operation"
        generation = self.generations.allocate(namespace, operation_id, 32)
        wire = OperationHandleWire(operation_id, generation)
        prepared: list[str] = []
        granted_resources: dict[str, ResourceAllocation] = {}
        try:
            for switch_id in targets:
                descriptor = descriptors[switch_id]
                response = self.clients[switch_id].call(
                    ControlCommand.OP_PREPARE,
                    (
                        group_handle_tlv(group.wire),
                        operation_handle_tlv(wire),
                        *descriptor.management_tlvs(),
                    ),
                    session_cookie=group.session.cookies[switch_id],
                )
                granted_resources[switch_id] = ResourceAllocation.from_tlv(
                    _required_tlv(response.tlvs, TlvType.GRANTED_RESOURCES)
                )
                prepared.append(switch_id)
        except Exception:
            rollback_complete = True
            for switch_id in prepared:
                try:
                    self.clients[switch_id].call(
                        ControlCommand.OP_ABORT,
                        [operation_handle_tlv(wire)],
                        session_cookie=group.session.cookies[switch_id],
                    )
                    self.clients[switch_id].call(
                        ControlCommand.OP_RELEASE,
                        [operation_handle_tlv(wire)],
                        session_cookie=group.session.cookies[switch_id],
                    )
                except Exception:
                    rollback_complete = False
            if rollback_complete:
                self.generations.release(namespace, operation_id)
            raise
        operation = CollectiveOperationHandle(group, wire, targets, dict(descriptors), granted_resources)
        self.operations.append(operation)
        return operation

    def commit_operation(self, operation: CollectiveOperationHandle) -> None:
        self._require_operation(operation)
        if operation.state == OperationState.ACTIVE:
            return
        try:
            for switch_id in operation.switch_ids:
                try:
                    response = self.clients[switch_id].call(
                        ControlCommand.OP_COMMIT,
                        [operation_handle_tlv(operation.wire)],
                        session_cookie=operation.group.session.cookies[switch_id],
                    )
                except PrismError:
                    status = self._operation_status_one(operation, switch_id)
                    if status != OperationState.ACTIVE:
                        raise
                else:
                    state = OperationState(
                        _required_tlv(response.tlvs, TlvType.OPERATION_STATUS).as_u64()
                    )
                    if state != OperationState.ACTIVE:
                        raise PrismError(
                            Status.INVALID_STATE,
                            f"OP_COMMIT returned {state.name}, expected ACTIVE",
                            switch_id,
                        )
        except Exception:
            for switch_id in operation.switch_ids:
                try:
                    self.clients[switch_id].call(
                        ControlCommand.OP_ABORT,
                        [operation_handle_tlv(operation.wire)],
                        session_cookie=operation.group.session.cookies[switch_id],
                    )
                except Exception:
                    pass
            operation.state = OperationState.ABORTED
            raise
        operation.state = OperationState.ACTIVE

    def abort_operation(self, operation: CollectiveOperationHandle) -> None:
        self._require_operation(operation)
        if operation.state == OperationState.ABORTED:
            return
        for switch_id in operation.switch_ids:
            self.clients[switch_id].call(
                ControlCommand.OP_ABORT,
                [operation_handle_tlv(operation.wire)],
                session_cookie=operation.group.session.cookies[switch_id],
            )
        operation.state = OperationState.ABORTED

    def operation_status(self, operation: CollectiveOperationHandle) -> dict[str, OperationState]:
        self._require_operation(operation)
        return {switch_id: self._operation_status_one(operation, switch_id) for switch_id in operation.switch_ids}

    def wait_operation(
        self,
        operation: CollectiveOperationHandle,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> dict[str, OperationState]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            states = self.operation_status(operation)
            if all(state == OperationState.COMPLETE for state in states.values()):
                operation.state = OperationState.COMPLETE
                return states
            if any(state == OperationState.ABORTED for state in states.values()):
                operation.state = OperationState.ABORTED
                raise PrismError(Status.ABORTED, "operation aborted on at least one switch")
            if time.monotonic() >= deadline:
                raise PrismError(Status.TIMEOUT, "operation did not complete before timeout")
            time.sleep(poll_seconds)

    def release_operation(self, operation: CollectiveOperationHandle) -> None:
        self._require_operation(operation)
        if operation.state not in (OperationState.COMPLETE, OperationState.ABORTED):
            raise InvalidHandleError("operation may be released only after COMPLETE or ABORTED")
        for switch_id in operation.switch_ids:
            self.clients[switch_id].call(
                ControlCommand.OP_RELEASE,
                [operation_handle_tlv(operation.wire)],
                session_cookie=operation.group.session.cookies[switch_id],
            )
        namespace = f"job:{operation.group.session.job_id}:group:{operation.group.wire.group_id}:{operation.group.wire.generation}:operation"
        self.generations.release(namespace, operation.wire.operation_id)
        operation.state = OperationState.FREE
        operation.valid = False

    def _operation_status_one(self, operation: CollectiveOperationHandle, switch_id: str) -> OperationState:
        response = self.clients[switch_id].call(
            ControlCommand.OP_STATUS,
            [operation_handle_tlv(operation.wire)],
            session_cookie=operation.group.session.cookies[switch_id],
        )
        return OperationState(_required_tlv(response.tlvs, TlvType.OPERATION_STATUS).as_u64())

    def _group_status_one(
        self,
        session: SessionHandle,
        wire: GroupHandleWire,
        switch_id: str,
    ) -> GroupState:
        response = self.clients[switch_id].call(
            ControlCommand.GROUP_STATUS,
            [group_handle_tlv(wire)],
            session_cookie=session.cookies[switch_id],
        )
        return GroupState(_required_tlv(response.tlvs, TlvType.GROUP_STATUS).as_u64())

    def _switches(self, switch_ids: Iterable[str] | None) -> tuple[str, ...]:
        targets = tuple(self.clients if switch_ids is None else switch_ids)
        if not targets or any(switch_id not in self.clients for switch_id in targets):
            raise ValueError("unknown or empty switch set")
        return targets

    def _validate_descriptor_targets(self, session: SessionHandle, descriptors: Mapping[str, GroupDescriptor]) -> tuple[str, ...]:
        targets = tuple(descriptors)
        if set(targets) != set(session.cookies):
            raise ValueError("group descriptors must cover the complete session tree")
        return targets

    @staticmethod
    def _validate_operation_tree(
        group_descriptors: Mapping[str, GroupDescriptor],
        descriptors: Mapping[str, OperationDescriptor],
        parent_edges: Mapping[str, str],
    ) -> None:
        switch_ids = set(descriptors)
        if set(group_descriptors) != switch_ids:
            raise ValueError("group and operation descriptors must cover the same switch tree")

        geometries = {(item.element_count, item.elements_per_chunk) for item in descriptors.values()}
        if len(geometries) != 1:
            raise ValueError("all operation nodes must use identical element/chunk geometry")

        semantics = {(item.semantic, item.reduction_operator) for item in descriptors.values()}
        if len(semantics) != 1:
            raise ValueError("all operation nodes must use the same collective semantic and operator")

        if len(switch_ids) == 1:
            root = next(iter(switch_ids))
            group = group_descriptors[root]
            if group.node_role != NodeRole.SINGLE or group.upstream.has_parent or parent_edges:
                raise ValueError("a one-switch tree must use one parentless SINGLE node")
        else:
            roots = [
                switch_id
                for switch_id, descriptor in group_descriptors.items()
                if descriptor.node_role == NodeRole.ROOT
            ]
            if len(roots) != 1:
                raise ValueError("a multi-switch tree must contain exactly one ROOT node")
            root = roots[0]
            if group_descriptors[root].upstream.has_parent:
                raise ValueError("the ROOT node must not have a parent action")
            if set(parent_edges) != switch_ids - {root}:
                raise ValueError("parent edges must cover every non-root switch exactly once")

            for switch_id, group in group_descriptors.items():
                if switch_id == root:
                    continue
                if group.node_role not in (NodeRole.LEAF, NodeRole.INTERNAL):
                    raise ValueError("non-root nodes must be LEAF or INTERNAL")
                if not group.upstream.has_parent:
                    raise ValueError("every non-root node must have a parent action")

        for child, parent in parent_edges.items():
            if child not in switch_ids or parent not in switch_ids:
                raise ValueError("parent edge references an unknown switch")
            if child == parent:
                raise ValueError("a switch cannot be its own parent")
            if group_descriptors[parent].node_role not in (NodeRole.INTERNAL, NodeRole.ROOT):
                raise ValueError("a parent switch must be INTERNAL or ROOT")

            visited = {child}
            current = parent
            while current != root:
                if current in visited or current not in parent_edges:
                    raise ValueError("parent edges must form one acyclic tree rooted at ROOT")
                visited.add(current)
                current = parent_edges[current]

        if len(switch_ids) > 1:
            for switch_id, group in group_descriptors.items():
                if group.node_role not in (NodeRole.INTERNAL, NodeRole.ROOT):
                    continue
                child_count = sum(parent == switch_id for parent in parent_edges.values())
                if child_count != group.expected_local_contributors:
                    raise ValueError("INTERNAL/ROOT contributor count must equal its child-subtree count")

        arithmetic_tuple = descriptors[root].arithmetic_tuple
        if any(item.arithmetic_tuple != arithmetic_tuple for item in descriptors.values()):
            raise ValueError("Protocol 1.0 requires one tree-wide arithmetic tuple")

        for switch_id, descriptor in descriptors.items():
            group_ids = {group.group_id for group in group_descriptors[switch_id].replication_groups}
            if any(route.replication_group_id not in group_ids for route in descriptor.result_routes):
                raise ValueError("result route references an unknown local replication group")

    @staticmethod
    def _require_session(session: SessionHandle) -> None:
        if not session.valid:
            raise InvalidHandleError("session handle is invalid")
        if any(time.monotonic() >= deadline for deadline in session.lease_deadlines.values()):
            session.valid = False
            raise PrismError(Status.STALE_SESSION, "session lease expired")

    @staticmethod
    def _require_group(group: CollectiveGroupHandle) -> None:
        PrismManager._require_session(group.session)
        if not group.valid:
            raise InvalidHandleError("group handle is invalid")

    @staticmethod
    def _require_operation(operation: CollectiveOperationHandle) -> None:
        PrismManager._require_group(operation.group)
        if not operation.valid:
            raise InvalidHandleError("operation handle is invalid")

    def _invalidate_switch(self, switch_id: str) -> None:
        for session in self.sessions:
            if switch_id in session.cookies:
                session.valid = False
        for group in self.groups:
            if switch_id in group.switch_ids:
                group.valid = False
        for operation in self.operations:
            if switch_id in operation.switch_ids:
                operation.valid = False


def _required_tlv(tlvs: Iterable[Tlv], type_: TlvType) -> Tlv:
    matches = [tlv for tlv in tlvs if tlv.type == type_]
    if len(matches) != 1:
        raise ProtocolDecodeError(f"expected exactly one {type_.name} TLV")
    return matches[0]


def _optional_tlv(tlvs: Iterable[Tlv], type_: TlvType) -> Tlv | None:
    matches = [tlv for tlv in tlvs if tlv.type == type_]
    if len(matches) > 1:
        raise ProtocolDecodeError(f"duplicate {type_.name} TLV")
    return matches[0] if matches else None


def prism_query_capabilities(manager: PrismManager, *args, **kwargs):
    return manager.query_capabilities(*args, **kwargs)


def prism_open_session(manager: PrismManager, *args, **kwargs):
    return manager.open_session(*args, **kwargs)


def prism_query_resources(manager: PrismManager, *args, **kwargs):
    return manager.query_resources(*args, **kwargs)


def prism_renew_session(manager: PrismManager, *args, **kwargs):
    return manager.renew_session(*args, **kwargs)


def prism_close_session(manager: PrismManager, *args, **kwargs):
    return manager.close_session(*args, **kwargs)


def prism_create_group(manager: PrismManager, *args, **kwargs):
    return manager.create_group(*args, **kwargs)


def prism_group_status(manager: PrismManager, *args, **kwargs):
    return manager.group_status(*args, **kwargs)


def prism_destroy_group(manager: PrismManager, *args, **kwargs):
    return manager.destroy_group(*args, **kwargs)


def prism_prepare_operation(manager: PrismManager, *args, **kwargs):
    return manager.prepare_operation(*args, **kwargs)


def prism_commit_operation(manager: PrismManager, *args, **kwargs):
    return manager.commit_operation(*args, **kwargs)


def prism_abort_operation(manager: PrismManager, *args, **kwargs):
    return manager.abort_operation(*args, **kwargs)


def prism_operation_status(manager: PrismManager, *args, **kwargs):
    return manager.operation_status(*args, **kwargs)


def prism_wait_operation(manager: PrismManager, *args, **kwargs):
    return manager.wait_operation(*args, **kwargs)


def prism_release_operation(manager: PrismManager, *args, **kwargs):
    return manager.release_operation(*args, **kwargs)
