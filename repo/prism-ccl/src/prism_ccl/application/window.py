"""Bounded per-stream admission, gap tracking and idempotent replay."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..domain.model import ConcreteFormat, OperationKey
from ..domain.numbers import ExactValue, decode_kulisch, decode_native
from ..wire.data import DataPacket, PacketClass, decode_data_frame


class Admission(Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OUT_OF_WINDOW = "out_of_window"
    OVERLAP = "overlap"
    NO_CREDIT = "no_credit"


@dataclass(frozen=True, slots=True)
class ValidatedChunk:
    packet: DataPacket
    frame: bytes
    values: tuple[ExactValue, ...]


class ReceiveWindow:
    """Packet IDs are replay identities; coverage is global element intervals.

    Only intervals in the active window are retained. Old ranges cannot be
    applied twice even if a peer gives them a different packet ID.
    """

    def __init__(
        self,
        *,
        operation: OperationKey,
        packet_class: PacketClass,
        source_endpoint: int,
        destination_endpoint: int,
        stream_id: int,
        element_count: int,
        allowed_formats: frozenset[ConcreteFormat],
        mtu: int,
        kulisch_bits: int,
        maximum_intervals: int,
        maximum_bytes: int,
        element_span: int,
    ) -> None:
        if not 0 < element_count < 1 << 32:
            raise ValueError("operation needs a positive bounded element count")
        if not allowed_formats or min(maximum_intervals, maximum_bytes, element_span) <= 0:
            raise ValueError("receive window capacities must be positive")
        self.operation = operation
        self.packet_class = packet_class
        self.source_endpoint = source_endpoint
        self.destination_endpoint = destination_endpoint
        self.stream_id = stream_id
        self.element_count = element_count
        self.allowed_formats = allowed_formats
        self.mtu = mtu
        self.kulisch_bits = kulisch_bits
        self.maximum_intervals = maximum_intervals
        self.maximum_bytes = maximum_bytes
        self.element_span = element_span
        self.base = 0
        self.retired_packet_id = -1
        self.last_seen = False
        self.active = False
        self._pending: dict[int, ValidatedChunk] = {}
        self._packet_ids: dict[int, int] = {}
        self._retired_frames: dict[int, bytes] = {}
        self._outstanding_bytes = 0

    def activate(self) -> None:
        if self.active or self.base or self._pending:
            raise ValueError("receive window cannot be activated twice")
        self.active = True

    @property
    def credit_intervals(self) -> int:
        return self.maximum_intervals - len(self._pending)

    @property
    def credit_bytes(self) -> int:
        return self.maximum_bytes - self._outstanding_bytes

    @property
    def holes(self) -> tuple[tuple[int, int], ...]:
        cursor = self.base
        result: list[tuple[int, int]] = []
        for first in sorted(self._pending):
            if cursor < first:
                result.append((cursor, first))
            cursor = max(cursor, first + self._pending[first].packet.element_count)
        if self.last_seen and cursor < self.element_count:
            result.append((cursor, self.element_count))
        return tuple(result)

    @property
    def complete(self) -> bool:
        return self.last_seen and self.base == self.element_count and not self._pending

    def accept(self, frame: bytes) -> Admission:
        if not self.active:
            raise ValueError("operation configuration is not committed")
        # Full binary and numerical validation precedes *any* receive-state mutation.
        packet = decode_data_frame(frame, mtu=self.mtu, kulisch_bits=self.kulisch_bits)
        if (
            packet.operation != self.operation
            or packet.packet_class != self.packet_class
            or packet.source_endpoint != self.source_endpoint
            or packet.destination_endpoint != self.destination_endpoint
            or packet.stream_id != self.stream_id
        ):
            raise ValueError("packet identity does not match committed stream")
        end = packet.first_element + packet.element_count
        if end > self.element_count or packet.last != (end == self.element_count):
            raise ValueError("LAST and interval disagree with configured vector length")
        values: list[ExactValue] = []
        for group in packet.groups:
            if group.format not in self.allowed_formats:
                raise ValueError("NumberGroup format is not advertised for this stream")
            for encoded in group.values:
                if group.format == ConcreteFormat.KULISCH:
                    assert isinstance(encoded, bytes)
                    values.append(decode_kulisch(encoded, self.kulisch_bits))
                else:
                    assert isinstance(encoded, int)
                    values.append(decode_native(encoded, group.format))
        if packet.packet_id in self._packet_ids:
            prior = self._pending[self._packet_ids[packet.packet_id]]
            if prior.frame != frame:
                raise ValueError("replayed packet ID changed its bytes")
            return Admission.DUPLICATE
        if packet.packet_id in self._retired_frames:
            if self._retired_frames[packet.packet_id] != frame:
                raise ValueError("retired packet ID changed its bytes")
            return Admission.DUPLICATE
        if packet.packet_id <= self.retired_packet_id or packet.first_element < self.base:
            return Admission.OUT_OF_WINDOW
        if end > min(self.element_count, self.base + self.element_span):
            return Admission.OUT_OF_WINDOW
        for first, existing in self._pending.items():
            existing_end = first + existing.packet.element_count
            if packet.first_element < existing_end and first < end:
                return Admission.OVERLAP
            if (packet.first_element < first) != (packet.packet_id < existing.packet.packet_id):
                raise ValueError("packet IDs are not monotonic with element order")
        if self.credit_intervals == 0 or len(frame) > self.credit_bytes:
            return Admission.NO_CREDIT
        validated = ValidatedChunk(packet, frame, tuple(values))
        self._pending[packet.first_element] = validated
        self._packet_ids[packet.packet_id] = packet.first_element
        self._outstanding_bytes += len(frame)
        self.last_seen |= packet.last
        return Admission.ACCEPTED

    def peek_contiguous(self) -> ValidatedChunk | None:
        return self._pending.get(self.base)

    def release_contiguous(self, chunk: ValidatedChunk) -> None:
        """Call only after the caller atomically commits this validated range."""
        if self._pending.get(self.base) != chunk:
            raise ValueError("only current contiguous interval may be released")
        del self._pending[self.base]
        del self._packet_ids[chunk.packet.packet_id]
        self._retired_frames[chunk.packet.packet_id] = chunk.frame
        if len(self._retired_frames) > self.maximum_intervals:
            del self._retired_frames[min(self._retired_frames)]
        self._outstanding_bytes -= len(chunk.frame)
        self.base += chunk.packet.element_count
        self.retired_packet_id = chunk.packet.packet_id
