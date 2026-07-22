"""End-to-end tests for the CCL-owned Wireshark dissector."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from prism_ccl.analysis.pcap import write_pcap
from prism_ccl.protocol.constants import (
    ETHERTYPE,
    AccumulatorProfile,
    CapabilityKey,
    CollectiveSemantic,
    ControlCommand,
    ControlFlag,
    DataFlag,
    PartialWireFormat,
    ReductionOperator,
    TlvType,
    WireFormat,
)
from prism_ccl.protocol.models import OperationDescriptor, ResultRangeRoute
from prism_ccl.protocol.serialization import (
    ControlFrame,
    ControlHeader,
    DataHeader,
    GroupHandleWire,
    OperationHandleWire,
    OperationIdentity,
    ProtocolVersionRange,
    Tlv,
)

CCL_ROOT = Path(__file__).resolve().parents[2]
DISSECTOR = CCL_ROOT / "wireshark" / "prism.lua"
GOLDEN_CAPTURE = CCL_ROOT / "wireshark" / "examples" / "allreduce_result.pcap"


class WiresharkDissectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tshark = shutil.which("tshark")
        if tshark is None:
            raise RuntimeError("tshark is required for the Wireshark test suite")
        cls.tshark = tshark
        cls.wireshark_config = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.wireshark_config.cleanup)

    def fields(self, capture: Path, *names: str) -> list[str]:
        command = [
            self.tshark,
            "-X",
            f"lua_script:{DISSECTOR}",
            "-r",
            str(capture),
            "-T",
            "fields",
        ]
        for name in names:
            command.extend(("-e", name))
        environment = os.environ.copy()
        environment["WIRESHARK_CONFIG_DIR"] = self.wireshark_config.name
        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )
        return result.stdout.strip().lower().split("\t")

    def verbose(self, capture: Path) -> str:
        environment = os.environ.copy()
        environment["WIRESHARK_CONFIG_DIR"] = self.wireshark_config.name
        result = subprocess.run(
            [
                self.tshark,
                "-X",
                f"lua_script:{DISSECTOR}",
                "-r",
                str(capture),
                "-V",
            ],
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )
        return result.stdout

    @staticmethod
    def ethernet(payload: bytes) -> bytes:
        return bytes.fromhex("025052495301025052495300") + ETHERTYPE.to_bytes(2, "big") + payload

    def test_flags_and_chunk_fields(self) -> None:
        header = DataHeader(
            OperationIdentity(1, 2, 3, 4, 5),
            6,
            7,
            DataFlag.ACK_REQUIRED | DataFlag.ACCUMULATION_INEXACT,
        )
        packet = header.pack(b"\0\0\0\0", allow_accumulation_inexact=True)
        ethernet = self.ethernet(packet)
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "flags.pcap"
            write_pcap(capture, [ethernet])
            fields = self.fields(
                capture,
                "prism.opcode",
                "prism.chunk_index",
                "prism.flags.accumulation_inexact",
            )
        self.assertEqual(len(fields), 3)
        self.assertIn(fields[0], {"0x02", "2"})
        self.assertEqual(fields[1], "7")
        self.assertIn(fields[2], {"1", "true"})

    def test_dut_observed_result_fixture(self) -> None:
        fields = self.fields(
            GOLDEN_CAPTURE,
            "prism.opcode",
            "prism.peer_id",
            "prism.chunk_index",
        )
        self.assertEqual(fields, ["0x03", "1", "0"])

    def test_control_command_and_operation_tlvs_are_descriptive(self) -> None:
        descriptor = OperationDescriptor(
            CollectiveSemantic.REDUCE,
            ReductionOperator.SUM,
            WireFormat.FP32,
            AccumulatorProfile.FP32_ORDERED,
            PartialWireFormat.FP32,
            WireFormat.FP32,
            4,
            2,
            1,
            2,
            1000,
            3,
            True,
            (ResultRangeRoute(0, 0, 1),),
        )
        frame = ControlFrame.from_tlvs(
            ControlHeader(
                0x1234,
                7,
                ControlCommand.OP_PREPARE,
                ControlFlag.REQUEST | ControlFlag.ACK_REQUIRED,
            ),
            (
                Tlv(TlvType.GROUP_HANDLE, GroupHandleWire(2, 1).pack()),
                Tlv(TlvType.OPERATION_HANDLE, OperationHandleWire(3, 1).pack()),
                *descriptor.management_tlvs(),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "control.pcap"
            write_pcap(capture, [self.ethernet(frame.pack())])
            fields = self.fields(
                capture,
                "_ws.col.Info",
                "prism.control.command",
                "prism.operation.semantic",
                "prism.operation.accumulator_profile",
                "prism.operation.element_count",
                "prism.operation.route.first_chunk",
            )
        self.assertTrue(fields[0].startswith("op_prepare"))
        self.assertIn(fields[1], {"0x0200", "512"})
        self.assertEqual(fields[2:], ["1", "2", "4", "0"])

    def test_capability_vector_entries_are_decoded(self) -> None:
        capabilities = b"".join(
            (
                struct.pack("!HHQI", int(CapabilityKey.MAX_SESSIONS), 0, 8, 0),
                struct.pack(
                    "!HHQI",
                    int(CapabilityKey.SUPPORTED_INPUT_FORMATS),
                    0,
                    1 << int(WireFormat.FP32),
                    0,
                ),
                struct.pack(
                    "!HHQI",
                    int(CapabilityKey.SUPPORTED_ACCUMULATOR_PROFILES),
                    0,
                    (1 << int(AccumulatorProfile.FP32_ARRIVAL))
                    | (1 << int(AccumulatorProfile.FP32_ORDERED)),
                    0,
                ),
                struct.pack(
                    "!HHQI",
                    int(CapabilityKey.SUPPORTED_PARTIAL_FORMATS),
                    0,
                    1 << int(PartialWireFormat.FP32),
                    0,
                ),
                struct.pack(
                    "!HHQI",
                    int(CapabilityKey.SUPPORTED_OUTPUT_FORMATS),
                    0,
                    (1 << int(WireFormat.FP16)) | (1 << int(WireFormat.FP32)),
                    0,
                ),
            )
        )
        frame = ControlFrame.from_tlvs(
            ControlHeader(0, 8, ControlCommand.CAPS_RESPONSE, ControlFlag.RESPONSE),
            (
                Tlv.u64(TlvType.DEVICE_BOOT_ID, 1),
                Tlv(TlvType.PROTOCOL_VERSION_RANGE, ProtocolVersionRange(1, 0, 1, 0).pack()),
                Tlv(TlvType.CAPABILITIES, capabilities),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capabilities.pcap"
            write_pcap(capture, [self.ethernet(frame.pack())])
            fields = self.fields(
                capture,
                "_ws.col.Info",
                "prism.capability.key",
                "prism.entry.value",
                "prism.capability.supported_input_formats",
                "prism.capability.supported_accumulator_profiles",
                "prism.capability.supported_partial_formats",
                "prism.capability.supported_output_formats",
            )
            verbose = self.verbose(capture)
        self.assertTrue(fields[0].startswith("caps_response"))
        self.assertIn("0x0001", fields[1])
        self.assertIn("0x0014", fields[1])
        self.assertIn("8", fields[2])
        self.assertIn(fields[3], {"0x0000000000000010", "16"})
        self.assertIn(fields[4], {"0x0000000000000006", "6"})
        self.assertIn(fields[5], {"0x0000000000000010", "16"})
        self.assertIn(fields[6], {"0x0000000000000014", "20"})
        self.assertIn("Supported input formats", verbose)
        self.assertIn("FP32_ARRIVAL", verbose)
        self.assertIn("FP32", verbose)
        self.assertIn("FP16, FP32", verbose)


if __name__ == "__main__":
    unittest.main()
