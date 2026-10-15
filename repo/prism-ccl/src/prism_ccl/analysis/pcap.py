"""PRISM capture generation and inspection at the Ethernet frame boundary."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..application.software import FrameEvent
from ..wire.control import ContextRecord, ControlCommand, ControlStatus, decode_control_frame
from ..wire.data import ETHERTYPE, PacketClass, decode_data_frame
from ..wire.progress import decode_progress_frame

_GLOBAL = struct.Struct("<IHHIIII")
_RECORD = struct.Struct("<IIII")
_PCAP_MAGIC = 0xA1B2C3D4
_PCAP_NANO_MAGIC = 0xA1B23C4D
_LINKTYPE_ETHERNET = 1


def write_pcap(
    path: str | Path,
    events: Iterable[FrameEvent],
    *,
    simulated_tick_ns: int = 4,
    include_dropped: bool = False,
) -> None:
    """PCAP timestamps are simulated time, never host wall-clock time."""
    if simulated_tick_ns <= 0:
        raise ValueError("simulated tick duration must be positive")
    with Path(path).open("wb") as output:
        output.write(_GLOBAL.pack(_PCAP_MAGIC, 2, 4, 0, 0, 65535, _LINKTYPE_ETHERNET))
        for event in events:
            if not event.delivered and not include_dropped:
                continue
            microseconds = event.tick * simulated_tick_ns // 1000
            seconds, fraction = divmod(microseconds, 1_000_000)
            output.write(_RECORD.pack(seconds, fraction, len(event.frame), len(event.frame)))
            output.write(event.frame)


def read_pcap(path: str | Path) -> Iterator[tuple[int, bytes]]:
    with Path(path).open("rb") as source:
        header = source.read(_GLOBAL.size)
        if len(header) != _GLOBAL.size:
            raise ValueError("truncated PCAP global header")
        magic, major, minor, _zone, _precision, snaplen, link_type = _GLOBAL.unpack(header)
        if magic not in (_PCAP_MAGIC, _PCAP_NANO_MAGIC) or (major, minor, link_type) != (
            2,
            4,
            _LINKTYPE_ETHERNET,
        ):
            raise ValueError("unsupported PCAP byte order, version or link type")
        precision = 1_000_000_000 if magic == _PCAP_NANO_MAGIC else 1_000_000
        while record := source.read(_RECORD.size):
            if len(record) != _RECORD.size:
                raise ValueError("truncated PCAP record header")
            seconds, subseconds, included, original = _RECORD.unpack(record)
            if included > snaplen or included > original or subseconds >= precision:
                raise ValueError("invalid PCAP record dimensions")
            frame = source.read(included)
            if len(frame) != included:
                raise ValueError("truncated PCAP frame")
            timestamp_us = seconds * 1_000_000 + (
                subseconds // 1000 if magic == _PCAP_NANO_MAGIC else subseconds
            )
            yield timestamp_us, frame


def inspect_frame(frame: bytes, *, mtu: int = 1500, kulisch_bits: int = 279) -> dict[str, Any]:
    if len(frame) < 16 or int.from_bytes(frame[12:14], "big") != ETHERTYPE:
        raise ValueError("not a PRISM Ethernet frame")
    try:
        packet_class = PacketClass(frame[15])
    except ValueError as error:
        raise ValueError("unknown PRISM packet class") from error
    common: dict[str, Any] = {
        "source_mac": frame[6:12].hex(":"),
        "destination_mac": frame[0:6].hex(":"),
        "class": packet_class.name,
    }
    if packet_class in (PacketClass.DATA, PacketClass.RESULT):
        data_packet = decode_data_frame(frame, mtu=mtu, kulisch_bits=kulisch_bits)
        return {
            **common,
            "operation": asdict(data_packet.operation),
            "source_endpoint": data_packet.source_endpoint,
            "destination_endpoint": data_packet.destination_endpoint,
            "stream_id": data_packet.stream_id,
            "packet_id": data_packet.packet_id,
            "first_element": data_packet.first_element,
            "element_count": data_packet.element_count,
            "last": data_packet.last,
            "groups": [
                {"format": group.format.name, "count": len(group.values)}
                for group in data_packet.groups
            ],
        }
    if packet_class == PacketClass.CONTROL:
        control_packet = decode_control_frame(frame, mtu=mtu)
        record = (
            ContextRecord.unpack(control_packet.body)
            if control_packet.command == ControlCommand.STAGE
            else None
        )
        return {
            **common,
            "operation": asdict(control_packet.operation),
            "transaction_id": control_packet.transaction_id,
            "command": control_packet.command.name,
            "status": control_packet.status,
            "status_name": (
                ControlStatus(control_packet.status).name
                if control_packet.status in ControlStatus._value2member_map_
                else "UNKNOWN"
            ),
            "context_role": record.role.name if record else None,
            "context": (
                {
                    "manager_mac": record.manager_mac.hex(":"),
                    "manager_port": record.manager_port,
                    "maximum_original_terms": record.maximum_original_terms,
                    "rank_formats": sorted(fmt.name for fmt in record.rank_formats),
                    "bindings": [
                        {
                            "local_endpoint": binding.local_endpoint,
                            "peer_endpoint": binding.peer_endpoint,
                            "local_port": binding.local_port,
                            "peer_kind": binding.peer_kind.name,
                            "peer_mac": binding.peer_mac.hex(":"),
                            "rank_id": binding.rank_id,
                            "original_terms": binding.original_terms,
                            "formats": sorted(fmt.name for fmt in binding.formats),
                            "result_enabled": binding.result_enabled,
                        }
                        for binding in record.bindings
                    ],
                }
                if record
                else None
            ),
        }
    progress_packet = decode_progress_frame(frame, mtu=mtu)
    return {
        **common,
        "operation": asdict(progress_packet.operation),
        "source_endpoint": progress_packet.source_endpoint,
        "destination_endpoint": progress_packet.destination_endpoint,
        "stream_id": progress_packet.stream_id,
        "packet_id": progress_packet.packet_id,
        "cumulative_element": progress_packet.cumulative_element,
        "credit_intervals": progress_packet.credit_intervals,
        "credit_bytes": progress_packet.credit_bytes,
        "status": progress_packet.status.name,
        "complete": progress_packet.complete,
        "holes": progress_packet.holes,
    }
