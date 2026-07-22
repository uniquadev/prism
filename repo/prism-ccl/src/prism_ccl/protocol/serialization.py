"""Network-byte-order serializers and parsers for PRISM Protocol 1.0."""

from __future__ import annotations

import hashlib
import math
import struct
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from .constants import (
    COMMAND_TLV_SCHEMAS,
    CONTROL_HEADER_BYTES,
    CONTROL_WORD_BYTES,
    DATA_HEADER_BYTES,
    PROGRESS_HEADER_BYTES,
    RESULT_HEADER_BYTES,
    VERSION_MAJOR,
    VERSION_MINOR,
    ControlCommand,
    ControlFlag,
    DataFlag,
    Opcode,
    ProgressFlag,
    ProgressPeerKind,
    ProgressReason,
    Status,
    TlvFlag,
    TlvType,
)
from .errors import ProtocolDecodeError

_CONTROL_HEADER = struct.Struct("!QQHBBHH")
_DATA_HEADER = struct.Struct("!QHHHIH3sB")
_PROGRESS_HEADER = struct.Struct("!QHHHIHBB3sH3sHBBIH")
_TLV_HEADER = struct.Struct("!HHI")
_GROUP_HANDLE = struct.Struct("!HH")
_OPERATION_HANDLE = struct.Struct("!HI")
_PROTOCOL_VERSION_RANGE = struct.Struct("!BBBBI")


def _require_range(name: str, value: int, bits: int) -> None:
    if not 0 <= value < (1 << bits):
        raise ValueError(f"{name}={value} does not fit in {bits} bits")


def _pack_u24(value: int) -> bytes:
    _require_range("u24", value, 24)
    return value.to_bytes(3, "big")


def _unpack_u24(value: bytes) -> int:
    if len(value) != 3:
        raise ProtocolDecodeError("invalid 24-bit field")
    return int.from_bytes(value, "big")


def _enum[EnumT: Enum](enum_type: type[EnumT], value: int, field_name: str) -> EnumT:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ProtocolDecodeError(f"invalid {field_name} value 0x{value:x}") from exc


@dataclass(frozen=True, slots=True)
class ControlWord:
    opcode: Opcode
    major: int = VERSION_MAJOR
    minor: int = VERSION_MINOR

    def pack(self) -> bytes:
        _require_range("major", self.major, 4)
        _require_range("minor", self.minor, 4)
        return bytes(((self.major << 4) | self.minor, int(self.opcode)))

    @classmethod
    def unpack(cls, data: bytes) -> ControlWord:
        if len(data) != CONTROL_WORD_BYTES:
            raise ProtocolDecodeError("PRISM control word must be 2 bytes")
        major, minor = data[0] >> 4, data[0] & 0x0F
        opcode = _enum(Opcode, data[1], "opcode")
        if major != VERSION_MAJOR or minor != VERSION_MINOR:
            raise ProtocolDecodeError(f"unsupported PRISM version {major}.{minor}")
        return cls(opcode=opcode, major=major, minor=minor)


@dataclass(frozen=True, slots=True)
class ProtocolVersionRange:
    minimum_major: int
    minimum_minor: int
    maximum_major: int
    maximum_minor: int

    def pack(self) -> bytes:
        for name, value in (
            ("minimum_major", self.minimum_major),
            ("minimum_minor", self.minimum_minor),
            ("maximum_major", self.maximum_major),
            ("maximum_minor", self.maximum_minor),
        ):
            _require_range(name, value, 8)
        if (self.minimum_major, self.minimum_minor) > (self.maximum_major, self.maximum_minor):
            raise ValueError("protocol version range is reversed")
        return _PROTOCOL_VERSION_RANGE.pack(
            self.minimum_major,
            self.minimum_minor,
            self.maximum_major,
            self.maximum_minor,
            0,
        )

    @classmethod
    def unpack(cls, data: bytes) -> ProtocolVersionRange:
        if len(data) != _PROTOCOL_VERSION_RANGE.size:
            raise ProtocolDecodeError("protocol version range must be 8 bytes")
        minimum_major, minimum_minor, maximum_major, maximum_minor, reserved = (
            _PROTOCOL_VERSION_RANGE.unpack(data)
        )
        if reserved:
            raise ProtocolDecodeError("non-zero protocol version range reserved field")
        result = cls(minimum_major, minimum_minor, maximum_major, maximum_minor)
        if (minimum_major, minimum_minor) > (maximum_major, maximum_minor):
            raise ProtocolDecodeError("protocol version range is reversed")
        return result

    def supports(self, major: int, minor: int) -> bool:
        return (
            (self.minimum_major, self.minimum_minor)
            <= (major, minor)
            <= (
                self.maximum_major,
                self.maximum_minor,
            )
        )


