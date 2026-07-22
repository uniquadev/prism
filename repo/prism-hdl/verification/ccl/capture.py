"""Per-test PCAP ownership for frames observed at DUT boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from prism_ccl.analysis.pcap import CapturedPacket, write_pcap, write_pcapng

CapturedFrame = tuple[int, bytes]

_DIRECTION_ORDER = {"rx": 0, "tx": 1}


@dataclass(slots=True)
class ObservedCapture:
    """Collect observed frames and write the required per-port capture layout."""

    root: Path
    test_name: str
    frames: dict[tuple[int, str], list[CapturedFrame]] = field(default_factory=dict)

    def record(self, *, port: int, direction: str, frame: CapturedFrame) -> None:
        if port < 0:
            raise ValueError("capture port must be non-negative")
        if direction not in {"rx", "tx"}:
            raise ValueError("capture direction must be 'rx' or 'tx'")
        timestamp_ns, data = frame
        if timestamp_ns < 0:
            raise ValueError("capture timestamp must be non-negative")
        if not data:
            raise ValueError("captured frame must not be empty")
        self.frames.setdefault((port, direction), []).append(frame)

    def write(self) -> tuple[Path, ...]:
        output = self.root / self.test_name
        output.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        streams = sorted(
            self.frames.items(), key=lambda item: (item[0][0], _DIRECTION_ORDER[item[0][1]])
        )
        interface_ids = {stream: index for index, (stream, _) in enumerate(streams)}
        aggregate: list[tuple[int, int, int, int, bytes]] = []
        for (port, direction), frames in streams:
            path = output / f"port{port}_{direction}.pcap"
            write_pcap(path, frames)
            paths.append(path)
            aggregate.extend(
                (timestamp_ns, port, _DIRECTION_ORDER[direction], sequence, data)
                for sequence, (timestamp_ns, data) in enumerate(frames)
            )

        if streams:
            aggregate_path = output / "all_ports.pcapng"
            ordered_packets = [
                CapturedPacket(
                    timestamp_ns=timestamp_ns,
                    original_length=len(data),
                    data=data,
                    interface_id=interface_ids[(port, "rx" if direction == 0 else "tx")],
                )
                for timestamp_ns, port, direction, _sequence, data in sorted(aggregate)
            ]
            write_pcapng(
                aggregate_path,
                [f"port{port}_{direction}" for (port, direction), _frames in streams],
                ordered_packets,
            )
            paths.append(aggregate_path)
        return tuple(paths)
