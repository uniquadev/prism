from __future__ import annotations

from fractions import Fraction

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from prism_ccl.protocol.constants import WireFormat
from prism_ccl.protocol.numeric import decode_bits

ACC_W = 288
UNITS = {
    WireFormat.INT8: Fraction(1),
    WireFormat.FP16: Fraction(1, 1 << 24),
    WireFormat.BF16: Fraction(1, 1 << 133),
    WireFormat.FP32: Fraction(1, 1 << 149),
}


def pack_lanes(values: list[int]) -> int:
    return sum(value << (32 * lane) for lane, value in enumerate(values))


def signed_field(value: int, width: int) -> int:
    return value & ((1 << width) - 1)


@cocotb.test()
async def every_input_datatype_maps_to_exact_deposits_and_special_flags(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    vectors = (
        (WireFormat.INT8, [0x00, 0x80, 0x7F, 0xFF]),
        (WireFormat.FP16, [0x8000, 0x0001, 0x7C00, 0x7E01]),
        (WireFormat.BF16, [0x8000, 0x0001, 0x7F80, 0xFF80]),
        (WireFormat.FP32, [0x80000000, 0x00000001, 0xFF800000, 0x7FA12345]),
    )
    for wire_format, values in vectors:
        dut.s_element_bits.value = pack_lanes(values)
        dut.s_element_keep.value = 0xF
        dut.s_format.value = int(wire_format)
        dut.s_valid.value = 1
        await RisingEdge(dut.clk)
        dut.s_valid.value = 0
        await Timer(1, unit="ps")

        expected_deposits = []
        expected = {
            "finite": 0,
            "zero": 0,
            "zero_sign": 0,
            "nan": 0,
            "positive_infinity": 0,
            "negative_infinity": 0,
        }
        for lane, bits in enumerate(values):
            decoded = decode_bits(bits, wire_format)
            deposit = 0
            if decoded.kind in {"zero", "finite"}:
                assert decoded.value is not None
                deposit = int(decoded.value / UNITS[wire_format])
                expected["finite"] |= 1 << lane
            if decoded.kind == "zero":
                expected["zero"] |= 1 << lane
                expected["zero_sign"] |= int(decoded.sign) << lane
            elif decoded.kind == "nan":
                expected["nan"] |= 1 << lane
            elif decoded.kind == "infinity":
                key = "negative_infinity" if decoded.sign else "positive_infinity"
                expected[key] |= 1 << lane
            expected_deposits.append(signed_field(deposit, ACC_W))

        raw_deposits = int(dut.m_deposits.value)
        actual_deposits = [
            (raw_deposits >> (lane * ACC_W)) & ((1 << ACC_W) - 1) for lane in range(4)
        ]
        assert actual_deposits == expected_deposits
        assert int(dut.m_element_keep.value) == 0xF
        assert int(dut.m_overflow.value) == 0
        assert int(dut.m_format_error.value) == 0
        for name, mask in expected.items():
            assert int(getattr(dut, f"m_{name}").value) == mask

        dut.m_ready.value = 1
        await RisingEdge(dut.clk)
        dut.m_ready.value = 0

    dut.s_format.value = int(WireFormat.INVALID)
    dut.s_element_bits.value = 0
    dut.s_element_keep.value = 0xF
    dut.s_valid.value = 1
    await RisingEdge(dut.clk)
    dut.s_valid.value = 0
    await Timer(1, unit="ps")
    assert int(dut.m_valid.value) == 1
    assert int(dut.m_format_error.value) == 1
    assert int(dut.m_deposits.value) == 0