@dataclass(frozen=True, slots=True)
class GroupHandleWire:
    group_id: int
    generation: int

    def pack(self) -> bytes:
        _require_range("group_id", self.group_id, 16)
        _require_range("group_generation", self.generation, 16)
        return _GROUP_HANDLE.pack(self.group_id, self.generation)

    @classmethod
    def unpack(cls, data: bytes) -> GroupHandleWire:
        if len(data) != _GROUP_HANDLE.size:
            raise ProtocolDecodeError("group handle must be 4 bytes")
        return cls(*_GROUP_HANDLE.unpack(data))


@dataclass(frozen=True, slots=True)
class OperationHandleWire:
    operation_id: int
    generation: int

    def pack(self) -> bytes:
        _require_range("operation_id", self.operation_id, 16)
        _require_range("operation_generation", self.generation, 32)
        return _OPERATION_HANDLE.pack(self.operation_id, self.generation)

    @classmethod
    def unpack(cls, data: bytes) -> OperationHandleWire:
        if len(data) != _OPERATION_HANDLE.size:
            raise ProtocolDecodeError("operation handle must be 6 bytes")
        return cls(*_OPERATION_HANDLE.unpack(data))


@dataclass(frozen=True, slots=True)
class OperationIdentity:
    job_id: int
    group_id: int
    group_generation: int
    operation_id: int
    operation_generation: int

    def validate(self) -> None:
        _require_range("job_id", self.job_id, 64)
        _require_range("group_id", self.group_id, 16)
        _require_range("group_generation", self.group_generation, 16)
        _require_range("operation_id", self.operation_id, 16)
        _require_range("operation_generation", self.operation_generation, 32)


@dataclass(frozen=True, slots=True)
class ControlHeader:
    session_cookie: int
    transaction_id: int
    command: ControlCommand
    flags: ControlFlag
    status: Status = Status.OK
    fragment_index: int = 0
    fragment_count: int = 1

    def pack(self) -> bytes:
        _require_range("session_cookie", self.session_cookie, 64)
        _require_range("transaction_id", self.transaction_id, 64)
        _require_range("flags", int(self.flags), 8)
        _require_range("status", int(self.status), 8)
        _require_range("fragment_index", self.fragment_index, 16)
        _require_range("fragment_count", self.fragment_count, 16)
        if self.fragment_count == 0 or self.fragment_index >= self.fragment_count:
            raise ValueError("invalid fragment index/count")
        known_flags = sum(int(flag) for flag in ControlFlag)
        if int(self.flags) & ~known_flags:
            raise ValueError("non-zero reserved control flags")
        return _CONTROL_HEADER.pack(
            self.session_cookie,
            self.transaction_id,
            int(self.command),
            int(self.flags),
            int(self.status),
            self.fragment_index,
            self.fragment_count,
        )

    @classmethod
    def unpack(cls, data: bytes) -> ControlHeader:
        if len(data) != CONTROL_HEADER_BYTES:
            raise ProtocolDecodeError("PM_OP_CONTROL header must be 24 bytes")
        cookie, txn, command, flags, status, index, count = _CONTROL_HEADER.unpack(data)
        if count == 0 or index >= count:
            raise ProtocolDecodeError("invalid control fragment index/count")
        known_flags = sum(int(flag) for flag in ControlFlag)
        if flags & ~known_flags:
            raise ProtocolDecodeError("non-zero reserved control flags")
        return cls(
            session_cookie=cookie,
            transaction_id=txn,
            command=_enum(ControlCommand, command, "control command"),
            flags=ControlFlag(flags),
            status=_enum(Status, status, "status"),
            fragment_index=index,
            fragment_count=count,
        )


