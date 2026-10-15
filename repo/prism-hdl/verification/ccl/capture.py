"""Per-test PCAP ownership for frames observed at DUT boundaries."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

CapturedFrame = tuple[int, bytes]

_DIRECTION_ORDER = {"rx": 0, "tx": 1}
_PCAP_HEADER = struct.Struct("<IHHIIII")
_PCAP_RECORD = struct.Struct("<IIII")


def _write_pcap(path: Path, frames: list[CapturedFrame]) -> None:
    """Preserve nanosecond simulator timestamps in a standard PCAP stream."""
    with path.open("wb") as output:
        output.write(_PCAP_HEADER.pack(0xA1B23C4D, 2, 4, 0, 0, 65535, 1))
        for timestamp_ns, frame in frames:
            seconds, nanoseconds = divmod(timestamp_ns, 1_000_000_000)
            output.write(_PCAP_RECORD.pack(seconds, nanoseconds, len(frame), len(frame)))
            output.write(frame)


def _option(code: int, value: bytes) -> bytes:
    return struct.pack("<HH", code, len(value)) + value + bytes((-len(value)) % 4)


def _block(output: BinaryIO, kind: int, body: bytes) -> None:
    if len(body) % 4:
        raise ValueError("PCAPNG body must be 32-bit aligned")
    size = len(body) + 12
    output.write(struct.pack("<II", kind, size))
    output.write(body)
    output.write(struct.pack("<I", size))


def _write_pcapng(
    path: Path,
    streams: list[tuple[int, str]],
    frames: list[tuple[int, int, int, int, bytes]],
) -> None:
    """Write one nanosecond-resolution interface per physical port/direction."""
    with path.open("wb") as output:
        _block(output, 0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
        for port, direction in streams:
            options = (
                _option(2, f"port{port}_{direction}".encode())
                + _option(9, b"\x09")
                + _option(0, b"")
            )
            _block(output, 1, struct.pack("<HHI", 1, 0, 65535) + options)
        interface_ids = {stream: index for index, stream in enumerate(streams)}
        for timestamp_ns, port, direction_order, _sequence, data in sorted(frames):
            direction = "rx" if direction_order == 0 else "tx"
            interface_id = interface_ids[(port, direction)]
            body = struct.pack(
                "<IIIII",
                interface_id,
                timestamp_ns >> 32,
                timestamp_ns & 0xFFFF_FFFF,
                len(data),
                len(data),
            )
            _block(output, 6, body + data + bytes((-len(data)) % 4))


@dataclass(slots=True)
class ObservedCapture:
    """Collect observed frames and write the per-port capture layout."""

    root: Path
    test_name: str | None = None
    frames: dict[tuple[int, str], list[CapturedFrame]] = field(default_factory=dict)

    def record(self, *, port: int, direction: str, frame: CapturedFrame) -> None:
        if port < 0:
            raise ValueError("capture port must be non-negative")
        if direction not in _DIRECTION_ORDER:
            raise ValueError("capture direction must be 'rx' or 'tx'")
        timestamp_ns, data = frame
        if timestamp_ns < 0:
            raise ValueError("capture timestamp must be non-negative")
        if not data:
            raise ValueError("captured frame must not be empty")
        self.frames.setdefault((port, direction), []).append(frame)

    def write(self) -> tuple[Path, ...]:
        output = self.root / self.test_name if self.test_name else self.root
        output.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        streams = sorted(self.frames, key=lambda stream: (stream[0], _DIRECTION_ORDER[stream[1]]))
        aggregate: list[tuple[int, int, int, int, bytes]] = []
        for port, direction in streams:
            frames = self.frames[(port, direction)]
            path = output / f"port{port}_{direction}.pcap"
            _write_pcap(path, frames)
            paths.append(path)
            aggregate.extend(
                (timestamp_ns, port, _DIRECTION_ORDER[direction], sequence, data)
                for sequence, (timestamp_ns, data) in enumerate(frames)
            )

        if streams:
            aggregate_path = output / "all_ports.pcapng"
            _write_pcapng(aggregate_path, streams, aggregate)
            paths.append(aggregate_path)
        return tuple(paths)
