"""The Lua dissector consumes frames emitted by the public software example."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from prism_ccl.analysis import write_pcap
from prism_ccl.application.software import FrameEvent
from prism_ccl.domain.model import OperationKey
from prism_ccl.examples import hierarchical_example
from prism_ccl.wire.data import DataPacket, PacketClass, encode_data_frame

DISSECTOR = Path(__file__).resolve().parents[2] / "wireshark" / "prism.lua"


def test_tshark_decodes_numbergroups_and_control(tmp_path: Path) -> None:
    tshark = shutil.which("tshark")
    if tshark is None:
        pytest.skip("tshark is not installed")
    capture = tmp_path / "numbergroup.pcap"
    write_pcap(capture, hierarchical_example(length=12).frames)
    env = {**os.environ, "WIRESHARK_CONFIG_DIR": str(tmp_path / "wireshark-config")}
    result = subprocess.run(
        [
            tshark,
            "-X",
            f"lua_script:{DISSECTOR}",
            "-r",
            str(capture),
            "-T",
            "fields",
            "-e",
            "prism.opcode",
            "-e",
            "prism.first_element",
            "-e",
            "prism.group.format",
            "-e",
            "prism.group.elements",
            "-e",
            "prism.context.kulisch_bits",
            "-e",
            "prism.context.manager_port",
            "-e",
            "prism.binding.local_endpoint",
            "-e",
            "prism.binding.peer_mac",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Lua Error" not in result.stderr
    rows = [row.split("\t") for row in result.stdout.splitlines()]
    assert any(row[0] in {"0x02", "2"} and row[2] for row in rows)
    assert any(row[0] in {"0x03", "3"} and row[2] for row in rows)
    assert any(row[4] == "280" for row in rows)
    assert any(row[5] and row[6] and row[7] for row in rows)


def test_tshark_marks_terminal_arithmetic_error(tmp_path: Path) -> None:
    tshark = shutil.which("tshark")
    if tshark is None:
        pytest.skip("tshark is not installed")
    frame = encode_data_frame(
        DataPacket(
            PacketClass.RESULT,
            OperationKey(1, 1, 0, 1, 0),
            source_endpoint=1,
            destination_endpoint=2,
            stream_id=2,
            packet_id=1,
            first_element=0,
            groups=(),
            last=True,
            accumulation_inexact=True,
        ),
        destination_mac=bytes.fromhex("020000000002"),
        source_mac=bytes.fromhex("020000000001"),
        mtu=1500,
        kulisch_bits=320,
    )
    capture = tmp_path / "arithmetic-error.pcap"
    write_pcap(capture, (FrameEvent(0, "switch", "rank", PacketClass.RESULT, 1, (), frame, True),))
    env = {**os.environ, "WIRESHARK_CONFIG_DIR": str(tmp_path / "wireshark-config")}
    result = subprocess.run(
        [
            tshark,
            "-X",
            f"lua_script:{DISSECTOR}",
            "-r",
            str(capture),
            "-T",
            "fields",
            "-e",
            "prism.flags.accumulation_inexact",
            "-e",
            "_ws.col.Info",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Lua Error" not in result.stderr
    assert (
        result.stdout.strip()
        == "True\tRESULT packet=1 first=0 count=0 groups=0 ACCUMULATION_INEXACT"
    )