@dataclass(frozen=True, slots=True)
class Tlv:
    type: TlvType
    value: bytes
    flags: TlvFlag = TlvFlag.MANDATORY

    def pack(self) -> bytes:
        _require_range("TLV type", int(self.type), 16)
        _require_range("TLV flags", int(self.flags), 16)
        known_flags = sum(int(flag) for flag in TlvFlag)
        if int(self.flags) & ~known_flags:
            raise ValueError("non-zero reserved TLV flags")
        _require_range("TLV value length", len(self.value), 32)
        padding = (-len(self.value)) % 8
        return (
            _TLV_HEADER.pack(int(self.type), int(self.flags), len(self.value))
            + self.value
            + bytes(padding)
        )

    @classmethod
    def u64(cls, type_: TlvType, value: int, flags: TlvFlag = TlvFlag.MANDATORY) -> Tlv:
        _require_range(type_.name, value, 64)
        return cls(type_, value.to_bytes(8, "big"), flags)

    def as_u64(self) -> int:
        if len(self.value) != 8:
            raise ProtocolDecodeError(f"{self.type.name} is not a 64-bit value")
        return int.from_bytes(self.value, "big")


def pack_tlvs(tlvs: Iterable[Tlv]) -> bytes:
    return b"".join(tlv.pack() for tlv in tlvs)


def parse_tlvs(data: bytes) -> tuple[Tlv, ...]:
    result: list[Tlv] = []
    offset = 0
    known_flags = sum(int(flag) for flag in TlvFlag)
    while offset < len(data):
        if len(data) - offset < _TLV_HEADER.size:
            raise ProtocolDecodeError("truncated TLV header")
        type_value, flags_value, value_length = _TLV_HEADER.unpack_from(data, offset)
        if flags_value & ~known_flags:
            raise ProtocolDecodeError("non-zero reserved TLV flags")
        offset += _TLV_HEADER.size
        padded_length = value_length + ((-value_length) % 8)
        if value_length > len(data) - offset or padded_length > len(data) - offset:
            raise ProtocolDecodeError("truncated TLV value")
        value = data[offset : offset + value_length]
        padding = data[offset + value_length : offset + padded_length]
        if any(padding):
            raise ProtocolDecodeError("non-zero TLV padding")
        offset += padded_length
        try:
            type_ = TlvType(type_value)
        except ValueError:
            if flags_value & int(TlvFlag.MANDATORY):
                raise ProtocolDecodeError(f"unknown mandatory TLV 0x{type_value:04x}") from None
            continue
        result.append(Tlv(type_, value, TlvFlag(flags_value)))
    return tuple(result)


def validate_tlv_schema(command: ControlCommand, tlvs: Iterable[Tlv]) -> tuple[Tlv, ...]:
    values = tuple(tlvs)
    schema = COMMAND_TLV_SCHEMAS.get(command)
    if schema is None:
        raise ProtocolDecodeError(f"no TLV schema for {command.name}")
    seen: dict[TlvType, int] = {}
    allowed = schema.mandatory | schema.optional
    for tlv in values:
        if tlv.type not in allowed:
            if tlv.flags & TlvFlag.MANDATORY:
                raise ProtocolDecodeError(f"TLV {tlv.type.name} is not valid for {command.name}")
            continue
        seen[tlv.type] = seen.get(tlv.type, 0) + 1
        if seen[tlv.type] > 1 and tlv.type not in schema.repeatable:
            raise ProtocolDecodeError(f"duplicate non-repeatable TLV {tlv.type.name}")
    missing = schema.mandatory - seen.keys()
    if missing:
        raise ProtocolDecodeError(
            f"missing mandatory TLVs for {command.name}: "
            f"{', '.join(item.name for item in sorted(missing, key=int))}"
        )
    return values


