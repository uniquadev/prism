"""Dependency-free PCAP/PCAPNG inspection for PRISM Ethernet frames."""

from __future__ import annotations

import json
import re
import struct
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, cast

from ..protocol.constants import (
    BYTES_PER_ELEMENT,
    CHUNK_PAYLOAD_BYTES,
    ETHERTYPE,
    Opcode,
    WireFormat,
)
from ..protocol.errors import ProtocolDecodeError
from ..protocol.geometry import expected_payload_bytes
from ..protocol.numeric import decode_bits
from ..protocol.serialization import (
    ControlFrame,
    ControlWord,
    DataHeader,
    OperationIdentity,
    ProgressHeader,
    ResultHeader,
)

_PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
    b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
}
_PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"


@dataclass(frozen=True, slots=True)
class CapturedPacket:
    timestamp_ns: int
    original_length: int
    data: bytes
    interface_id: int = 0
    interface_name: str | None = None


@dataclass(frozen=True, slots=True)
class DecodedPrismPacket:
    opcode: Opcode
    header: object
    payload: bytes


@dataclass(frozen=True, slots=True)
class EthernetPacket:
    capture: CapturedPacket
    destination: str
    source: str
    ethertype: int
    vlan_tags: tuple[int, ...]
    payload: bytes
    prism: DecodedPrismPacket | None


@dataclass(frozen=True, slots=True)
class OperationDecodeContext:
    identity: OperationIdentity
    input_format: WireFormat
    output_format: WireFormat
    element_count: int


def identity_key(identity: OperationIdentity) -> str:
    return ":".join(
        str(value)
        for value in (
            identity.job_id,
            identity.group_id,
            identity.group_generation,
            identity.operation_id,
            identity.operation_generation,
        )
    )


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    value = stream.read(length)
    if len(value) != length:
        raise ProtocolDecodeError("truncated capture file")
    return value


