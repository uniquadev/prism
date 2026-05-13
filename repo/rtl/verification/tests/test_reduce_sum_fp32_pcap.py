
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Lorenzo Cipolletti

import math
import os
import struct

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


PCAP_OUT = "traces/passthrough_out.pcap"

ETHERTYPE_REDUCTION = 0x88B5

# Ethernet fields stay network-order; Mini-Sharp custom fields are little-endian.

ETH_HDR_BYTES = 14
MINISHARP_HDR_BYTES = 19
MINISHARP_PAYLOAD_OFFSET = ETH_HDR_BYTES + MINISHARP_HDR_BYTES

CHUNK_ID_OFFSET = ETH_HDR_BYTES + 0
P_SIZE_OFFSET = ETH_HDR_BYTES + 4
FLOW_ID_OFFSET = ETH_HDR_BYTES + 8
COLLECTIVE_OP_OFFSET = ETH_HDR_BYTES + 10
OP_FLAGS_OFFSET = ETH_HDR_BYTES + 11
DTYPE_OFFSET = ETH_HDR_BYTES + 12
FLAGS_OFFSET = ETH_HDR_BYTES + 13
RESERVED_OFFSET = ETH_HDR_BYTES + 14
EXPECTED_OFFSET = ETH_HDR_BYTES + 15
CONTRIB_OFFSET = ETH_HDR_BYTES + 17

REDUCE_OP_SUM = 0
COLLECTIVE_REDUCE = 1
DTYPE_FP32 = 0


def read_pcap_frames(path):
    frames = []

    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) != 24:
            raise RuntimeError("PCAP global header too short")

        magic = gh[:4]

        if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
            endian = "<"
        elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
            endian = ">"
        else:
            raise RuntimeError(f"Unsupported PCAP magic: {magic.hex()}")

        while True:
            ph = f.read(16)
            if not ph:
                break

            if len(ph) != 16:
                raise RuntimeError("Truncated PCAP packet header")

            _ts_sec, _ts_frac, incl_len, _orig_len = struct.unpack(endian + "IIII", ph)

            frame = f.read(incl_len)
            if len(frame) != incl_len:
                raise RuntimeError("Truncated PCAP frame")

            frames.append(frame)

    return frames


def be16(frame, offset):
    return struct.unpack_from("!H", frame, offset)[0]


def le16(frame, offset):
    return struct.unpack_from("<H", frame, offset)[0]


def le32(frame, offset):
    return struct.unpack_from("<I", frame, offset)[0]


def fp32_values_from_payload(payload):
    assert len(payload) % 4 == 0
    return [
        struct.unpack_from("<f", payload, i)[0]
        for i in range(0, len(payload), 4)
    ]


def parse_minisharp_frame(frame):
    return {
        "ethertype": be16(frame, 12),
        "chunk_id": le32(frame, CHUNK_ID_OFFSET),
        "p_size": le32(frame, P_SIZE_OFFSET),
        "flow_id": le16(frame, FLOW_ID_OFFSET),
        "op_flags": frame[OP_FLAGS_OFFSET],
        "collective_op": frame[COLLECTIVE_OP_OFFSET],
        "dtype": frame[DTYPE_OFFSET],
        "expected_contributions": le16(frame, EXPECTED_OFFSET),
        "contribution_index": le16(frame, CONTRIB_OFFSET),
        "payload": frame[MINISHARP_PAYLOAD_OFFSET:],
    }


async def reset_dut(dut, cycles=10):
    dut.eos.value = 0
    dut.rst_n.value = 0

    for _ in range(cycles):
        await RisingEdge(dut.clk)

    dut.rst_n.value = 1

    for _ in range(2):
        await RisingEdge(dut.clk)


async def close_pcap_dumper(dut):
    dut.eos.value = 1

    for _ in range(5):
        await RisingEdge(dut.clk)

    dut.eos.value = 0

    for _ in range(20):
        await RisingEdge(dut.clk)


@cocotb.test()
async def test_reduce_sum_fp32_generates_reduced_pcap(dut):
    cocotb.start_soon(Clock(dut.clk, 3104, units="ps").start())

    await reset_dut(dut)

    for _ in range(100000):
        await RisingEdge(dut.clk)

        if int(dut.pcapfinished.value) == 1:
            break
    else:
        await close_pcap_dumper(dut)
        raise AssertionError("Timed out waiting for pcapfinished")

    for _ in range(10000):
        await RisingEdge(dut.clk)

    await close_pcap_dumper(dut)

    await Timer(1, units="ns")

    assert os.path.exists(PCAP_OUT), f"Missing output PCAP: {PCAP_OUT}"

    frames = read_pcap_frames(PCAP_OUT)
    assert len(frames) == 2, f"Expected 2 reduced packets, got {len(frames)}"

    decoded = [parse_minisharp_frame(frame) for frame in frames]

    for packet in decoded:
        assert packet["ethertype"] == ETHERTYPE_REDUCTION
        assert packet["p_size"] == 64
        assert packet["op_flags"] == REDUCE_OP_SUM
        assert packet["collective_op"] == COLLECTIVE_REDUCE
        assert packet["dtype"] == DTYPE_FP32
        assert packet["expected_contributions"] == 1
        assert packet["contribution_index"] == 0
        assert len(packet["payload"]) == 64

    by_chunk = {packet["chunk_id"]: packet for packet in decoded}

    assert 0 in by_chunk, "Missing reduced chunk_id 0"
    assert 1 in by_chunk, "Missing reduced chunk_id 1"

    values0 = fp32_values_from_payload(by_chunk[0]["payload"])
    values1 = fp32_values_from_payload(by_chunk[1]["payload"])

    for i, value in enumerate(values0):
        assert math.isclose(value, 10.0, rel_tol=0.0, abs_tol=1e-6), (
            f"Chunk 0 FP32 lane {i}: expected 10.0, got {value}"
        )

    for i, value in enumerate(values1):
        assert math.isclose(value, 26.0, rel_tol=0.0, abs_tol=1e-6), (
            f"Chunk 1 FP32 lane {i}: expected 26.0, got {value}"
        )