@dataclass(frozen=True, slots=True)
class ControlFrame:
    header: ControlHeader
    payload: bytes = b""

    def pack(self) -> bytes:
        return ControlWord(Opcode.CONTROL).pack() + self.header.pack() + self.payload

    @classmethod
    def unpack(cls, data: bytes) -> ControlFrame:
        if len(data) < CONTROL_WORD_BYTES + CONTROL_HEADER_BYTES:
            raise ProtocolDecodeError("truncated PM_OP_CONTROL frame")
        word = ControlWord.unpack(data[:2])
        if word.opcode != Opcode.CONTROL:
            raise ProtocolDecodeError("frame is not PM_OP_CONTROL")
        return cls(ControlHeader.unpack(data[2:26]), data[26:])

    @classmethod
    def from_tlvs(cls, header: ControlHeader, tlvs: Iterable[Tlv]) -> ControlFrame:
        return cls(header, pack_tlvs(tlvs))

    def tlvs(self) -> tuple[Tlv, ...]:
        if self.header.fragment_count != 1:
            raise ProtocolDecodeError(
                "fragmented control payload must be reassembled before TLV parsing"
            )
        parsed = parse_tlvs(self.payload)
        return (
            validate_tlv_schema(self.header.command, parsed)
            if self.header.status == Status.OK
            else parsed
        )

    @property
    def payload_digest(self) -> bytes:
        return hashlib.sha256(self.payload).digest()


@dataclass(frozen=True, slots=True)
class DataHeader:
    identity: OperationIdentity
    contributor_id: int
    chunk_index: int
    flags: DataFlag = DataFlag.ACK_REQUIRED

    def pack_header(self) -> bytes:
        self.identity.validate()
        _require_range("contributor_id", self.contributor_id, 16)
        _require_range("flags", int(self.flags), 8)
        return _DATA_HEADER.pack(
            self.identity.job_id,
            self.identity.group_id,
            self.identity.group_generation,
            self.identity.operation_id,
            self.identity.operation_generation,
            self.contributor_id,
            _pack_u24(self.chunk_index),
            int(self.flags),
        )

    def pack(self, payload: bytes, *, allow_accumulation_inexact: bool = False) -> bytes:
        if (self.flags & DataFlag.ACCUMULATION_INEXACT) and not allow_accumulation_inexact:
            raise ValueError("endpoint-originated DATA cannot assert ACCUMULATION_INEXACT")
        return ControlWord(Opcode.COL_DATA).pack() + self.pack_header() + payload

    @classmethod
    def unpack(
        cls, data: bytes, *, laboratory_extension_enabled: bool = True
    ) -> tuple[DataHeader, bytes]:
        if len(data) < CONTROL_WORD_BYTES + DATA_HEADER_BYTES:
            raise ProtocolDecodeError("truncated PM_OP_COL_DATA frame")
        word = ControlWord.unpack(data[:2])
        if word.opcode != Opcode.COL_DATA:
            raise ProtocolDecodeError("frame is not PM_OP_COL_DATA")
        job, gid, ggen, oid, ogen, contributor, chunk, flags = _DATA_HEADER.unpack(data[2:26])
        known_flags = sum(int(flag) for flag in DataFlag)
        if flags & ~known_flags:
            raise ProtocolDecodeError("non-zero reserved data flags")
        if (flags & int(DataFlag.ACCUMULATION_INEXACT)) and not laboratory_extension_enabled:
            raise ProtocolDecodeError("ACCUMULATION_INEXACT requires the laboratory extension")
        identity = OperationIdentity(job, gid, ggen, oid, ogen)
        return cls(identity, contributor, _unpack_u24(chunk), DataFlag(flags)), data[26:]


