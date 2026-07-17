"""Canonical numeric assignments for the PRISM 1.0 host and wire protocol."""

from __future__ import annotations

from enum import IntEnum, IntFlag


VERSION_MAJOR = 1
VERSION_MINOR = 0
ETHERTYPE = 0x88B5
ETHERNET_PAYLOAD_BYTES = 1500
CONTROL_WORD_BYTES = 2
CONTROL_HEADER_BYTES = 24
DATA_HEADER_BYTES = 24
RESULT_HEADER_BYTES = 24
PROGRESS_HEADER_BYTES = 40
CHUNK_PAYLOAD_BYTES = ETHERNET_PAYLOAD_BYTES - CONTROL_WORD_BYTES - DATA_HEADER_BYTES
PROGRESS_PAYLOAD_BYTES = ETHERNET_PAYLOAD_BYTES - CONTROL_WORD_BYTES - PROGRESS_HEADER_BYTES
MAX_CHUNKS = 1 << 24
MAX_BITMAP_BYTES = MAX_CHUNKS // 8
MAX_TWO_PHASE_BITMAP_BYTES = 2 * MAX_BITMAP_BYTES


class Opcode(IntEnum):
    INVALID = 0x00
    CONTROL = 0x01
    COL_DATA = 0x02
    COL_RES = 0x03
    COL_PROGRESS = 0x04


class ControlCommand(IntEnum):
    INVALID = 0x0000

    CAPS_QUERY = 0x0001
    CAPS_RESPONSE = 0x0002
    RESOURCE_QUERY = 0x0003
    RESOURCE_RESPONSE = 0x0004

    SESSION_OPEN = 0x0010
    SESSION_OPEN_RESPONSE = 0x0011
    SESSION_RENEW = 0x0012
    SESSION_RENEW_RESPONSE = 0x0013
    SESSION_CLOSE = 0x0014
    SESSION_CLOSE_RESPONSE = 0x0015

    GROUP_STAGE = 0x0100
    GROUP_STAGE_RESPONSE = 0x0101
    GROUP_COMMIT = 0x0102
    GROUP_COMMIT_RESPONSE = 0x0103
    GROUP_ABORT = 0x0104
    GROUP_ABORT_RESPONSE = 0x0105
    GROUP_STATUS = 0x0106
    GROUP_STATUS_RESPONSE = 0x0107
    GROUP_DESTROY = 0x0108
    GROUP_DESTROY_RESPONSE = 0x0109

    OP_PREPARE = 0x0200
    OP_PREPARE_RESPONSE = 0x0201
    OP_COMMIT = 0x0202
    OP_COMMIT_RESPONSE = 0x0203
    OP_ABORT = 0x0204
    OP_ABORT_RESPONSE = 0x0205
    OP_STATUS = 0x0206
    OP_STATUS_RESPONSE = 0x0207
    OP_RELEASE = 0x0208
    OP_RELEASE_RESPONSE = 0x0209

    OP_COMPLETE_EVENT = 0x0300
    OP_ERROR_EVENT = 0x0301
    RESOURCE_PRESSURE_EVENT = 0x0302
    EVENT_ACK = 0x0303


RESPONSE_FOR: dict[ControlCommand, ControlCommand] = {
    ControlCommand.CAPS_QUERY: ControlCommand.CAPS_RESPONSE,
    ControlCommand.RESOURCE_QUERY: ControlCommand.RESOURCE_RESPONSE,
    ControlCommand.SESSION_OPEN: ControlCommand.SESSION_OPEN_RESPONSE,
    ControlCommand.SESSION_RENEW: ControlCommand.SESSION_RENEW_RESPONSE,
    ControlCommand.SESSION_CLOSE: ControlCommand.SESSION_CLOSE_RESPONSE,
    ControlCommand.GROUP_STAGE: ControlCommand.GROUP_STAGE_RESPONSE,
    ControlCommand.GROUP_COMMIT: ControlCommand.GROUP_COMMIT_RESPONSE,
    ControlCommand.GROUP_ABORT: ControlCommand.GROUP_ABORT_RESPONSE,
    ControlCommand.GROUP_STATUS: ControlCommand.GROUP_STATUS_RESPONSE,
    ControlCommand.GROUP_DESTROY: ControlCommand.GROUP_DESTROY_RESPONSE,
    ControlCommand.OP_PREPARE: ControlCommand.OP_PREPARE_RESPONSE,
    ControlCommand.OP_COMMIT: ControlCommand.OP_COMMIT_RESPONSE,
    ControlCommand.OP_ABORT: ControlCommand.OP_ABORT_RESPONSE,
    ControlCommand.OP_STATUS: ControlCommand.OP_STATUS_RESPONSE,
    ControlCommand.OP_RELEASE: ControlCommand.OP_RELEASE_RESPONSE,
}


