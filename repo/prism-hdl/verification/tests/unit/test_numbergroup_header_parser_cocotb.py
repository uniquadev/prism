"""Fixed DATA/RESULT fields from independent and production NumberGroup bytes."""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.triggers import Timer
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.domain.numbers import decode_native, encode_kulisch
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    encode_data_frame,
)

GOLDEN = bytes.fromhex(
    "001122334455 66778899aabb 88b5 20 02 "
    "0102030405060708 1122 3344 5566 778899aa "
    "0102 0304 0a0b0c0d 00000009 0003 02 01 0010 0f10 0000 "
    "01 00 0002 7f80 0000 "
    "02 00 0001 003c 0000"
)
KEY = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
DST = bytes.fromhex("001122334455")
SRC = bytes.fromhex("66778899aabb")


async def drive(dut: Any, frame: bytes, *, keep: int | None = None) -> None:
    first = frame[:64]
    dut.s_tdata.value = int.from_bytes(first.ljust(64, b"\0"), "little")
    dut.s_tkeep.value = (1 << len(first)) - 1 if keep is None else keep
    dut.s_valid.value = 1
    dut.m_ready.value = 1
    await Timer(1, unit="ns")


@cocotb.test()
async def independently_transcribed_alternating_groups(dut: Any) -> None:
    await drive(dut, GOLDEN)
    assert int(dut.s_ready.value) == 1
    assert int(dut.m_valid.value) == 1
    assert int(dut.fixed_header_valid.value) == 1
    expected = {
        "destination_mac": int.from_bytes(DST, "big"),
        "source_mac": int.from_bytes(SRC, "big"),
        "ethertype": 0x88B5,
        "version": 0x20,
        "packet_class": 2,
        "job_id": 0x0102030405060708,
        "group_id": 0x1122,
        "group_generation": 0x3344,
        "operation_id": 0x5566,
        "operation_generation": 0x778899AA,
        "source_endpoint": 0x0102,
        "destination_endpoint": 0x0304,
        "packet_id": 0x0A0B0C0D,
        "first_element": 9,
        "element_count": 3,
        "group_count": 2,
        "flags": 1,
        "body_bytes": 16,
        "stream_id": 0x0F10,
        "reserved": 0,
        "ingress_port": 7,
    }
    for name, value in expected.items():
        assert int(getattr(dut, name).value) == value, name
    # The first AXI beat contains exactly eight bytes of NumberGroup body.
    assert GOLDEN[56:64] == bytes.fromhex("010000027f800000")


@cocotb.test()
async def native_and_kulisch_headers_with_backpressure(dut: Any) -> None:
    samples: tuple[tuple[ConcreteFormat, int | bytes], ...] = (
        (ConcreteFormat.INT8, 0x7F),
        (ConcreteFormat.FP16, 0x3C00),
        (ConcreteFormat.BF16, 0x3F80),
        (ConcreteFormat.FP32, 0x3F800000),
        (
            ConcreteFormat.KULISCH,
            encode_kulisch(decode_native(0x3F800000, ConcreteFormat.FP32), 279),
        ),
    )
    for index, (fmt, value) in enumerate(samples):
        packet = DataPacket(
            PacketClass.RESULT,
            KEY,
            10,
            1,
            1,
            index,
            17,
            (NumberGroup(fmt, (value,)),),
            True,
        )
        frame = encode_data_frame(
            packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
        )
        await drive(dut, frame)
        dut.m_ready.value = 0
        await Timer(1, unit="ns")
        assert int(dut.s_ready.value) == 0
        assert int(dut.m_valid.value) == 1
        assert int(dut.fixed_header_valid.value) == 1
        assert int(dut.version.value) == 0x20
        assert int(dut.packet_class.value) == 3
        assert int(dut.packet_id.value) == index
        assert int(dut.first_element.value) == 17
        assert int(dut.element_count.value) == 1
        assert int(dut.group_count.value) == 1
        assert int(dut.body_bytes.value) == len(NumberGroup(fmt, (value,)).pack(279))
        assert int(dut.stream_id.value) == 1
        dut.m_ready.value = 1
        await Timer(1, unit="ns")
        assert int(dut.s_ready.value) == 1
    await drive(dut, GOLDEN, keep=((1 << 56) - 1) ^ (1 << 55))
    assert int(dut.fixed_header_valid.value) == 0
