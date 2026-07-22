from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from prism_ccl.analysis.pcap import write_pcap
from prism_ccl.cli.pcap_dump import main
from prism_ccl.protocol.constants import ETHERTYPE, DataFlag
from prism_ccl.protocol.serialization import DataHeader, OperationIdentity


class PcapCliTests(unittest.TestCase):
    @staticmethod
    def fixture(directory: str) -> tuple[Path, OperationIdentity]:
        identity = OperationIdentity(1, 2, 3, 4, 5)
        prism = DataHeader(identity, 6, 0, DataFlag(0)).pack(b"\x00\x00\x80\x3f")
        ethernet = bytes.fromhex("025052495301025052495300") + ETHERTYPE.to_bytes(2, "big") + prism
        capture = Path(directory) / "port3_rx.pcap"
        write_pcap(capture, [ethernet], timestamp_ns=8)
        return capture, identity

    @staticmethod
    def run_cli(*arguments: str) -> str:
        output = StringIO()
        with patch.object(sys, "argv", ["prism-pcap", *arguments]), redirect_stdout(output):
            main()
        return output.getvalue()

    def test_text_and_summary_formats_infer_capture_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture, _identity = self.fixture(directory)
            text = self.run_cli(str(capture))
            self.assertIn("port=3/rx", text)
            self.assertIn("note: numeric format requires operation context", text)

            summary = json.loads(self.run_cli(str(capture), "--format", "summary"))
            self.assertEqual(summary["packets"], 1)
            self.assertEqual(summary["opcodes"], {"COL_DATA": 1})

    def test_json_format_decodes_values_with_explicit_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture, identity = self.fixture(directory)
            context = Path(directory) / "operations.json"
            context.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "job_id": identity.job_id,
                                "group_id": identity.group_id,
                                "group_generation": identity.group_generation,
                                "operation_id": identity.operation_id,
                                "operation_generation": identity.operation_generation,
                                "input_format": "FP32",
                                "output_format": 4,
                                "element_count": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            record = json.loads(
                self.run_cli(
                    str(capture),
                    "--format",
                    "json",
                    "--context",
                    str(context),
                    "--port",
                    "7",
                    "--direction",
                    "tx",
                    "--clock-hz",
                    "100000000",
                    "--strict",
                )
            )
            self.assertEqual((record["port"], record["direction"]), (7, "tx"))
            self.assertEqual(record["decoded_values"][0]["value"], "1")
            self.assertIsNone(record["decode_note"])


if __name__ == "__main__":
    unittest.main()