@dataclass(frozen=True, slots=True)
class ResultHeader:
    identity: OperationIdentity
    result_path_id: int
    chunk_index: int
    flags: DataFlag = DataFlag.ACK_REQUIRED

    def pack_header(self) -> bytes:
        self.identity.validate()
        _require_range("result_path_id", self.result_path_id, 16)
        _require_range("flags", int(self.flags), 8)
        return _DATA_HEADER.pack(
            self.identity.job_id,
            self.identity.group_id,
            self.identity.group_generation,
            self.identity.operation_id,
            self.identity.operation_generation,
            self.result_path_id,
            _pack_u24(self.chunk_index),
            int(self.flags),
        )

    def pack(self, payload: bytes) -> bytes:
        return ControlWord(Opcode.COL_RES).pack() + self.pack_header() + payload

    @classmethod
    def unpack(
        cls, data: bytes, *, laboratory_extension_enabled: bool = True
    ) -> tuple[ResultHeader, bytes]:
        if len(data) < CONTROL_WORD_BYTES + RESULT_HEADER_BYTES:
            raise ProtocolDecodeError("truncated PM_OP_COL_RES frame")
        word = ControlWord.unpack(data[:2])
        if word.opcode != Opcode.COL_RES:
            raise ProtocolDecodeError("frame is not PM_OP_COL_RES")
        job, gid, ggen, oid, ogen, path, chunk, flags = _DATA_HEADER.unpack(data[2:26])
        known_flags = sum(int(flag) for flag in DataFlag)
        if flags & ~known_flags:
            raise ProtocolDecodeError("non-zero reserved result flags")
        if (flags & int(DataFlag.ACCUMULATION_INEXACT)) and not laboratory_extension_enabled:
            raise ProtocolDecodeError("ACCUMULATION_INEXACT requires the laboratory extension")
        identity = OperationIdentity(job, gid, ggen, oid, ogen)
        return cls(identity, path, _unpack_u24(chunk), DataFlag(flags)), data[26:]


@dataclass(frozen=True, slots=True)
class ProgressHeader:
    identity: OperationIdentity
    peer_id: int
    peer_kind: ProgressPeerKind
    flags: ProgressFlag
    window_base: int
    admitted_window_chunks: int
    selective_ack_base: int
    selective_ack_bits: int
    status: Status
    reason: ProgressReason
    retry_delay_us: int = 0

    def pack_header(self) -> bytes:
        self.identity.validate()
        _require_range("peer_id", self.peer_id, 16)
        _require_range("flags", int(self.flags), 8)
        _require_range("window_base", self.window_base, 24)
        _require_range("admitted_window_chunks", self.admitted_window_chunks, 16)
        _require_range("selective_ack_base", self.selective_ack_base, 24)
        _require_range("selective_ack_bits", self.selective_ack_bits, 16)
        _require_range("retry_delay_us", self.retry_delay_us, 32)
        return _PROGRESS_HEADER.pack(
            self.identity.job_id,
            self.identity.group_id,
            self.identity.group_generation,
            self.identity.operation_id,
            self.identity.operation_generation,
            self.peer_id,
            int(self.peer_kind),
            int(self.flags),
            _pack_u24(self.window_base),
            self.admitted_window_chunks,
            _pack_u24(self.selective_ack_base),
            self.selective_ack_bits,
            int(self.status),
            int(self.reason),
            self.retry_delay_us,
            0,
        )

    def pack(self, selective_ack_bitmap: bytes = b"") -> bytes:
        expected = math.ceil(self.selective_ack_bits / 8)
        if len(selective_ack_bitmap) != expected:
            raise ValueError(f"selective ACK bitmap must be {expected} bytes")
        if self.selective_ack_bits and selective_ack_bitmap:
            unused = (8 - (self.selective_ack_bits % 8)) % 8
            if unused and selective_ack_bitmap[-1] & ((1 << unused) - 1):
                raise ValueError("non-zero unused selective ACK bits")
        return ControlWord(Opcode.COL_PROGRESS).pack() + self.pack_header() + selective_ack_bitmap

    @classmethod
    def unpack(cls, data: bytes) -> tuple[ProgressHeader, bytes]:
        if len(data) < CONTROL_WORD_BYTES + PROGRESS_HEADER_BYTES:
            raise ProtocolDecodeError("truncated PM_OP_COL_PROGRESS frame")
        word = ControlWord.unpack(data[:2])
        if word.opcode != Opcode.COL_PROGRESS:
            raise ProtocolDecodeError("frame is not PM_OP_COL_PROGRESS")
        fields = _PROGRESS_HEADER.unpack(data[2:42])
        (
            job,
            gid,
            ggen,
            oid,
            ogen,
            peer_id,
            peer_kind,
            flags,
            window_base,
            window_chunks,
            ack_base,
            ack_bits,
            status,
            reason,
            retry_delay,
            reserved,
        ) = fields
        if reserved:
            raise ProtocolDecodeError("non-zero reserved progress field")
        known_flags = sum(int(flag) for flag in ProgressFlag)
        if flags & ~known_flags:
            raise ProtocolDecodeError("non-zero reserved progress flags")
        bitmap = data[42:]
        expected = math.ceil(ack_bits / 8)
        if len(bitmap) != expected:
            raise ProtocolDecodeError("invalid selective ACK bitmap length")
        unused = (8 - (ack_bits % 8)) % 8
        if unused and bitmap and bitmap[-1] & ((1 << unused) - 1):
            raise ProtocolDecodeError("non-zero unused selective ACK bits")
        identity = OperationIdentity(job, gid, ggen, oid, ogen)
        return (
            cls(
                identity,
                peer_id,
                _enum(ProgressPeerKind, peer_kind, "progress peer kind"),
                ProgressFlag(flags),
                _unpack_u24(window_base),
                window_chunks,
                _unpack_u24(ack_base),
                ack_bits,
                _enum(Status, status, "progress status"),
                _enum(ProgressReason, reason, "progress reason"),
                retry_delay,
            ),
            bitmap,
        )


