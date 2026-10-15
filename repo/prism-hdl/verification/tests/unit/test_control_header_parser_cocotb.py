"""Independent fixed-header bytes for protocol 2.0 CONTROL parsing."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.triggers import Timer
from prism_ccl.domain.model import OperationKey
from prism_ccl.wire.control import ControlCommand, ControlPacket, encode_control_frame

GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 01 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0a0b0c0d 0102 0304 07 00 0000 00 01 "
    "000000000000000000000000"
)


@cocotb.test()
async def independent_control_header_offsets_and_handshake(dut: Any) -> None:
    assert len(GOLDEN) == 60
    dut.s_tdata.value = int.from_bytes(GOLDEN.ljust(64, b"\0"), "little")
    dut.s_tkeep.value = (1 << 60) - 1
    dut.s_valid.value = 1
    dut.m_ready.value = 0
    await Timer(1, unit="ps")
    assert int(dut.m_valid.value) == 1
    assert int(dut.s_ready.value) == 0
    assert int(dut.m_fixed_header_valid.value) == 1
    expected = {
        "m_job_id": 0x0102030405060708,
        "m_group_id": 0x1122,
        "m_group_generation": 0x3344,
        "m_operation_id": 0x5566,
        "m_operation_generation": 0x778899AA,
        "m_transaction_id": 0x0A0B0C0D,
        "m_source_endpoint": 0x0102,
        "m_destination_endpoint": 0x0304,
        "m_command": 7,
        "m_status": 0,
        "m_body_bytes": 0,
        "m_fragment_index": 0,
        "m_fragment_count": 1,
        "m_ingress_port": 7,
    }
    for field, value in expected.items():
        assert int(getattr(dut, field).value) == value, field
    dut.m_ready.value = 1
    await Timer(1, unit="ps")
    assert int(dut.s_ready.value) == 1
    dut.s_tkeep.value = ((1 << 60) - 1) ^ (1 << 47)
    await Timer(1, unit="ps")
    assert int(dut.m_fixed_header_valid.value) == 0


@cocotb.test()
async def production_codec_matches_independent_header(dut: Any) -> None:
    packet = ControlPacket(
        OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA),
        0x0A0B0C0D,
        0x0102,
        0x0304,
        ControlCommand.CAPS_QUERY,
    )
    encoded = encode_control_frame(
        packet,
        destination_mac=bytes.fromhex("001122334455"),
        source_mac=bytes.fromhex("66778899aabb"),
        mtu=1500,
    )
    assert encoded == GOLDEN
    dut.s_tdata.value = int.from_bytes(encoded.ljust(64, b"\0"), "little")
    dut.s_tkeep.value = (1 << len(encoded)) - 1
    dut.s_valid.value = 1
    dut.m_ready.value = 1
    await Timer(1, unit="ps")
    assert int(dut.m_transaction_id.value) == packet.transaction_id
    assert int(dut.m_command.value) == int(packet.command)
