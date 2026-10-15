"""Structural tests for per-stream and aggregate DUT-observed captures."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ccl.capture import ObservedCapture


def read_capture(path: Path) -> list[tuple[int, int, str | None, bytes]]:
    """Inspect capture containers independently of the writer under test."""
    data = path.read_bytes()
    packets: list[tuple[int, int, str | None, bytes]] = []
    if path.suffix == ".pcap":
        assert data[:4] == b"\x4d\x3c\xb2\xa1"
        offset = 24
        while offset < len(data):
            seconds, nanoseconds, length, original = struct.unpack_from("<IIII", data, offset)
            assert length == original
            offset += 16
            packets.append(
                (seconds * 1_000_000_000 + nanoseconds, 0, None, data[offset : offset + length])
            )
            offset += length
        assert offset == len(data)
        return packets
    interfaces: list[str] = []
    offset = 0
    while offset < len(data):
        kind, size = struct.unpack_from("<II", data, offset)
        assert size >= 12 and size % 4 == 0
        assert struct.unpack_from("<I", data, offset + size - 4)[0] == size
        body = data[offset + 8 : offset + size - 4]
        if kind == 1:
            assert struct.unpack_from("<H", body)[0] == 1
            option_code, option_length = struct.unpack_from("<HH", body, 8)
            assert option_code == 2
            interfaces.append(body[12 : 12 + option_length].decode())
        elif kind == 6:
            interface_id, high, low, length, original = struct.unpack_from("<IIIII", body)
            assert length == original
            packets.append(
                ((high << 32) | low, interface_id, interfaces[interface_id], body[20 : 20 + length])
            )
        offset += size
    assert offset == len(data)
    return packets


class ObservedCaptureTests(unittest.TestCase):
    def test_aggregate_is_complete_and_temporally_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = ObservedCapture(Path(directory), "ordered")
            capture.record(port=1, direction="tx", frame=(20, b"port1-tx-at-20"))
            capture.record(port=0, direction="rx", frame=(10, b"port0-rx-at-10"))
            capture.record(port=0, direction="rx", frame=(20, b"port0-rx-at-20"))
            capture.record(port=0, direction="tx", frame=(15, b"port0-tx-at-15"))

            paths = capture.write()

            self.assertEqual(
                [path.name for path in paths],
                ["port0_rx.pcap", "port0_tx.pcap", "port1_tx.pcap", "all_ports.pcapng"],
            )
            packets = list(read_capture(paths[-1]))
            self.assertEqual([packet[0] for packet in packets], [10, 15, 20, 20])
            self.assertEqual(
                [packet[3] for packet in packets],
                [b"port0-rx-at-10", b"port0-tx-at-15", b"port0-rx-at-20", b"port1-tx-at-20"],
            )
            self.assertEqual(
                [packet[2] for packet in packets],
                ["port0_rx", "port0_tx", "port0_rx", "port1_tx"],
            )
            self.assertEqual([packet[1] for packet in packets], [0, 1, 0, 2])

            individual_count = sum(len(list(read_capture(path))) for path in paths[:-1])
            self.assertEqual(len(packets), individual_count)

    def test_record_rejects_invalid_capture_metadata(self) -> None:
        capture = ObservedCapture(Path("unused"), "invalid")
        with self.assertRaises(ValueError):
            capture.record(port=-1, direction="rx", frame=(0, b"frame"))
        with self.assertRaises(ValueError):
            capture.record(port=0, direction="sideways", frame=(0, b"frame"))
        with self.assertRaises(ValueError):
            capture.record(port=0, direction="rx", frame=(-1, b"frame"))
        with self.assertRaises(ValueError):
            capture.record(port=0, direction="rx", frame=(0, b""))


if __name__ == "__main__":
    unittest.main()
