"""Structural tests for per-stream and aggregate DUT-observed captures."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ccl.capture import ObservedCapture
from prism_ccl.analysis.pcap import read_capture


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
            self.assertEqual([packet.timestamp_ns for packet in packets], [10, 15, 20, 20])
            self.assertEqual(
                [packet.data for packet in packets],
                [b"port0-rx-at-10", b"port0-tx-at-15", b"port0-rx-at-20", b"port1-tx-at-20"],
            )
            self.assertEqual(
                [packet.interface_name for packet in packets],
                ["port0_rx", "port0_tx", "port0_rx", "port1_tx"],
            )
            self.assertEqual([packet.interface_id for packet in packets], [0, 1, 0, 2])

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
