from __future__ import annotations

from collections import Counter

from prism_protocol.client import ControlResponse
from prism_protocol.constants import (
    RESPONSE_FOR,
    ControlCommand,
    ControlFlag,
    GroupState,
    OperationState,
    Status,
    TlvType,
)
from prism_protocol.errors import PrismError
from prism_protocol.model import (
    Capabilities,
    ContributorBinding,
    GroupDescriptor,
    OperationDescriptor,
    ReplicationGroup,
    ResourceAllocation,
    ResourcePool,
    ResultRoute,
    UpstreamAction,
    group_handle_tlv,
    operation_handle_tlv,
)
from prism_protocol.wire import ControlHeader, GroupHandleWire, OperationHandleWire, ProtocolVersionRange, Tlv


class FakeSwitchClient:
    def __init__(self, switch_id: str, capabilities: Capabilities | None = None) -> None:
        self.switch_id = switch_id
        self.capabilities = capabilities or Capabilities.reference(device_boot_id=hash(switch_id) & ((1 << 64) - 1))
        self.pool = ResourcePool(self.capabilities)
        self.cookie = (hash((switch_id, "cookie")) & ((1 << 64) - 1)) or 1
        self.groups: dict[tuple[int, int], GroupState] = {}
        self.operations: dict[tuple[int, int], OperationState] = {}
        self.operation_groups: dict[tuple[int, int], GroupHandleWire] = {}
        self.calls: Counter[ControlCommand] = Counter()
        self.fail_once: dict[ControlCommand, Status] = {}
        self.lose_after_apply_once: set[ControlCommand] = set()
        self.reported_state_once: dict[ControlCommand, int] = {}

    def call(
        self,
        command: ControlCommand,
        tlvs=(),
        *,
        session_cookie: int = 0,
        transaction_id: int | None = None,
    ) -> ControlResponse:
        tlvs = tuple(tlvs)
        self.calls[command] += 1
        failure = self.fail_once.pop(command, None)
        if failure is not None:
            raise PrismError(failure, f"injected {command.name} failure", self.switch_id)

        response_tlvs: tuple[Tlv, ...]
        if command == ControlCommand.CAPS_QUERY:
            response_tlvs = (
                Tlv.u64(TlvType.DEVICE_BOOT_ID, self.capabilities.device_boot_id),
                Tlv(TlvType.PROTOCOL_VERSION_RANGE, ProtocolVersionRange(1, 0, 1, 0).pack()),
                self.capabilities.to_tlv(),
            )
        elif command == ControlCommand.RESOURCE_QUERY:
            response_tlvs = self.pool.snapshot().to_tlvs()
        elif command == ControlCommand.SESSION_OPEN:
            response_tlvs = (
                Tlv.u64(TlvType.SESSION_COOKIE, self.cookie),
                Tlv.u64(TlvType.DEVICE_BOOT_ID, self.capabilities.device_boot_id),
                Tlv.u64(TlvType.LEASE_MS, 30_000),
                Tlv.u64(TlvType.LEASE_GRACE_MS, 5_000),
            )
        elif command == ControlCommand.SESSION_RENEW:
            response_tlvs = (Tlv.u64(TlvType.LEASE_MS, 30_000),)
        elif command == ControlCommand.SESSION_CLOSE:
            response_tlvs = ()
        elif command == ControlCommand.GROUP_STAGE:
            handle = GroupHandleWire.unpack(_one(tlvs, TlvType.GROUP_HANDLE).value)
            key = (handle.group_id, handle.generation)
            descriptor = GroupDescriptor.unpack_descriptor(
                _one(tlvs, TlvType.GROUP_DESCRIPTOR).value,
                (ContributorBinding.unpack(item.value) for item in tlvs if item.type == TlvType.CONTRIBUTOR_BINDING),
                UpstreamAction.unpack(_one(tlvs, TlvType.UPSTREAM_ACTION).value),
                (ReplicationGroup.unpack(item.value) for item in tlvs if item.type == TlvType.REPLICATION_GROUP),
            )
            reservation = self.pool.stage_group(key, descriptor)
            self.groups[key] = GroupState.STAGED
            response_tlvs = (
                group_handle_tlv(handle),
                ResourceAllocation(
                    group_slots=1,
                    replication_groups=reservation.replication_groups,
                    replication_entries=reservation.replication_entries,
                ).to_tlv(TlvType.RESOURCE_RESERVATION),
            )
        elif command == ControlCommand.GROUP_COMMIT:
            handle = GroupHandleWire.unpack(_one(tlvs, TlvType.GROUP_HANDLE).value)
            key = (handle.group_id, handle.generation)
            if key not in self.groups:
                raise PrismError(Status.NOT_FOUND, "group not staged")
            self.groups[key] = GroupState.INSTALLED
            reported = self.reported_state_once.pop(command, int(GroupState.INSTALLED))
            response_tlvs = (group_handle_tlv(handle), Tlv.u64(TlvType.GROUP_STATUS, reported))
        elif command == ControlCommand.GROUP_ABORT:
            handle = GroupHandleWire.unpack(_one(tlvs, TlvType.GROUP_HANDLE).value)
            key = (handle.group_id, handle.generation)
            self.groups.pop(key, None)
            self.pool.destroy_group(key)
            response_tlvs = (ResourceAllocation(group_slots=1).to_tlv(TlvType.RELEASED_RESOURCES),)
        elif command == ControlCommand.GROUP_STATUS:
            handle = GroupHandleWire.unpack(_one(tlvs, TlvType.GROUP_HANDLE).value)
            state = self.groups.get((handle.group_id, handle.generation), GroupState.FREE)
            response_tlvs = (group_handle_tlv(handle), Tlv.u64(TlvType.GROUP_STATUS, int(state)))
        elif command == ControlCommand.GROUP_DESTROY:
            handle = GroupHandleWire.unpack(_one(tlvs, TlvType.GROUP_HANDLE).value)
            key = (handle.group_id, handle.generation)
            self.pool.destroy_group(key)
            self.groups.pop(key, None)
            response_tlvs = (group_handle_tlv(handle), ResourceAllocation(group_slots=1).to_tlv(TlvType.RELEASED_RESOURCES))
        elif command == ControlCommand.OP_PREPARE:
            group = GroupHandleWire.unpack(_one(tlvs, TlvType.GROUP_HANDLE).value)
            handle = OperationHandleWire.unpack(_one(tlvs, TlvType.OPERATION_HANDLE).value)
            key = (handle.operation_id, handle.generation)
            routes = tuple(
                ResultRoute.unpack(item.value) for item in tlvs if item.type == TlvType.RESULT_ROUTE
            )
            descriptor = OperationDescriptor.unpack(_one(tlvs, TlvType.OPERATION_DESCRIPTOR).value, routes)
            reservation = self.pool.prepare_operation(
                (group.group_id, group.generation, handle.operation_id, handle.generation),
                descriptor,
            )
            self.operations[key] = OperationState.PREPARED
            self.operation_groups[key] = group
            response_tlvs = (
                operation_handle_tlv(handle),
                ResourceAllocation(
                    operation_slots=1,
                    phase_bitmap_bytes=reservation.bitmap_bytes,
                    aggregation_slots=reservation.aggregation_slots,
                    replay_output_slots=reservation.replay_slots,
                    route_entries=reservation.route_entries,
                ).to_tlv(TlvType.GRANTED_RESOURCES),
            )
        elif command == ControlCommand.OP_COMMIT:
            handle = OperationHandleWire.unpack(_one(tlvs, TlvType.OPERATION_HANDLE).value)
            key = (handle.operation_id, handle.generation)
            if key not in self.operations:
                raise PrismError(Status.NOT_FOUND, "operation not prepared")
            group = self.operation_groups[key]
            self.pool.commit_operation((group.group_id, group.generation, handle.operation_id, handle.generation))
            self.operations[key] = OperationState.ACTIVE
            reported = self.reported_state_once.pop(command, int(OperationState.ACTIVE))
            response_tlvs = (operation_handle_tlv(handle), Tlv.u64(TlvType.OPERATION_STATUS, reported))
        elif command == ControlCommand.OP_ABORT:
            handle = OperationHandleWire.unpack(_one(tlvs, TlvType.OPERATION_HANDLE).value)
            key = (handle.operation_id, handle.generation)
            group = self.operation_groups[key]
            self.pool.abort_operation((group.group_id, group.generation, handle.operation_id, handle.generation))
            self.operations[key] = OperationState.ABORTED
            response_tlvs = (operation_handle_tlv(handle), Tlv.u64(TlvType.OPERATION_STATUS, int(OperationState.ABORTED)))
        elif command == ControlCommand.OP_STATUS:
            handle = OperationHandleWire.unpack(_one(tlvs, TlvType.OPERATION_HANDLE).value)
            state = self.operations.get((handle.operation_id, handle.generation), OperationState.FREE)
            response_tlvs = (operation_handle_tlv(handle), Tlv.u64(TlvType.OPERATION_STATUS, int(state)))
        elif command == ControlCommand.OP_RELEASE:
            handle = OperationHandleWire.unpack(_one(tlvs, TlvType.OPERATION_HANDLE).value)
            key = (handle.operation_id, handle.generation)
            group = self.operation_groups.pop(key, None)
            released = None if group is None else self.pool.release_operation(
                (group.group_id, group.generation, handle.operation_id, handle.generation)
            )
            self.operations.pop(key, None)
            allocation = ResourceAllocation() if released is None else ResourceAllocation(
                operation_slots=1,
                phase_bitmap_bytes=released.bitmap_bytes,
                aggregation_slots=released.aggregation_slots,
                replay_output_slots=released.replay_slots,
                route_entries=released.route_entries,
            )
            response_tlvs = (operation_handle_tlv(handle), allocation.to_tlv(TlvType.RELEASED_RESOURCES))
        else:
            raise PrismError(Status.UNSUPPORTED_COMMAND, command.name)

        if command in self.lose_after_apply_once:
            self.lose_after_apply_once.remove(command)
            raise PrismError(Status.TIMEOUT, "injected lost response", self.switch_id)

        response_command = RESPONSE_FOR[command]
        response_cookie = self.cookie if command == ControlCommand.SESSION_OPEN else session_cookie
        return ControlResponse(
            ControlHeader(
                response_cookie,
                transaction_id or self.calls[command],
                response_command,
                ControlFlag.RESPONSE,
                Status.OK,
            ),
            response_tlvs,
        )


def _one(tlvs: tuple[Tlv, ...], type_: TlvType) -> Tlv:
    values = [tlv for tlv in tlvs if tlv.type == type_]
    if len(values) != 1:
        raise AssertionError(f"expected one {type_.name}")
    return values[0]