class Status(IntEnum):
    OK = 0x00
    UNSUPPORTED_VERSION = 0x01
    UNSUPPORTED_COMMAND = 0x02
    UNSUPPORTED_FEATURE = 0x03
    INVALID_REQUEST = 0x04
    INVALID_RECORD = 0x05
    INVALID_STATE = 0x06
    AUTH_REQUIRED = 0x07
    AUTH_FAILED = 0x08
    STALE_SESSION = 0x09
    STALE_DEVICE_BOOT_ID = 0x0A
    TXN_CONFLICT = 0x0B
    NOT_FOUND = 0x0C
    ALREADY_EXISTS = 0x0D
    GENERATION_MISMATCH = 0x0E
    GROUP_BUSY = 0x0F
    OPERATION_BUSY = 0x10
    NO_GROUP_SLOT = 0x11
    NO_OPERATION_SLOT = 0x12
    NO_BITMAP_MEMORY = 0x13
    NO_ACCUMULATOR_RANGE = 0x14
    NO_REPLAY_BUFFER = 0x15
    NO_ROUTE_RESOURCE = 0x16
    NO_REPLICATION_RESOURCE = 0x17
    UNSUPPORTED_ARITHMETIC_TUPLE = 0x18
    BAD_PAYLOAD_LENGTH = 0x19
    OUT_OF_WINDOW = 0x1A
    RETRY = 0x1B
    TIMEOUT = 0x1C
    ABORTED = 0x1D
    INTERNAL_ERROR = 0x1E


class ControlFlag(IntFlag):
    REQUEST = 0x01
    RESPONSE = 0x02
    EVENT = 0x04
    ACK_REQUIRED = 0x08
    AUTH_PRESENT = 0x10


class TlvFlag(IntFlag):
    MANDATORY = 0x0001


class DataFlag(IntFlag):
    RETRANSMIT = 0x01
    ACK_REQUIRED = 0x02
    LAST_CHUNK = 0x04


class ProgressFlag(IntFlag):
    DUPLICATE = 0x01
    SELECTIVE_ACK = 0x02
    WINDOW_UPDATE = 0x04
    RESULT_PATH = 0x08
    FATAL = 0x10


class ProgressPeerKind(IntEnum):
    INVALID = 0x00
    CONTRIBUTOR = 0x01
    RESULT_PATH = 0x02
    ENDPOINT = 0x03


class ProgressReason(IntEnum):
    NONE = 0x00
    ACCEPTED = 0x01
    DUPLICATE = 0x02
    OUT_OF_WINDOW = 0x03
    NO_SLOT = 0x04
    STALE_GENERATION = 0x05
    BAD_PAYLOAD = 0x06
    RETRY_LATER = 0x07
    FATAL_OPERATION = 0x08


class FeatureFlag(IntFlag):
    RELIABLE_HOP_BY_HOP = 1 << 0
    SELECTIVE_ACK = 1 << 1
    RESULT_ACK = 1 << 2
    LEASED_SESSIONS = 1 << 3
    MANAGEMENT_AUTH = 1 << 4
    MACSEC_MANAGEMENT_DOMAIN = 1 << 5
    EXTERNAL_BITMAP_MEMORY = 1 << 6