def _iter_pcap(stream: BinaryIO, magic: bytes) -> Iterator[CapturedPacket]:
    endian, resolution = _PCAP_MAGIC[magic]
    rest = _read_exact(stream, 20)
    _, _, _, _, snaplen, network = struct.unpack(endian + "HHIIII", rest)
    if snaplen == 0 or network != 1:
        raise ProtocolDecodeError("capture must use Ethernet link type")
    header = struct.Struct(endian + "IIII")
    while True:
        raw_header = stream.read(header.size)
        if not raw_header:
            return
        if len(raw_header) != header.size:
            raise ProtocolDecodeError("truncated PCAP packet header")
        seconds, fraction, captured_length, original_length = header.unpack(raw_header)
        if captured_length > snaplen:
            raise ProtocolDecodeError("PCAP packet exceeds declared snapshot length")
        yield CapturedPacket(
            seconds * 1_000_000_000 + (fraction * 1_000_000_000 // resolution),
            original_length,
            _read_exact(stream, captured_length),
        )


def _pcapng_options(raw: bytes, endian: str) -> Iterator[tuple[int, bytes]]:
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < 4:
            raise ProtocolDecodeError("truncated PCAPNG option header")
        code, length = struct.unpack_from(endian + "HH", raw, offset)
        offset += 4
        padded_length = (length + 3) & ~3
        if offset + padded_length > len(raw):
            raise ProtocolDecodeError("truncated PCAPNG option value")
        value = raw[offset : offset + length]
        offset += padded_length
        if code == 0:
            if length != 0:
                raise ProtocolDecodeError("invalid PCAPNG end-of-options marker")
            return
        yield code, value


def _iter_pcapng(stream: BinaryIO) -> Iterator[CapturedPacket]:
    # The section header magic has already been consumed. Its byte-order magic
    # is still available in the first block body.
    raw_length = _read_exact(stream, 4)
    raw_bom = _read_exact(stream, 4)
    if raw_bom == b"\x4d\x3c\x2b\x1a":
        endian = "<"
    elif raw_bom == b"\x1a\x2b\x3c\x4d":
        endian = ">"
    else:
        raise ProtocolDecodeError("invalid PCAPNG byte-order magic")
    block_length = struct.unpack(endian + "I", raw_length)[0]
    if block_length < 28 or block_length % 4:
        raise ProtocolDecodeError("invalid PCAPNG section length")
    _read_exact(stream, block_length - 16)
    if struct.unpack(endian + "I", _read_exact(stream, 4))[0] != block_length:
        raise ProtocolDecodeError("PCAPNG section length mismatch")

    link_types: list[int] = []
    timestamp_resolutions: list[int] = []
    interface_names: list[str | None] = []
    while True:
        raw_type = stream.read(4)
        if not raw_type:
            return
        raw_length = _read_exact(stream, 4)
        block_type, block_length = struct.unpack(endian + "II", raw_type + raw_length)
        if block_length < 12 or block_length % 4:
            raise ProtocolDecodeError("invalid PCAPNG block length")
        body = _read_exact(stream, block_length - 12)
        if struct.unpack(endian + "I", _read_exact(stream, 4))[0] != block_length:
            raise ProtocolDecodeError("PCAPNG block length mismatch")
        if block_type == 1:
            if len(body) < 8:
                raise ProtocolDecodeError("truncated PCAPNG interface description")
            link_type = struct.unpack_from(endian + "H", body)[0]
            timestamp_resolution = 1_000_000
            interface_name = None
            for code, value in _pcapng_options(body[8:], endian):
                if code == 2:
                    interface_name = value.decode("utf-8", errors="replace")
                elif code == 9:
                    if len(value) != 1:
                        raise ProtocolDecodeError("invalid PCAPNG timestamp resolution")
                    encoded = value[0]
                    timestamp_resolution = 2 ** (encoded & 0x7F) if encoded & 0x80 else 10**encoded
            link_types.append(link_type)
            timestamp_resolutions.append(timestamp_resolution)
            interface_names.append(interface_name)
        elif block_type == 6:
            if len(body) < 20:
                raise ProtocolDecodeError("truncated PCAPNG enhanced packet")
            interface_id, high, low, captured_length, original_length = struct.unpack_from(
                endian + "IIIII", body
            )
            if interface_id >= len(link_types) or link_types[interface_id] != 1:
                continue
            padded_length = (captured_length + 3) & ~3
            if 20 + padded_length > len(body):
                raise ProtocolDecodeError("truncated PCAPNG packet data")
            ticks = (high << 32) | low
            resolution = timestamp_resolutions[interface_id]
            yield CapturedPacket(
                ticks * 1_000_000_000 // resolution,
                original_length,
                body[20 : 20 + captured_length],
                interface_id,
                interface_names[interface_id],
            )


def read_capture(path: str | Path) -> Iterator[CapturedPacket]:
    with Path(path).open("rb") as stream:
        magic = _read_exact(stream, 4)
        if magic in _PCAP_MAGIC:
            yield from _iter_pcap(stream, magic)
        elif magic == _PCAPNG_MAGIC:
            yield from _iter_pcapng(stream)
        else:
            raise ProtocolDecodeError("unsupported capture-file magic")


def decode_prism_payload(payload: bytes) -> DecodedPrismPacket:
    word = ControlWord.unpack(payload[:2])
    if word.opcode == Opcode.CONTROL:
        frame = ControlFrame.unpack(payload)
        return DecodedPrismPacket(word.opcode, frame.header, frame.payload)
    if word.opcode == Opcode.COL_DATA:
        data_header, body = DataHeader.unpack(payload)
        return DecodedPrismPacket(word.opcode, data_header, body)
    if word.opcode == Opcode.COL_RES:
        result_header, body = ResultHeader.unpack(payload)
        return DecodedPrismPacket(word.opcode, result_header, body)
    if word.opcode == Opcode.COL_PROGRESS:
        # The bitmap length is encoded in the header; remove only Ethernet pad.
        if len(payload) < 42:
            raise ProtocolDecodeError("truncated progress packet")
        ack_bits = int.from_bytes(payload[32:34], "big")
        logical_length = 42 + ((ack_bits + 7) // 8)
        progress_header, bitmap = ProgressHeader.unpack(payload[:logical_length])
        return DecodedPrismPacket(word.opcode, progress_header, bitmap)
    raise ProtocolDecodeError(f"unsupported PRISM opcode {word.opcode!r}")


def _mac(value: bytes) -> str:
    return ":".join(f"{octet:02x}" for octet in value)


def decode_ethernet(capture: CapturedPacket) -> EthernetPacket:
    frame = capture.data
    if len(frame) < 14:
        raise ProtocolDecodeError("truncated Ethernet header")
    destination, source = _mac(frame[:6]), _mac(frame[6:12])
    offset = 12
    ethertype = int.from_bytes(frame[offset : offset + 2], "big")
    offset += 2
    vlan_tags: list[int] = []
    while ethertype in (0x8100, 0x88A8):
        if len(frame) < offset + 4:
            raise ProtocolDecodeError("truncated VLAN header")
        vlan_tags.append(int.from_bytes(frame[offset : offset + 2], "big"))
        ethertype = int.from_bytes(frame[offset + 2 : offset + 4], "big")
        offset += 4
    payload = frame[offset:]
    prism = decode_prism_payload(payload) if ethertype == ETHERTYPE else None
    return EthernetPacket(capture, destination, source, ethertype, tuple(vlan_tags), payload, prism)


def iter_prism_packets(path: str | Path, *, strict: bool = False) -> Iterator[EthernetPacket]:
    for capture in read_capture(path):
        try:
            packet = decode_ethernet(capture)
        except ProtocolDecodeError:
            if strict:
                raise
            continue
        if packet.prism is not None:
            yield packet


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Enum):
        return value.name
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(cast(Any, value)).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value


def packet_as_json(packet: EthernetPacket) -> str:
    assert packet.prism is not None
    return json.dumps(
        {
            "timestamp_ns": packet.capture.timestamp_ns,
            "interface_id": packet.capture.interface_id,
            "interface_name": packet.capture.interface_name,
            "source": packet.source,
            "destination": packet.destination,
            "opcode": packet.prism.opcode.name,
            "header": _json_value(packet.prism.header),
            "payload_hex": packet.prism.payload.hex(),
        },
        sort_keys=True,
    )


def load_operation_contexts(path: str | Path) -> dict[str, OperationDecodeContext]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    result: dict[str, OperationDecodeContext] = {}
    for item in document.get("operations", []):
        identity = OperationIdentity(
            int(item["job_id"]),
            int(item["group_id"]),
            int(item["group_generation"]),
            int(item["operation_id"]),
            int(item["operation_generation"]),
        )
        context = OperationDecodeContext(
            identity,
            WireFormat[item["input_format"]]
            if isinstance(item["input_format"], str)
            else WireFormat(item["input_format"]),
            WireFormat[item["output_format"]]
            if isinstance(item["output_format"], str)
            else WireFormat(item["output_format"]),
            int(item["element_count"]),
        )
        result[identity_key(identity)] = context
    return result


def decode_numeric_values(
    packet: DecodedPrismPacket,
    contexts: dict[str, OperationDecodeContext],
) -> tuple[list[dict[str, object]] | None, str | None]:
    header = packet.header
    if isinstance(header, DataHeader):
        wire_format = contexts.get(identity_key(header.identity))
        selected_format = wire_format.input_format if wire_format else None
    elif isinstance(header, ResultHeader):
        wire_format = contexts.get(identity_key(header.identity))
        selected_format = wire_format.output_format if wire_format else None
    else:
        return None, None
    if wire_format is None or selected_format is None:
        return None, "numeric format requires operation context"
    bytes_per_element = BYTES_PER_ELEMENT[selected_format]
    elements_per_chunk = CHUNK_PAYLOAD_BYTES // bytes_per_element
    logical_bytes = expected_payload_bytes(
        wire_format.element_count, elements_per_chunk, header.chunk_index, selected_format
    )
    payload = packet.payload[:logical_bytes]
    values: list[dict[str, object]] = []
    for offset in range(0, len(payload), bytes_per_element):
        bits = int.from_bytes(payload[offset : offset + bytes_per_element], "little")
        decoded = decode_bits(bits, selected_format)
        value = decoded.value
        values.append(
            {
                "bits": f"0x{bits:0{bytes_per_element * 2}x}",
                "kind": decoded.kind,
                "sign": decoded.sign,
                "value": None if value is None else str(value),
            }
        )
    return values, None


def packet_record(
    packet: EthernetPacket,
    *,
    port: int | None = None,
    direction: str | None = None,
    first_timestamp_ns: int | None = None,
    clock_hz: int | None = None,
    contexts: dict[str, OperationDecodeContext] | None = None,
) -> dict[str, object]:
    assert packet.prism is not None
    interface = packet.capture.interface_name
    inferred = re.fullmatch(r"port(\d+)_(rx|tx)", interface or "")
    if inferred is not None:
        if port is None:
            port = int(inferred.group(1))
        if direction is None:
            direction = inferred.group(2)
    values, note = decode_numeric_values(packet.prism, contexts or {})
    cycle = None
    if clock_hz is not None and first_timestamp_ns is not None:
        cycle = (packet.capture.timestamp_ns - first_timestamp_ns) * clock_hz // 1_000_000_000
    record: dict[str, object] = {
        "timestamp_ns": packet.capture.timestamp_ns,
        "cycle": cycle,
        "interface_id": packet.capture.interface_id,
        "interface_name": interface,
        "port": port,
        "direction": direction,
        "source": packet.source,
        "destination": packet.destination,
        "ethertype": f"0x{packet.ethertype:04x}",
        "version": "1.0",
        "opcode": packet.prism.opcode.name,
        "header": _json_value(packet.prism.header),
        "payload_length": len(packet.prism.payload),
        "payload_hex": packet.prism.payload.hex(),
        "decoded_values": values,
        "decode_note": note,
        "validation_error": None,
    }
    return record


def capture_summary(records: Sequence[dict[str, object]]) -> dict[str, object]:
    return {
        "packets": len(records),
        "opcodes": dict(Counter(str(record["opcode"]) for record in records)),
        "validation_errors": sum(record["validation_error"] is not None for record in records),
        "accumulation_inexact_packets": sum(
            "ACCUMULATION_INEXACT" in str(record["header"]) for record in records
        ),
    }


def write_pcap(
    path: str | Path,
    frames: Sequence[bytes | tuple[int, bytes]],
    *,
    timestamp_ns: int = 0,
) -> None:
    """Write deterministic classic-PCAP fixtures without requiring Scapy."""
    with Path(path).open("wb") as stream:
        stream.write(struct.pack("<IHHIIII", 0xA1B23C4D, 2, 4, 0, 0, 65535, 1))
        for index, item in enumerate(frames):
            if isinstance(item, tuple):
                packet_time, frame = item
            else:
                packet_time, frame = timestamp_ns + index, item
            seconds, nanoseconds = divmod(packet_time, 1_000_000_000)
            stream.write(struct.pack("<IIII", seconds, nanoseconds, len(frame), len(frame)))
            stream.write(frame)


def _pcapng_option(code: int, value: bytes) -> bytes:
    padding = bytes((-len(value)) % 4)
    return struct.pack("<HH", code, len(value)) + value + padding


def _write_pcapng_block(stream: BinaryIO, block_type: int, body: bytes) -> None:
    if len(body) % 4:
        raise ValueError("PCAPNG block body must be 32-bit aligned")
    total_length = 12 + len(body)
    stream.write(struct.pack("<II", block_type, total_length))
    stream.write(body)
    stream.write(struct.pack("<I", total_length))


def write_pcapng(
    path: str | Path,
    interface_names: Sequence[str],
    packets: Sequence[CapturedPacket],
) -> None:
    """Write a nanosecond-resolution, multi-interface PCAPNG capture."""
    if not interface_names:
        raise ValueError("PCAPNG capture requires at least one interface")
    if any(not name for name in interface_names) or len(set(interface_names)) != len(
        interface_names
    ):
        raise ValueError("PCAPNG interface names must be non-empty and unique")

    with Path(path).open("wb") as stream:
        _write_pcapng_block(stream, 0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
        for name in interface_names:
            options = (
                _pcapng_option(2, name.encode("utf-8"))
                + _pcapng_option(9, b"\x09")
                + _pcapng_option(0, b"")
            )
            _write_pcapng_block(stream, 1, struct.pack("<HHI", 1, 0, 65535) + options)

        for packet in packets:
            if packet.interface_id < 0 or packet.interface_id >= len(interface_names):
                raise ValueError("PCAPNG packet references an unknown interface")
            if packet.timestamp_ns < 0:
                raise ValueError("PCAPNG packet timestamp must be non-negative")
            if packet.original_length < len(packet.data):
                raise ValueError("PCAPNG original packet length is smaller than captured data")
            timestamp_high = packet.timestamp_ns >> 32
            timestamp_low = packet.timestamp_ns & 0xFFFF_FFFF
            packet_padding = bytes((-len(packet.data)) % 4)
            body = struct.pack(
                "<IIIII",
                packet.interface_id,
                timestamp_high,
                timestamp_low,
                len(packet.data),
                packet.original_length,
            )
            _write_pcapng_block(stream, 6, body + packet.data + packet_padding)
