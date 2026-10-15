"""Observe every online commit, including those before a range is complete."""

from __future__ import annotations

import random
import struct

import cocotb
from cocotb.triggers import Timer


def add32(left: int, right: int) -> int:
    a, b = (struct.unpack(">f", v.to_bytes(4, "big"))[0] for v in (left, right))
    try:
        value = int.from_bytes(struct.pack(">f", a + b), "big")
    except OverflowError:
        value = 0xFF800000 if a + b < 0 else 0x7F800000
    if value & 0x7FFFFFFF > 0x7F800000:
        value = 0x7FC00000
    return value


def pack(values: list[int], width: int = 32) -> int:
    return sum(value << (width * lane) for lane, value in enumerate(values))


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.cycle = 0
        self.pending = []
        self.results = set()
        self.result_stalled = None
        self.arithmetic_stalled = None
        self.values: dict[int, list[int]] = {}
        self.counts: dict[int, list[int]] = {}
        self.commits = 0
        self.accept_cycles: list[int] = []
        self.stalled = None

    async def tick(self, item=None, *, ready=True):
        d = self.dut
        d.clk.value = 0
        d.s_valid.value = int(item is not None)
        d.m_ready.value = int(ready)
        d.m_result_ready.value = int(ready)
        if item is not None:
            row, bits, keep, expected, children = item
            d.s_row.value = row
            d.s_bits.value = pack(bits)
            d.s_keep.value = keep
            d.s_expected_keep.value = expected
            d.s_children.value = children
        await Timer(2, unit="ns")
        accepted = item is not None and int(d.s_ready.value)
        arithmetic = d.u_accumulate
        arithmetic_item = tuple(
            int(getattr(arithmetic, name).value)
            for name in ("s_sum", "s_bits", "s_present", "s_keep", "s_tag")
        )
        if self.arithmetic_stalled is not None:
            assert int(arithmetic.s_valid.value) and arithmetic_item == self.arithmetic_stalled
        self.arithmetic_stalled = (
            arithmetic_item
            if int(arithmetic.s_valid.value) and not int(arithmetic.s_ready.value)
            else None
        )
        valid = int(d.m_valid.value)
        actual = (
            int(d.m_row.value),
            int(d.m_bits.value),
            int(d.m_counts.value),
            int(d.m_complete.value),
            int(d.m_error.value),
            int(d.m_keep.value),
        )
        if self.stalled is not None:
            assert valid and actual == self.stalled, "commit changed under backpressure"
        self.stalled = actual if valid and not ready else None
        if accepted:
            row, bits, keep, expected, children = item
            old = self.values.setdefault(row, [0] * 16)
            counts = self.counts.setdefault(row, [0] * 16)
            for lane in range(16):
                if keep & (1 << lane):
                    v = bits[lane]
                    if v & 0x7FFFFFFF > 0x7F800000:
                        v = 0x7FC00000
                    old[lane] = add32(old[lane], v) if counts[lane] else v
                    counts[lane] += 1
            complete = all(counts[lane] == children for lane in range(16) if expected & (1 << lane))
            self.pending.append((row, old.copy(), counts.copy(), int(complete), keep))
            self.accept_cycles.append(self.cycle)
        if valid and ready:
            assert self.pending, "unsolicited commit"
            # Different rows may complete through seed bypass or the adder.
            # The ordering requirement is per element, hence per row here.
            index = next(i for i, item in enumerate(self.pending) if item[0] == actual[0])
            row, bits, counts, complete, keep = self.pending.pop(index)
            mask32 = pack([0xFFFFFFFF if keep & (1 << lane) else 0 for lane in range(16)])
            mask4 = pack([15 if keep & (1 << lane) else 0 for lane in range(16)], 4)
            assert actual[0] == row and actual[3:] == (complete, 0, keep)
            assert actual[1] & mask32 == pack(bits) & mask32
            assert actual[2] & mask4 == pack(counts, 4) & mask4
            self.commits += 1
        snapshot = (
            int(d.m_result_row.value),
            int(d.m_result_bits.value),
            int(d.m_result_keep.value),
            int(d.m_result_error.value),
        )
        snapshot_valid = int(d.m_result_valid.value)
        if self.result_stalled is not None:
            assert snapshot_valid and snapshot == self.result_stalled
        self.result_stalled = snapshot if snapshot_valid and not ready else None
        if snapshot_valid and ready:
            row, bits, keep, error = snapshot
            assert row not in self.results and error == 0
            for lane in range(16):
                if keep & (1 << lane):
                    assert (bits >> (lane * 32)) & 0xFFFFFFFF == self.values[row][lane]
            self.results.add(row)
        d.clk.value = 1
        await Timer(2, unit="ns")
        self.cycle += 1
        return accepted

    async def reset(self):
        d = self.dut
        d.rst_n.value = 0
        d.s_release.value = 0
        d.s_valid.value = 0
        d.s_row.value = 0
        d.s_bits.value = 0
        d.s_keep.value = 0
        d.s_expected_keep.value = 0xFFFF
        d.s_children.value = 3
        for _ in range(3):
            await self.tick()
        d.rst_n.value = 1

    async def send(self, item, *, rng=None):
        for _ in range(200):
            if await self.tick(item, ready=rng is None or rng.random() > 0.3):
                return
        raise AssertionError("bank admission timed out")

    async def drain(self):
        for _ in range(100):
            await self.tick()
            if not self.pending and int(self.dut.m_idle.value):
                return
        raise AssertionError("bank failed to commit/release all pending updates")


