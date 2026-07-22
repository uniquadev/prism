from __future__ import annotations

import struct

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def tlv_decoder_preserves_event_stream_during_backpressure(dut):
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_header_valid.value = 0
    dut.s_byte_valid.value = 0
    dut.m_event_ready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    values = (123, 456)
    payload = b"".join(
        struct.pack("!HHI", record_type, 1, 8) + value.to_bytes(8, "big")
        for record_type, value in enumerate(values, start=1)
    )
    dut.s_header.value = 0
    dut.s_payload_length.value = len(payload)
    dut.s_header_valid.value = 1
    while not int(dut.s_header_ready.value):
        await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.s_header_valid.value = 0

    kinds = []
    value_bytes = []
    byte_index = 0
    held_event = None
    for cycle in range(1000):
        ready = (cycle % 5) != 1
        dut.m_event_ready.value = ready
        if byte_index < len(payload):
            dut.s_byte.value = payload[byte_index]
            dut.s_byte_last.value = byte_index == len(payload) - 1
            dut.s_byte_valid.value = 1
        else:
            dut.s_byte_valid.value = 0
        # Let VPI writes settle before sampling the handshake for this edge.
        await Timer(1, unit="ps")
        if int(dut.s_byte_valid.value) and int(dut.s_byte_ready.value):
            byte_index += 1
        if int(dut.m_event_valid.value):
            raw = int(dut.m_event.value)
            if not ready:
                if held_event is not None:
                    assert raw == held_event
                held_event = raw
            else:
                held_event = None
                assert len(dut.m_event) == 388
                kind = (raw >> 385) & 0x7
                kinds.append(kind)
                if kind == 2:
                    value_bytes.append((raw >> 9) & 0xFF)
        await RisingEdge(dut.clk)
        if kinds and kinds[-1] == 4:
            break
    assert byte_index == len(payload)
    assert kinds == [0, 1] + [2] * 8 + [3, 1] + [2] * 8 + [3, 4]
    assert bytes(value_bytes) == b"".join(value.to_bytes(8, "big") for value in values)