class SecurityProfile(IntEnum):
    LAB_UNAUTHENTICATED = 0x00
    EXTERNAL_AUTHENTICATED_CHANNEL = 0x01
    IN_PROTOCOL_AUTHENTICATION = 0x02


class NodeRole(IntEnum):
    INVALID = 0x00
    LEAF = 0x01
    INTERNAL = 0x02
    ROOT = 0x03
    SINGLE = 0x04


class NextHopType(IntEnum):
    INVALID = 0x00
    SWITCH = 0x01
    RANK = 0x02


class CollectiveSemantic(IntEnum):
    INVALID = 0x00
    REDUCE = 0x01
    ALLREDUCE = 0x02
    REDUCE_SCATTER = 0x03


class ReductionOperator(IntEnum):
    INVALID = 0x00
    SUM = 0x01


class WireFormat(IntEnum):
    INVALID = 0x00
    INT8 = 0x01
    FP16 = 0x02
    BF16 = 0x03
    FP32 = 0x04


BYTES_PER_ELEMENT: dict[WireFormat, int] = {
    WireFormat.INT8: 1,
    WireFormat.FP16: 2,
    WireFormat.BF16: 2,
    WireFormat.FP32: 4,
}


class PartialWireFormat(IntEnum):
    """Encoding used by PM_OP_COL_DATA between aggregation switches.

    Protocol 1.0 assigns only FP32. Exact and Kulisch encodings require a
    separately frozen layout before they can receive numeric assignments.
    """

    INVALID = 0x00
    FP32 = 0x04


PARTIAL_BYTES_PER_ELEMENT: dict[PartialWireFormat, int] = {
    PartialWireFormat.FP32: 4,
}


class AccumulatorProfile(IntEnum):
    INVALID = 0x00
    FP32 = 0x01


class AccumulationPolicy(IntEnum):
    INVALID = 0x00
    EAGER = 0x01
    CONTRIBUTOR_ORDERED = 0x02


class SessionState(IntEnum):
    CLOSED = 0x00
    OPEN = 0x01
    EXPIRING = 0x02
    ORPHANED = 0x03


class GroupState(IntEnum):
    FREE = 0x00
    STAGED = 0x01
    INSTALLED = 0x02
    DESTROYING = 0x03


class OperationState(IntEnum):
    FREE = 0x00
    PREPARED = 0x01
    ACTIVE = 0x02
    COMPLETE = 0x03
    RELEASING = 0x04
    ABORTED = 0x05


class AccumulatorRangeState(IntEnum):
    EMPTY = 0x00
    ACTIVE = 0x01
    OUTPUT_PENDING = 0x02


class TlvType(IntEnum):
    INVALID = 0x0000

    JOB_ID = 0x0001
    DEVICE_BOOT_ID = 0x0002
    SESSION_COOKIE = 0x0003
    LEASE_MS = 0x0004
    LEASE_GRACE_MS = 0x0005
    SECURITY_PROFILE = 0x0006
    FEATURE_MASK = 0x0007
    PROTOCOL_VERSION_RANGE = 0x0008
    CAPABILITIES = 0x0009
    RESOURCE_SNAPSHOT_ID = 0x000A
    RESOURCE_SNAPSHOT = 0x000B
    RESOURCE_RESERVATION = 0x000C
    PAYLOAD_DIGEST = 0x000D
    ERROR_DETAIL = 0x000E
    RELEASED_RESOURCES = 0x000F
    AUTH_DATA = 0x0010
    SESSION_USAGE = 0x0011

    GROUP_HANDLE = 0x0100
    GROUP_DESCRIPTOR = 0x0101
    CONTRIBUTOR_BINDING = 0x0102
    UPSTREAM_ACTION = 0x0103
    REPLICATION_GROUP = 0x0104
    GROUP_STATUS = 0x0105

    OPERATION_HANDLE = 0x0200
    OPERATION_DESCRIPTOR = 0x0201
    RESULT_ROUTE_RANGE = 0x0202
    GRANTED_RESOURCES = 0x0203
    OPERATION_STATUS = 0x0204
    PHASE_BITMAP_SUMMARY = 0x0205
    RETRY_POLICY = 0x0206

    EVENT_DETAIL = 0x0300