@cocotb.test()
async def updates_are_online_and_order_sensitive(dut):
    for sequence, expected in [
        ([0x3F800000, 0x33800000, 0xBF800000], 0),
        ([0x3F800000, 0xBF800000, 0x33800000], 0x33800000),
    ]:
        b = Bench(dut)
        await b.reset()
        for number, bits in enumerate(sequence):
            await b.send((0, [bits] * 16, 0xFFFF, 0xFFFF, 3))
            await b.drain()
            assert b.commits == number + 1, "must update before all contributors arrive"
        assert b.values[0] == [expected] * 16


@cocotb.test()
async def nearby_dependencies_backpressure_and_partial_lanes(dut):
    b = Bench(dut)
    await b.reset()
    rng = random.Random(9081)
    rows = list(range(32))
    for _contributor in range(3):
        rng.shuffle(rows)
        for row in rows:
            bits = [
                rng.choice([0x3F800000, 0xBF800000, 0x33800000, 0, 0x80000000, 1, 0x80000001])
                for _ in range(16)
            ]
            await b.send((row, bits, 0x5555, 0xFFFF, 3), rng=rng)
            await b.send((row, bits, 0xAAAA, 0xFFFF, 3), rng=rng)
    await b.drain()
    assert b.commits == 192
    dut.s_release.value = 1
    await b.tick()
    dut.s_release.value = 0
    fresh = Bench(dut)
    await fresh.send((0, [0x80000000] * 16, 0xFFFF, 0xFFFF, 1))
    await fresh.drain()
    assert fresh.values[0] == [0x80000000] * 16


@cocotb.test()
async def independent_rows_have_unit_initiation_interval(dut):
    b = Bench(dut)
    await b.reset()
    for row in range(64):
        await b.send((row, [0x3F800000] * 16, 0xFFFF, 0xFFFF, 2))
    assert all(y - x == 1 for x, y in zip(b.accept_cycles, b.accept_cycles[1:], strict=False))
    await b.drain()
    assert b.commits == 64
    dut._log.info("FP32 online bank: 64 independent full tiles, admission II=1")


@cocotb.test()
async def special_values_and_tail_mask(dut):
    b = Bench(dut)
    await b.reset()
    lhs = [0x7F800000, 0xFF800000, 0x7FC12345, 0x80000000, 1, 0x007FFFFF, 0x7F7FFFFF] + [0] * 9
    rhs = [0xFF800000, 0xFF800000, 0x3F800000, 0x80000000, 1, 1, 0x7F7FFFFF] + [0] * 9
    await b.send((0, lhs, 0x7F, 0x7F, 2))
    await b.send((0, rhs, 0x7F, 0x7F, 2))
    await b.drain()
    assert b.commits == 2


@cocotb.test()
async def disjoint_lanes_admit_without_false_raw_dependencies(dut):
    b = Bench(dut)
    await b.reset()
    await b.send((0, [0x80000000] * 16, 0x00FF, 0xFFFF, 2))
    first = b.accept_cycles[-1]
    await b.send((0, [0x80000000] * 16, 0xFF00, 0xFFFF, 2))
    assert b.accept_cycles[-1] - first == 1, "disjoint element positions must admit at II=1"
    await b.send((0, [0x3F800000] * 16, 0xFFFF, 0xFFFF, 2))
    # Another row remains independent while the real addition is in flight.
    await b.send((1, [0x33800000] * 16, 0xFFFF, 0xFFFF, 2))
    for _ in range(12):
        await b.tick(ready=False)
    await b.drain()
    assert b.commits == 4
    assert b.values[0] == [0x3F800000] * 16


@cocotb.test()
async def completion_snapshots_share_read_port_without_deadlock(dut):
    b = Bench(dut)
    await b.reset()
    rng = random.Random(4567)
    for row in range(64):
        await b.send((row, [0x3F800000 + row] * 16, 0xFFFF, 0xFFFF, 1), rng=rng)
    await b.drain()
    assert b.commits == 64 and b.results == set(range(64))


@cocotb.test()
async def reset_discards_pending_updates_and_snapshots(dut):
    b = Bench(dut)
    await b.reset()
    await b.send((0, [0x3F800000] * 16, 0xFFFF, 0xFFFF, 2))
    await b.send((1, [0x33800000] * 16, 0xFFFF, 0xFFFF, 1))
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    for _ in range(2):
        dut.clk.value = 0
        await Timer(2, unit="ns")
        dut.clk.value = 1
        await Timer(2, unit="ns")
    fresh = Bench(dut)
    await fresh.reset()
    await fresh.drain()
    assert fresh.commits == 0 and not fresh.results
    await fresh.send((0, [0x80000000] * 16, 0xFFFF, 0xFFFF, 1))
    await fresh.drain()
    assert fresh.commits == 1 and fresh.results == {0}
