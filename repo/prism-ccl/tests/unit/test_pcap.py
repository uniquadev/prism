from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prism_ccl.analysis.pcap import (
    capture_summary,
    decode_ethernet,
    iter_prism_packets,
    packet_as_json,
    packet_record,
    read_capture,
    write_pcap,
)
from prism_ccl.protocol.constants import ETHERTYPE, DataFlag, Opcode
from prism_ccl.protocol.serialization import DataHeader, OperationIdentity


class PcapTests(unittest.TestCase):
    def test_golden_dut_capture_is_parseable(self) -> None:
        fixture = Path(__file__).parents[2] / "wireshark" / "examples" / "allreduce_result.pcap"
        packets = list(iter_prism_packets(fixture))
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].prism.opcode, Opcode.COL_RES)
        self.assertEqual(packets[0].prism.header.result_path_id, 1)
        self.assertEqual(packets[0].prism.header.chunk_index, 0)

    def test_classic_pcap_round_trip_and_decode(self) -> None:
        identity = OperationIdentity(1, 2, 3, 4, 5)
        prism = DataHeader(identity, 6, 7, DataFlag.ACK_REQUIRED).pack(b"\x3f\x80\x00\x00")
        ethernet = bytes.fromhex("025052495301025052495300") + ETHERTYPE.to_bytes(2, "big") + prism
        with tempfile.TemporaryDirectory() as directory:
            capture_path = Path(directory) / "prism.pcap"
            write_pcap(capture_path, [ethernet], timestamp_ns=2_000_003_000)
            captures = list(read_capture(capture_path))
            self.assertEqual(len(captures), 1)
            packet = decode_ethernet(captures[0])
            self.assertEqual(packet.source, "02:50:52:49:53:00")
            self.assertEqual(packet.prism.opcode, Opcode.COL_DATA)
            self.assertEqual(packet.prism.header.chunk_index, 7)
            self.assertEqual(packet.prism.payload, b"\x3f\x80\x00\x00")
            self.assertIn('"opcode": "COL_DATA"', packet_as_json(packet))
            self.assertEqual(list(iter_prism_packets(capture_path)), [packet])
            record = packet_record(
                packet,
                port=0,
                direction="rx",
                first_timestamp_ns=packet.capture.timestamp_ns,
                clock_hz=250_000_000,
            )
            self.assertEqual(record["cycle"], 0)
            self.assertEqual(record["decode_note"], "numeric format requires operation context")
            self.assertEqual(capture_summary([record])["packets"], 1)

    def test_non_prism_frames_are_filtered(self) -> None:
        ethernet = bytes(12) + b"\x08\x00" + bytes(46)
        with tempfile.TemporaryDirectory() as directory:
            capture_path = Path(directory) / "other.pcap"
            write_pcap(capture_path, [ethernet])
            self.assertEqual(list(iter_prism_packets(capture_path)), [])


if __name__ == "__main__":
    unittest.main()
