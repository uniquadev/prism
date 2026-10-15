"""Independent format, numerical, FP32-eligibility, II=1 and backpressure checks."""

import random
from fractions import Fraction

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import ConcreteFormat as F
from prism_ccl.domain.numbers import (
    ExactValue,
    decode_native,
    encode_kulisch,
    is_lossless,
    round_native,
)

ORDER = (F.INT8, F.FP16, F.BF16, F.FP32)


def make_item(index, values, lanes, width, *, keep=None):
    formats = [
        next((fmt for fmt in ORDER if is_lossless(value, fmt)), F.KULISCH) for value in values
    ]
    wire = [encode_kulisch(value, width) for value in values]
    # The scheduler may send an eligible tile as one FP32 group.
    eligible = all(w[0] == 0 and is_lossless(v, F.FP32) for w, v in zip(wire, values, strict=True))
    return dict(
        first=index * lanes,
        keep=(1 << len(values)) - 1 if keep is None else keep,
        tags=sum(w[0] << (i * 8) for i, w in enumerate(wire)),
        integers=sum(
            (int.from_bytes(w[1:], "little") & ((1 << width) - 1)) << (i * width)
            for i, w in enumerate(wire)
        ),
        formats=formats,
        eligible=eligible,
        values=values,
        error=keep is not None,
    )


@cocotb.test()
async def grouping_stream_preserves_values_cost_and_handshake(dut):
    lanes = len(dut.s_keep)
    width = len(dut.s_integers) // lanes
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    dut.s_keep.value = 0
    dut.s_mode_wide.value = 1
    dut.s_fp32_bits.value = 0
    dut.s_tags.value = 0
    dut.s_integers.value = 0
    dut.s_first_element.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    pool = [
        decode_native(x, F.FP32)
        for x in (
            0x3F800000,
            0x3F801000,
            0x3EAAAAAB,
            0x00000001,
            0x00010000,
            0x80000000,
            0,
            0x7F800000,
            0xFF800000,
            0x7FC00000,
        )
    ]
    pool += [ExactValue("finite", False, Fraction(1) + Fraction(1, 1 << 24))]
    rng = random.Random(928)
    items = []
    for i in range(140):
        count = lanes if i < 64 else rng.randrange(1, lanes + 1)
        pattern = i % 5
        vals = [
            pool[0]
            if pattern == 0
            else pool[j % 3]
            if pattern == 1
            else pool[(j // 3) % len(pool)]
            if pattern == 2
            else rng.choice(pool)
            for j in range(count)
        ]
        items.append(make_item(i, vals, lanes, width))
    # Invalid keep followed immediately by valid metadata catches skewed errors.
    items.insert(75, make_item(900, [pool[0]] * 3, lanes, width, keep=5))
    items.insert(76, make_item(901, [pool[0]], lanes, width, keep=0))
    sent = received = 0
    accepts = []
    held = None
    for cycle in range(2000):
        await FallingEdge(dut.clk)
        ready = cycle < 72 or rng.random() > 0.35
        dut.m_ready.value = int(ready)
        dut.s_valid.value = int(sent < len(items))
        if sent < len(items):
            item = items[sent]
            dut.s_first_element.value = item["first"]
            dut.s_keep.value = item["keep"]
            dut.s_tags.value = item["tags"]
            dut.s_integers.value = item["integers"]
        await ReadOnly()
        valid = int(dut.m_valid.value)
        outputs = tuple(
            int(getattr(dut, name).value)
            for name in (
                "m_first_element",
                "m_keep",
                "m_formats",
                "m_native_bits",
                "m_fp32_bits",
                "m_fp32_eligible",
                "m_tags",
                "m_integers",
                "m_error",
            )
        )
        if held is not None:
            assert valid and outputs == held, "output changed while stalled"
        held = outputs if valid and not ready else None
        input_fire = sent < len(items) and int(dut.s_ready.value)
        if valid and ready:
            expected = items[received]
            assert outputs[0] == expected["first"] and outputs[1] == expected["keep"]
            assert outputs[-1] == int(expected["error"])
            if not expected["error"]:
                assert outputs[5] == int(expected["eligible"]), received
                for lane, (fmt, value) in enumerate(
                    zip(expected["formats"], expected["values"], strict=True)
                ):
                    got_fmt = (outputs[2] >> (lane * 8)) & 255
                    assert got_fmt == fmt, (received, lane, fmt, got_fmt)
                    if fmt != F.KULISCH:
                        assert (outputs[3] >> (lane * 32)) & 0xFFFFFFFF == round_native(value, fmt)
                    else:
                        mask = (1 << width) - 1
                        assert (outputs[7] >> (lane * width)) & mask == (
                            expected["integers"] >> (lane * width)
                        ) & mask
                    if expected["eligible"]:
                        assert (outputs[4] >> (lane * 32)) & 0xFFFFFFFF == round_native(
                            value, F.FP32
                        ), (received, lane)
            received += 1
        if input_fire:
            accepts.append(cycle)
            sent += 1
        await RisingEdge(dut.clk)
        if received == len(items):
            break
    assert sent == received == len(items)
    assert accepts[:64] == list(range(64)), "unnecessary input bubbles: II must be one"