class CapabilityKey(IntEnum):
    INVALID = 0x0000
    MAX_SESSIONS = 0x0001
    MAX_INSTALLED_GROUPS = 0x0002
    MAX_OPERATION_CONTEXTS = 0x0003
    MAX_ACTIVE_OPERATIONS_GLOBAL = 0x0004
    MAX_ACTIVE_OPERATIONS_PER_GROUP = 0x0005
    MAX_CHUNKS_PER_DIRECT_STREAM = 0x0006
    MAX_BITMAP_BYTES_PER_OPERATION = 0x0007
    TOTAL_PHASE_BITMAP_POOL_BYTES = 0x0008
    MAX_ACTIVE_ACCUMULATOR_RANGES_GLOBAL = 0x0009
    MAX_ACTIVE_ACCUMULATOR_RANGES_PER_OPERATION = 0x000A
    TOTAL_REPLAY_OUTPUT_SLOTS = 0x000B
    MAX_LOCAL_CONTRIBUTORS = 0x000C
    MAX_REPLICATION_GROUPS = 0x000D
    MAX_RESULT_DESTINATIONS_PER_GROUP = 0x000E
    MAX_OPERATION_RESULT_ROUTE_RANGES = 0x000F
    MAX_MANAGEMENT_STAGING_BYTES = 0x0010
    MAX_SELECTIVE_ACK_WINDOW = 0x0011
    SUPPORTED_COLLECTIVE_SEMANTICS = 0x0012
    SUPPORTED_REDUCTION_OPERATORS = 0x0013
    SUPPORTED_ARITHMETIC_TUPLE = 0x0014
    MTU_BYTES = 0x0015
    MAX_PRISM_PAYLOAD_BYTES = 0x0016
    SUPPORTED_SECURITY_PROFILES = 0x0017
    SUPPORTED_RELIABILITY_FEATURES = 0x0018
    REPLAY_CACHE_DEPTH = 0x0019
    REPLAY_CACHE_RETENTION_MS = 0x001A
    SUPPORTED_ACCUMULATOR_PROFILE = 0x001B


class ResourceKey(IntEnum):
    INVALID = 0x0000
    FREE_GROUP_SLOTS = 0x0001
    FREE_OPERATION_CONTEXTS = 0x0002
    FREE_ACTIVE_OPERATION_SLOTS = 0x0003
    FREE_PHASE_BITMAP_BYTES = 0x0004
    FREE_ACCUMULATOR_RANGES = 0x0005
    FREE_REPLAY_OUTPUT_SLOTS = 0x0006
    FREE_ROUTE_ENTRIES = 0x0007
    FREE_REPLICATION_GROUPS = 0x0008
    FREE_REPLICATION_ENTRIES = 0x0009
    SESSION_GROUP_USAGE = 0x000A
    SESSION_PREPARED_OPERATION_USAGE = 0x000B
    SESSION_ACTIVE_OPERATION_USAGE = 0x000C
    SESSION_BITMAP_USAGE_BYTES = 0x000D
    SESSION_ACCUMULATOR_RANGE_USAGE = 0x000E


class AllocationKey(IntEnum):
    INVALID = 0x0000
    GROUP_SLOTS = 0x0001
    OPERATION_SLOTS = 0x0002
    PHASE_BITMAP_BYTES = 0x0003
    ACCUMULATOR_RANGES = 0x0004
    REPLAY_OUTPUT_SLOTS = 0x0005
    ROUTE_ENTRIES = 0x0006
    REPLICATION_GROUPS = 0x0007
    REPLICATION_ENTRIES = 0x0008


REPEATABLE_TLVS = frozenset(
    {
        TlvType.CONTRIBUTOR_BINDING,
        TlvType.REPLICATION_GROUP,
        TlvType.RESULT_ROUTE_RANGE,
    }
)


