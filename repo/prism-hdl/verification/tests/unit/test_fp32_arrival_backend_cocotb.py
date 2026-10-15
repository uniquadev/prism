"""Bank arbitration defines arrival, independently for each global element."""

from __future__ import annotations

import random
import struct
from collections import deque

import cocotb
from cocotb.triggers import Timer

from tests.unit.test_fp32_arrival_bank_cocotb import add32, pack


def to_fp32(bits, fmt):
    if fmt == 1:
        return int.from_bytes(struct.pack(">f", bits if bits < 128 else bits - 256), "big")
    if fmt == 2:
        return int.from_bytes(
            struct.pack(">f", struct.unpack(">e", bits.to_bytes(2, "big"))[0]), "big"
        )
    return bits << 16 if fmt == 3 else bits


@cocotb.test()
async def simultaneous_ports_mixed_formats_and_backpressure(dut):
    ports = len(dut.s_bits)
    queues = [deque() for _ in range(ports)]
    # Rows are banked; each port interleaves local formats and partial lane masks.
    for contribution, (fmt, bits) in enumerate([(4, 0x3F800000), (2, 0x0001), (3, 0xBF80)]):
        for row in range(32):
            port = (row + contribution) % ports
            for keep in (0x5555, 0xAAAA):
                queues[port].append((row, fmt, bits, keep))
    sums = [[0] * 16 for _ in range(32)]
    counts = [[0] * 16 for _ in range(32)]
    results = set()
    rng = random.Random(2981)
    dut.rst_n.value = 0
    dut.s_release.value = 0
    dut.s_valid.value = 0
    dut.s_children.value = 3
    dut.s_total_elements.value = 512
    dut.m_ready.value = 0
    stalled = None
    accepted = 0
    for cycle in range(12000):
        dut.clk.value = 0
        if cycle == 3:
            dut.rst_n.value = 1
        valid = 0
        for port in range(ports):
            if queues[port] and cycle >= 3:
                row, fmt, bits, keep = queues[port][0]
                dut.s_first[port].value = row * 16
                dut.s_format[port].value = fmt
                dut.s_bits[port].value = pack([bits] * 16, {1: 8, 2: 16, 3: 16, 4: 32}[fmt])
                dut.s_keep[port].value = keep
                valid |= 1 << port
        dut.s_valid.value = valid
        ready = cycle >= 3 and rng.random() > 0.4
        dut.m_ready.value = ready
        await Timer(2, unit="ns")
        if cycle >= 3:
            input_ready = int(dut.s_ready.value)
            for port in range(ports):
                if valid & input_ready & (1 << port):
                    row, fmt, bits, keep = queues[port].popleft()
                    bits = to_fp32(bits, fmt)
                    for lane in range(16):
                        if keep & (1 << lane):
                            sums[row][lane] = (
                                add32(sums[row][lane], bits) if counts[row][lane] else bits
                            )
                            counts[row][lane] += 1
                    accepted += 1
            out_valid = int(dut.m_valid.value)
            item = (
                int(dut.m_slot.value),
                int(dut.m_bits.value),
                int(dut.m_present.value),
                int(dut.m_error.value),
            )
            if stalled is not None:
                assert out_valid and item == stalled
            stalled = item if out_valid and not ready else None
            if out_valid and ready:
                row, bits, keep, error = item
                assert row not in results
                assert counts[row] == [3] * 16
                assert (bits, keep, error) == (pack(sums[row]), 0xFFFF, 0)
                results.add(row)
            assert not int(dut.m_fault.value)
        dut.clk.value = 1
        await Timer(2, unit="ns")
        if len(results) == 32 and not any(queues):
            assert accepted == 192
            return
    raise AssertionError(f"backend timeout: accepted={accepted}, results={len(results)}")
