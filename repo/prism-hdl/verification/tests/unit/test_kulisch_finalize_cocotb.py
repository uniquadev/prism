from __future__ import annotations

import cocotb
from cocotb.triggers import Timer
from prism_ccl.protocol.constants import WireFormat

ACC_W = 320


def pack_signed(values: list[int]) -> int:
    mask = (1 << ACC_W) - 1
    return sum((value & mask) << (ACC_W * lane) for lane, value in enumerate(values))


@cocotb.test()
async def finalizer_handles_rounding_overflow_specials_and_signed_zero(dut) -> None:
    dut.input_format.value = int(WireFormat.FP32)
    dut.accumulators.value = pack_signed(
        [
            1 << 149,
            -(1 << 149),
            (1 << 149) + (1 << 125),
            (1 << 149) + (3 << 124),
        ]
    )
    dut.saw_nan.value = 0
    dut.saw_positive_infinity.value = 0
    dut.saw_negative_infinity.value = 0
    dut.saw_finite_nonzero.value = 0xF
    dut.saw_zero.value = 0
    dut.all_zero_negative.value = 0
    await Timer(1, unit="ns")
    raw = int(dut.fp32_bits.value)
    assert [(raw >> (32 * lane)) & 0xFFFFFFFF for lane in range(4)] == [
        0x3F800000,
        0xBF800000,
        0x3F800000,
        0x3F800001,
    ]
    assert int(dut.inexact.value) == 0b1100
    assert int(dut.overflow.value) == 0
    assert int(dut.underflow.value) == 0

    dut.accumulators.value = pack_signed([(1 << 319) - 1, 0, 0, 0])
    dut.saw_nan.value = 0b0010
    dut.saw_positive_infinity.value = 0b0100
    dut.saw_negative_infinity.value = 0b0100
    dut.saw_finite_nonzero.value = 0b0001
    dut.saw_zero.value = 0b1000
    dut.all_zero_negative.value = 0b1000
    await Timer(1, unit="ns")
    raw = int(dut.fp32_bits.value)
    assert [(raw >> (32 * lane)) & 0xFFFFFFFF for lane in range(4)] == [
        0x7F800000,
        0x7FC00000,
        0x7FC00000,
        0x80000000,
    ]
    assert int(dut.overflow.value) == 0b0001
    assert int(dut.inexact.value) == 0b0001

    dut.accumulators.value = 0
    dut.saw_nan.value = 0
    dut.saw_positive_infinity.value = 0b0001
    dut.saw_negative_infinity.value = 0b0010
    dut.saw_finite_nonzero.value = 0
    dut.saw_zero.value = 0
    dut.all_zero_negative.value = 0
    await Timer(1, unit="ns")
    raw = int(dut.fp32_bits.value)
    assert [(raw >> (32 * lane)) & 0xFFFFFFFF for lane in range(2)] == [
        0x7F800000,
        0xFF800000,
    ]