class TlvSchema(tuple):
    """Tuple-like schema: mandatory, optional, repeatable TLV type sets."""

    __slots__ = ()

    def __new__(
        cls,
        mandatory: set[TlvType] | frozenset[TlvType] = frozenset(),
        optional: set[TlvType] | frozenset[TlvType] = frozenset(),
        repeatable: set[TlvType] | frozenset[TlvType] = frozenset(),
    ) -> "TlvSchema":
        return tuple.__new__(cls, (frozenset(mandatory), frozenset(optional), frozenset(repeatable)))

    @property
    def mandatory(self) -> frozenset[TlvType]:
        return self[0]

    @property
    def optional(self) -> frozenset[TlvType]:
        return self[1]

    @property
    def repeatable(self) -> frozenset[TlvType]:
        return self[2]


COMMAND_TLV_SCHEMAS: dict[ControlCommand, TlvSchema] = {
    ControlCommand.CAPS_QUERY: TlvSchema(optional={TlvType.SECURITY_PROFILE}),
    ControlCommand.CAPS_RESPONSE: TlvSchema(
        mandatory={TlvType.DEVICE_BOOT_ID, TlvType.PROTOCOL_VERSION_RANGE, TlvType.CAPABILITIES},
        optional={TlvType.FEATURE_MASK, TlvType.SECURITY_PROFILE},
    ),
    ControlCommand.RESOURCE_QUERY: TlvSchema(optional={TlvType.GROUP_HANDLE, TlvType.OPERATION_HANDLE}),
    ControlCommand.RESOURCE_RESPONSE: TlvSchema(
        mandatory={TlvType.RESOURCE_SNAPSHOT_ID, TlvType.RESOURCE_SNAPSHOT},
        optional={TlvType.SESSION_USAGE},
    ),
    ControlCommand.SESSION_OPEN: TlvSchema(
        mandatory={TlvType.JOB_ID, TlvType.SECURITY_PROFILE},
        optional={TlvType.AUTH_DATA, TlvType.LEASE_MS},
    ),
    ControlCommand.SESSION_OPEN_RESPONSE: TlvSchema(
        mandatory={TlvType.SESSION_COOKIE, TlvType.DEVICE_BOOT_ID, TlvType.LEASE_MS, TlvType.LEASE_GRACE_MS}
    ),
    ControlCommand.SESSION_RENEW: TlvSchema(optional={TlvType.LEASE_MS, TlvType.AUTH_DATA}),
    ControlCommand.SESSION_RENEW_RESPONSE: TlvSchema(mandatory={TlvType.LEASE_MS}),
    ControlCommand.SESSION_CLOSE: TlvSchema(),
    ControlCommand.SESSION_CLOSE_RESPONSE: TlvSchema(optional={TlvType.RELEASED_RESOURCES}),
    ControlCommand.GROUP_STAGE: TlvSchema(
        mandatory={TlvType.GROUP_HANDLE, TlvType.GROUP_DESCRIPTOR, TlvType.UPSTREAM_ACTION},
        optional={TlvType.CONTRIBUTOR_BINDING, TlvType.REPLICATION_GROUP},
        repeatable={TlvType.CONTRIBUTOR_BINDING, TlvType.REPLICATION_GROUP},
    ),
    ControlCommand.GROUP_STAGE_RESPONSE: TlvSchema(
        mandatory={TlvType.GROUP_HANDLE, TlvType.RESOURCE_RESERVATION}
    ),
    ControlCommand.GROUP_COMMIT: TlvSchema(mandatory={TlvType.GROUP_HANDLE}),
    ControlCommand.GROUP_COMMIT_RESPONSE: TlvSchema(mandatory={TlvType.GROUP_HANDLE, TlvType.GROUP_STATUS}),
    ControlCommand.GROUP_ABORT: TlvSchema(mandatory={TlvType.GROUP_HANDLE}),
    ControlCommand.GROUP_ABORT_RESPONSE: TlvSchema(optional={TlvType.RELEASED_RESOURCES}),
    ControlCommand.GROUP_STATUS: TlvSchema(mandatory={TlvType.GROUP_HANDLE}),
    ControlCommand.GROUP_STATUS_RESPONSE: TlvSchema(mandatory={TlvType.GROUP_HANDLE, TlvType.GROUP_STATUS}),
    ControlCommand.GROUP_DESTROY: TlvSchema(mandatory={TlvType.GROUP_HANDLE}),
    ControlCommand.GROUP_DESTROY_RESPONSE: TlvSchema(
        mandatory={TlvType.GROUP_HANDLE}, optional={TlvType.RELEASED_RESOURCES}
    ),
    ControlCommand.OP_PREPARE: TlvSchema(
        mandatory={TlvType.GROUP_HANDLE, TlvType.OPERATION_HANDLE, TlvType.OPERATION_DESCRIPTOR},
        optional={TlvType.RESULT_ROUTE_RANGE, TlvType.RETRY_POLICY},
        repeatable={TlvType.RESULT_ROUTE_RANGE},
    ),
    ControlCommand.OP_PREPARE_RESPONSE: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE, TlvType.GRANTED_RESOURCES}
    ),
    ControlCommand.OP_COMMIT: TlvSchema(mandatory={TlvType.OPERATION_HANDLE}),
    ControlCommand.OP_COMMIT_RESPONSE: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE, TlvType.OPERATION_STATUS}
    ),
    ControlCommand.OP_ABORT: TlvSchema(mandatory={TlvType.OPERATION_HANDLE}),
    ControlCommand.OP_ABORT_RESPONSE: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE, TlvType.OPERATION_STATUS}
    ),
    ControlCommand.OP_STATUS: TlvSchema(mandatory={TlvType.OPERATION_HANDLE}),
    ControlCommand.OP_STATUS_RESPONSE: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE, TlvType.OPERATION_STATUS},
        optional={TlvType.PHASE_BITMAP_SUMMARY, TlvType.ERROR_DETAIL},
    ),
    ControlCommand.OP_RELEASE: TlvSchema(mandatory={TlvType.OPERATION_HANDLE}),
    ControlCommand.OP_RELEASE_RESPONSE: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE}, optional={TlvType.RELEASED_RESOURCES}
    ),
    ControlCommand.OP_COMPLETE_EVENT: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE, TlvType.EVENT_DETAIL}
    ),
    ControlCommand.OP_ERROR_EVENT: TlvSchema(
        mandatory={TlvType.OPERATION_HANDLE, TlvType.EVENT_DETAIL, TlvType.ERROR_DETAIL}
    ),
    ControlCommand.RESOURCE_PRESSURE_EVENT: TlvSchema(mandatory={TlvType.EVENT_DETAIL}),
    ControlCommand.EVENT_ACK: TlvSchema(mandatory={TlvType.EVENT_DETAIL}),
}


def assert_unique_enum_values() -> None:
    """Fail if an enum accidentally aliases a numeric wire value."""

    enums = (
        Opcode,
        ControlCommand,
        Status,
        ProgressPeerKind,
        ProgressReason,
        SecurityProfile,
        NodeRole,
        NextHopType,
        CollectiveSemantic,
        ReductionOperator,
        WireFormat,
        PartialWireFormat,
        AccumulatorProfile,
        AccumulationPolicy,
        TlvType,
        CapabilityKey,
        ResourceKey,
        AllocationKey,
    )
    for enum_type in enums:
        values = [member.value for member in enum_type]
        if len(values) != len(set(values)):
            raise AssertionError(f"duplicate numeric value in {enum_type.__name__}")


assert CHUNK_PAYLOAD_BYTES == 1474
assert PROGRESS_PAYLOAD_BYTES == 1458
assert MAX_BITMAP_BYTES == 2 * 1024 * 1024
assert MAX_TWO_PHASE_BITMAP_BYTES == 4 * 1024 * 1024
assert_unique_enum_values()
