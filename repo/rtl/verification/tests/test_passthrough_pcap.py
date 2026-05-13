# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Lorenzo Cipolletti
#
# Questo file fa parte del progetto Mini-Sharp.
# Vedere LICENSE e NOTICE nel root della repository per i dettagli.

import os
import struct

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


PCAP_OUT = "traces/passthrough_out.pcap"

ETHERTYPE_REDUCTION = 0x88B5

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


def read_pcap_frames(path):
    """Legge un file PCAP classico e restituisce la lista dei frame Ethernet."""
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


def be32(frame, offset):
    return struct.unpack_from("!I", frame, offset)[0]


def parse_minisharp_frame(frame):
    """Estrae i campi principali da un frame Ethernet Mini-Sharp."""
    return {
        "dst": frame[0:6],
        "src": frame[6:12],
        "ethertype": be16(frame, 12),
        "chunk_id": be32(frame, CHUNK_ID_OFFSET),
        "p_size": be32(frame, P_SIZE_OFFSET),
        "flow_id": be16(frame, FLOW_ID_OFFSET),
        "op_flags": frame[OP_FLAGS_OFFSET],
        "collective_op": frame[COLLECTIVE_OP_OFFSET],
        "dtype": frame[DTYPE_OFFSET],
        "flags": frame[FLAGS_OFFSET],
        "reserved": frame[RESERVED_OFFSET],
        "expected_contributions": be16(frame, EXPECTED_OFFSET),
        "contribution_index": be16(frame, CONTRIB_OFFSET),
        "payload": frame[MINISHARP_PAYLOAD_OFFSET:],
    }


async def reset_dut(dut, cycles=10):
    """Porta il DUT in reset e poi lo rilascia in modo deterministico."""
    dut.eos.value = 0
    dut.rst_n.value = 0

    for _ in range(cycles):
        await RisingEdge(dut.clk)

    dut.rst_n.value = 1

    for _ in range(2):
        await RisingEdge(dut.clk)


async def close_pcap_dumper(dut):
    """
    Il modulo pcap_dumper chiude il file quando vede eos.
    Manteniamo eos alto per alcuni cicli per rendere la chiusura stabile.
    """
    dut.eos.value = 1

    for _ in range(5):
        await RisingEdge(dut.clk)

    dut.eos.value = 0

    for _ in range(20):
        await RisingEdge(dut.clk)


@cocotb.test()
async def test_passthrough_generates_reduced_pcap(dut):
    """
    Test end-to-end basato su PCAP.

    Input generato da traffic-gen:
      chunk 0: contributi 1, 2, 3, 4 -> 10 / 0x0a
      chunk 1: contributi 5, 6, 7, 8 -> 26 / 0x1a

    Output atteso:
      2 frame Ethernet Mini-Sharp con payload ridotto.
    """

    # Periodo scelto in ps interi per evitare errori di precisione in Cocotb.
    cocotb.start_soon(Clock(dut.clk, 3104, units="ps").start())

    await reset_dut(dut)

    # Aspetta che la sorgente PCAP abbia letto tutto il file di input.
    for _ in range(100000):
        await RisingEdge(dut.clk)

        if int(dut.pcapfinished.value) == 1:
            break
    else:
        await close_pcap_dumper(dut)
        raise AssertionError("Timed out waiting for pcapfinished")

    # Lascia drenare il datapath e il dumper.
    for _ in range(10000):
        await RisingEdge(dut.clk)

    await close_pcap_dumper(dut)

    await Timer(1, units="ns")

    assert os.path.exists(PCAP_OUT), f"Missing output PCAP: {PCAP_OUT}"

    file_size = os.path.getsize(PCAP_OUT)
    dut._log.info("Output PCAP path: %s", PCAP_OUT)
    dut._log.info("Output PCAP size: %d bytes", file_size)

    frames = read_pcap_frames(PCAP_OUT)

    dut._log.info("Output PCAP contains %d frame(s)", len(frames))

    assert len(frames) == 2, f"Expected 2 reduced packets, got {len(frames)}"

    decoded = [parse_minisharp_frame(frame) for frame in frames]

    for packet in decoded:
        assert packet["ethertype"] == ETHERTYPE_REDUCTION
        assert packet["p_size"] == 64
        assert packet["op_flags"] == 0
        assert packet["collective_op"] == 1
        assert packet["dtype"] == 3
        assert packet["expected_contributions"] == 1
        assert packet["contribution_index"] == 0
        assert len(packet["payload"]) == 64

    by_chunk = {packet["chunk_id"]: packet for packet in decoded}

    assert 0 in by_chunk, "Missing reduced chunk_id 0"
    assert 1 in by_chunk, "Missing reduced chunk_id 1"

    # Verify flow_id preserved and matches the group id used by traffic-gen
    assert by_chunk[0]["flow_id"] == 0, "Chunk 0 should have flow_id 0"
    assert by_chunk[1]["flow_id"] == 1, "Chunk 1 should have flow_id 1"

    assert all(byte == 0x0A for byte in by_chunk[0]["payload"]), (
        "Chunk 0 payload should be 0x0a repeated"
    )

    assert all(byte == 0x1A for byte in by_chunk[1]["payload"]), (
        "Chunk 1 payload should be 0x1a repeated"
    )
