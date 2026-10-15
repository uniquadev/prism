from __future__ import annotations

import json
import struct
import sys

import pytest

from prism_ccl.analysis import inspect_frame, read_pcap, write_pcap
from prism_ccl.cli.pcap_dump import main
from prism_ccl.examples import hierarchical_example
from prism_ccl.wire.data import PacketClass


def test_capture_uses_standard_ethernet_pcap_header_and_actual_frames(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(tmp_path) / "hierarchical.pcap"
    result = hierarchical_example(length=10)
    write_pcap(path, result.frames)
    raw = path.read_bytes()
    assert raw[:24] == bytes.fromhex("d4c3b2a1 0200 0400 00000000 00000000 ffff0000 01000000")
    captured = list(read_pcap(path))
    assert len(captured) == sum(event.delivered for event in result.frames)
    assert all(timestamp >= 0 for timestamp, _frame in captured)
    records = [inspect_frame(frame) for _timestamp, frame in captured]
    assert any(record["class"] == "DATA" and record["groups"] for record in records)
    assert any(record["class"] == "CONTROL" for record in records)
    staged = [record for record in records if record.get("command") == "STAGE"]
    assert staged and all(record["context"]["bindings"] for record in staged)
    assert all(record["context"]["manager_mac"] for record in staged)
    assert any(record["class"] == "PROGRESS" for record in records)
    assert any(record["class"] == "RESULT" for record in records)
    assert all(event.packet_class in PacketClass for event in result.frames)


def test_cli_and_truncated_capture(tmp_path: object, monkeypatch: object, capsys: object) -> None:
    from pathlib import Path

    path = Path(tmp_path) / "single.pcap"
    from prism_ccl.examples import single_example

    write_pcap(path, single_example().frames)
    monkeypatch.setattr(sys, "argv", ["prism-pcap", str(path)])  # type: ignore[attr-defined]
    main()
    lines = capsys.readouterr().out.splitlines()  # type: ignore[attr-defined]
    assert lines and json.loads(lines[0])["class"] == "CONTROL"
    truncated = Path(tmp_path) / "truncated.pcap"
    truncated.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="truncated"):
        list(read_pcap(truncated))


def test_simulator_nanosecond_capture_is_readable(tmp_path: object) -> None:
    from pathlib import Path

    from prism_ccl.examples import single_example

    frame = next(event.frame for event in single_example().frames if event.delivered)
    path = Path(tmp_path) / "port0_tx.pcap"
    path.write_bytes(
        struct.pack("<IHHIIII", 0xA1B23C4D, 2, 4, 0, 0, 65535, 1)
        + struct.pack("<IIII", 0, 1_234_567, len(frame), len(frame))
        + frame
    )
    assert list(read_pcap(path)) == [(1234, frame)]
    assert inspect_frame(frame)["class"] == "CONTROL"