@dataclass(slots=True)
class _FragmentTransaction:
    command: ControlCommand
    flags: ControlFlag
    status: Status
    fragment_count: int
    created_at: float
    fragments: dict[int, bytes] = field(default_factory=dict)


class ControlReassembler:
    """Bounded control-fragment reassembly keyed by cookie, transaction, command."""

    def __init__(self, max_staged_bytes: int, timeout_seconds: float) -> None:
        if max_staged_bytes <= 0 or timeout_seconds <= 0:
            raise ValueError("reassembly bounds must be positive")
        self.max_staged_bytes = max_staged_bytes
        self.timeout_seconds = timeout_seconds
        self._transactions: dict[tuple[int, int], _FragmentTransaction] = {}

    def add(self, frame: ControlFrame, now: float | None = None) -> tuple[Tlv, ...] | None:
        now = time.monotonic() if now is None else now
        self.expire(now)
        header = frame.header
        key = (header.session_cookie, header.transaction_id)
        transaction = self._transactions.get(key)
        if transaction is None:
            transaction = _FragmentTransaction(
                header.command,
                header.flags,
                header.status,
                header.fragment_count,
                now,
            )
            self._transactions[key] = transaction
        elif (
            transaction.command != header.command
            or transaction.flags != header.flags
            or transaction.status != header.status
            or transaction.fragment_count != header.fragment_count
        ):
            del self._transactions[key]
            raise ProtocolDecodeError("control header changed within a fragmented transaction")
        previous = transaction.fragments.get(header.fragment_index)
        if previous is not None and previous != frame.payload:
            del self._transactions[key]
            raise ProtocolDecodeError("conflicting duplicate control fragment")
        transaction.fragments[header.fragment_index] = frame.payload
        if sum(len(value) for value in transaction.fragments.values()) > self.max_staged_bytes:
            del self._transactions[key]
            raise ProtocolDecodeError("staged control transaction exceeds capability")
        if len(transaction.fragments) != transaction.fragment_count:
            return None
        payload = b"".join(
            transaction.fragments[index] for index in range(transaction.fragment_count)
        )
        del self._transactions[key]
        return validate_tlv_schema(header.command, parse_tlvs(payload))

    def expire(self, now: float | None = None) -> tuple[tuple[int, int], ...]:
        now = time.monotonic() if now is None else now
        expired = tuple(
            key
            for key, value in self._transactions.items()
            if now - value.created_at >= self.timeout_seconds
        )
        for key in expired:
            del self._transactions[key]
        return expired


assert _CONTROL_HEADER.size == CONTROL_HEADER_BYTES
assert _DATA_HEADER.size == DATA_HEADER_BYTES
assert _PROGRESS_HEADER.size == PROGRESS_HEADER_BYTES
