"""Sustained NumberGroup throughput gate for the SINGLE DUT.

These tests observe accepted AXI beats, including gaps between packets. The
short case catches a byte-serial RESULT sender; the long case requires packet
streaming and tests per-port DATA ingress as well as RESULT egress. Neither
case treats the 512-bit bus width or a simulated 4 ns clock as measured rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cocotb
from ccl.examples import shared_port_world
from ccl.world import CocotbSingleBackend
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    OperationKey,
    PartialWirePolicy,
    TypedVector,
)
from prism_ccl.domain.numbers import combine_exact, decode_native, round_native
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)

CLOCK_HZ = 250_000_000
TARGET_GBPS = 100.0
SHORT_ELEMENTS = 64
STREAM_ELEMENTS = 4096
NATIVE_RESULT_KEY = OperationKey(7, 3, 1, 9, 2)


@dataclass(slots=True)
class TransferWindow:
    first_cycle: int | None = None
    last_cycle: int | None = None
    frames: int = 0
    beats: int = 0
    axi_bytes: int = 0

    @property
    def cycles(self) -> int:
        if self.first_cycle is None or self.last_cycle is None:
            raise AssertionError("no accepted AXI transfer for the requested packet class")
        return self.last_cycle - self.first_cycle + 1

    def numeric_gbps(self, numeric_bytes: int) -> float:
        return numeric_bytes * 8 * CLOCK_HZ / self.cycles / 1e9

    def axi_gbps(self) -> float:
        return self.numeric_gbps(self.axi_bytes)


class AxiRateProbe:
    """Passively measure handshakes over the full first-to-last frame window."""

    def __init__(self, dut: Any) -> None:
        self.dut = dut
        self.cycles = 0
        self.windows: dict[tuple[str, int, int], TransferWindow] = {}
        self.in_frame: dict[tuple[str, int], int] = {}
        self.input_stalls = [0, 0]

    async def run(self) -> None:
        await RisingEdge(self.dut.rst_n)
        while True:
            await FallingEdge(self.dut.clk)
            await ReadOnly()
            self.cycles += 1
            for direction in ("s", "m"):
                for port in range(2):
                    prefix = f"{direction}{port}"
                    if (
                        direction == "s"
                        and int(getattr(self.dut, f"{prefix}_tvalid").value)
                        and not int(getattr(self.dut, f"{prefix}_tready").value)
                    ):
                        self.input_stalls[port] += 1
                    if not (
                        int(getattr(self.dut, f"{prefix}_tvalid").value)
                        and int(getattr(self.dut, f"{prefix}_tready").value)
                    ):
                        continue
                    stream = (direction, port)
                    if stream not in self.in_frame:
                        first_beat = int(getattr(self.dut, f"{prefix}_tdata").value).to_bytes(
                            64, "little"
                        )
                        self.in_frame[stream] = first_beat[15]
                    packet_class = self.in_frame[stream]
                    window = self.windows.setdefault(
                        (direction, port, packet_class), TransferWindow()
                    )
                    if window.first_cycle is None:
                        window.first_cycle = self.cycles
                    window.last_cycle = self.cycles
                    window.beats += 1
                    window.axi_bytes += int(getattr(self.dut, f"{prefix}_tkeep").value).bit_count()
                    if int(getattr(self.dut, f"{prefix}_tlast").value):
                        window.frames += 1
                        del self.in_frame[stream]

    def window(self, direction: str, port: int, packet_class: PacketClass) -> TransferWindow:
        return self.windows.get((direction, port, int(packet_class)), TransferWindow())


async def check_profile(
    dut: Any,
    accumulator: AccumulatorPolicy,
    partial_wire: PartialWirePolicy,
    *,
    elements: int,
) -> None:
    world, tree = shared_port_world()
    vectors = {
        0: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * elements),
        1: TypedVector(ConcreteFormat.FP32, (0x33800000,) * elements),
        2: TypedVector(ConcreteFormat.FP32, (0xBF800000,) * elements),
    }
    world.register_reduce(
        "line-rate",
        tree=tree,
        vectors=vectors,
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=accumulator,
        partial_wire=partial_wire,
        output_format=ConcreteFormat.FP32,
        mtu=1500,
    )
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    probe = AxiRateProbe(dut)
    monitor = cocotb.start_soon(probe.run())
    try:
        result = await world.run_async(
            "line-rate",
            backend=CocotbSingleBackend(
                dut, prism_name="s", start_clock=False, timeout_cycles=200_000
            ),
        )
    finally:
        monitor.cancel()

    exact_bits = 0x33800000
    rounded_bits = 0x00000000
    expected = exact_bits if accumulator == AccumulatorPolicy.KULISCH_FIXED else rounded_bits
    assert result.rank_bits == {1: (expected,) * elements}
    assert result.released_context

    result_frames = [
        frame for port, frame in result.frames if port == 1 and frame[15] == PacketClass.RESULT
    ]
    result_elements = sum(
        decode_data_frame(frame, mtu=1500, kulisch_bits=280).element_count
        for frame in result_frames
    )
    assert result_elements == elements
    egress = probe.window("m", 1, PacketClass.RESULT)
    assert egress.frames == len(result_frames)
    if elements == STREAM_ELEMENTS:
        assert egress.frames >= 8, "a single buffered frame is not a streaming test"
    result_gbps = egress.numeric_gbps(result_elements * 4)
    dut._log.info(
        "policy=%s elements=%d RESULT payload=%.2f Gb/s, AXI frame=%.2f Gb/s "
        "over %d frames, %d beats and %d cycles",
        accumulator.name,
        elements,
        result_gbps,
        egress.axi_gbps(),
        egress.frames,
        egress.beats,
        egress.cycles,
    )
    assert result_gbps >= TARGET_GBPS, (
        f"{accumulator.name}: observed RESULT payload {result_gbps:.2f} Gb/s; "
        f"target is {TARGET_GBPS:.0f} Gb/s"
    )

    if elements == STREAM_ELEMENTS:
        input_starts = [probe.window("s", port, PacketClass.DATA).first_cycle for port in (0, 1)]
        assert egress.first_cycle is not None and all(cycle is not None for cycle in input_starts)
        dut._log.info(
            "policy=%s first DATA-to-RESULT AXI latency=%d cycles",
            accumulator.name,
            egress.first_cycle - min(cycle for cycle in input_starts if cycle is not None),
        )
        for port in (0, 1):
            sent = [
                frame
                for sent_port, frame in result.sent_frames
                if sent_port == port and frame[15] == PacketClass.DATA
            ]
            received_elements = sum(
                decode_data_frame(frame, mtu=1500, kulisch_bits=280).element_count for frame in sent
            )
            assert received_elements >= elements
            ingress = probe.window("s", port, PacketClass.DATA)
            assert ingress.frames == len(sent)
            assert ingress.frames >= 8
            ingress_gbps = ingress.numeric_gbps(received_elements * 4)
            dut._log.info(
                "policy=%s port=%d DATA payload=%.2f Gb/s, AXI frame=%.2f Gb/s "
                "over %d frames, %d beats, %d cycles, %d input stalls",
                accumulator.name,
                port,
                ingress_gbps,
                ingress.axi_gbps(),
                ingress.frames,
                ingress.beats,
                ingress.cycles,
                probe.input_stalls[port],
            )
            assert ingress_gbps >= TARGET_GBPS, (
                f"{accumulator.name} port {port}: observed DATA payload "
                f"{ingress_gbps:.2f} Gb/s; target is {TARGET_GBPS:.0f} Gb/s"
            )


@cocotb.test()
async def fp32_arrival_result_chunk_reaches_line_rate(dut: Any) -> None:
    await check_profile(
        dut, AccumulatorPolicy.FP32_ARRIVAL, PartialWirePolicy.FP32, elements=SHORT_ELEMENTS
    )


@cocotb.test()
async def kulisch_fixed_result_chunk_reaches_line_rate(dut: Any) -> None:
    await check_profile(
        dut, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH, elements=SHORT_ELEMENTS
    )


@cocotb.test()
async def kulisch_auto_result_chunk_reaches_line_rate(dut: Any) -> None:
    await check_profile(
        dut, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO, elements=SHORT_ELEMENTS
    )


@cocotb.test()
async def fp32_arrival_stream_reaches_line_rate(dut: Any) -> None:
    engine = dut.u_core.u_single.u_ingress.gen_arrival_round.u_arrival
    counters = {
        "accepted": [0, 0],
        "lane_busy": [0, 0],
        "arbitration": [0, 0],
        "pipeline": [0, 0],
        "not_offered": [0, 0],
        "output_stall": 0,
        "busy_rows": {},
    }

    async def observe() -> None:
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            valid = int(engine.s_valid.value)
            ready = int(engine.s_ready.value)
            for port in range(2):
                if not valid & (1 << port):
                    counters["not_offered"][port] += 1
                elif ready & (1 << port):
                    counters["accepted"][port] += 1
                else:
                    slot = int(engine.s_first[port].value) // 16
                    bank_state = engine.gen_bank[slot % 4]
                    busy = int(bank_state.u_state.pending.value) | int(
                        bank_state.u_state.completed.value
                    )
                    reason = (
                        "lane_busy"
                        if (busy >> ((slot // 4) * 16)) & int(engine.s_keep[port].value)
                        else "pipeline"
                        if not int(bank_state.selected_ready.value)
                        else "arbitration"
                    )
                    counters[reason][port] += 1
                    if reason == "lane_busy":
                        key = f"p{port}/tile{slot}/keep{int(engine.s_keep[port].value):04x}"
                        counters["busy_rows"][key] = counters["busy_rows"].get(key, 0) + 1
            if int(engine.m_valid.value) and not int(engine.m_ready.value):
                counters["output_stall"] += 1

    monitor = cocotb.start_soon(observe())
    try:
        await check_profile(
            dut, AccumulatorPolicy.FP32_ARRIVAL, PartialWirePolicy.FP32, elements=STREAM_ELEMENTS
        )
    finally:
        monitor.cancel()
        dut._log.info("FP32 admission diagnostics: %s", counters)


@cocotb.test()
async def kulisch_fixed_stream_reaches_line_rate(dut: Any) -> None:
    await check_profile(
        dut, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH, elements=STREAM_ELEMENTS
    )


@cocotb.test()
async def kulisch_auto_stream_reaches_line_rate(dut: Any) -> None:
    await check_profile(
        dut, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO, elements=STREAM_ELEMENTS
    )


async def check_native_result(
    dut: Any,
    output_format: ConcreteFormat,
    accumulator: AccumulatorPolicy,
    partial_wire: PartialWirePolicy,
) -> None:
    world, tree = shared_port_world()
    pattern = (0x3F800000, 0x40000000, 0x40400000, 0xC0400000, 0, 0xBF800000)
    input_bits = tuple(pattern[index % len(pattern)] for index in range(STREAM_ELEMENTS))
    world.register_reduce(
        "native-result",
        tree=tree,
        vectors={
            0: TypedVector(ConcreteFormat.FP32, input_bits),
            1: TypedVector(ConcreteFormat.FP32, (0x3F800000,) * STREAM_ELEMENTS),
            2: TypedVector(ConcreteFormat.FP32, (0xBF800000,) * STREAM_ELEMENTS),
        },
        destination_rank=1,
        management_paths={"s": ("am", "forward", "s")},
        accumulator=accumulator,
        partial_wire=partial_wire,
        output_format=output_format,
        mtu=1500,
        key=NATIVE_RESULT_KEY,
    )
    cocotb.start_soon(Clock(dut.clk, 4, unit="ns").start())
    probe = AxiRateProbe(dut)
    monitor = cocotb.start_soon(probe.run())
    try:
        result = await world.run_async(
            "native-result",
            backend=CocotbSingleBackend(
                dut, prism_name="s", start_clock=False, timeout_cycles=200_000
            ),
        )
    finally:
        monitor.cancel()

    one = decode_native(0x3F800000, ConcreteFormat.FP32)
    minus_one = decode_native(0xBF800000, ConcreteFormat.FP32)
    expected_pattern = tuple(
        round_native(
            combine_exact((decode_native(value, ConcreteFormat.FP32), one, minus_one)),
            output_format,
        )
        for value in pattern
    )
    expected_bits = tuple(
        expected_pattern[index % len(expected_pattern)] for index in range(STREAM_ELEMENTS)
    )
    assert result.rank_bits == {1: expected_bits}
    assert result.released_context
    width = {
        ConcreteFormat.INT8: 1,
        ConcreteFormat.FP16: 2,
        ConcreteFormat.BF16: 2,
        ConcreteFormat.FP32: 4,
    }[output_format]
    values_per_frame = 22 * (64 // width)
    expected_frames = []
    for frame_index, first in enumerate(range(0, STREAM_ELEMENTS, values_per_frame)):
        count = min(values_per_frame, STREAM_ELEMENTS - first)
        expected_frames.append(
            encode_data_frame(
                DataPacket(
                    PacketClass.RESULT,
                    NATIVE_RESULT_KEY,
                    11,
                    1,
                    1,
                    frame_index + 2,
                    first,
                    (NumberGroup(output_format, expected_bits[first : first + count]),),
                    last=first + count == STREAM_ELEMENTS,
                ),
                destination_mac=bytes.fromhex("020000000002"),
                source_mac=bytes.fromhex("020000000003"),
                mtu=1500,
                kulisch_bits=320,
            )
        )
    result_frames = [
        frame for port, frame in result.frames if port == 1 and frame[15] == PacketClass.RESULT
    ]
    assert result_frames == expected_frames
    egress = probe.window("m", 1, PacketClass.RESULT)
    assert egress.frames == len(expected_frames)
    numeric_bytes = STREAM_ELEMENTS * width
    numeric_gbps = egress.numeric_gbps(numeric_bytes)
    elements_per_second = STREAM_ELEMENTS * CLOCK_HZ / egress.cycles
    dut._log.info(
        "%s/%s RESULT numeric=%.2f Gb/s elements=%.3e/s AXI frame=%.2f Gb/s "
        "frames=%d beats=%d cycles=%d",
        accumulator.name,
        output_format.name,
        numeric_gbps,
        elements_per_second,
        egress.axi_gbps(),
        egress.frames,
        egress.beats,
        egress.cycles,
    )
    assert numeric_gbps >= TARGET_GBPS


@cocotb.test()
async def int8_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.INT8, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO
    )


@cocotb.test()
async def fp16_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.FP16, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO
    )


@cocotb.test()
async def bf16_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.BF16, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO
    )


@cocotb.test()
async def fp32_native_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.FP32, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO
    )


@cocotb.test()
async def fixed_kulisch_int8_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.INT8, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH
    )


@cocotb.test()
async def fixed_kulisch_fp16_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.FP16, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH
    )


@cocotb.test()
async def fixed_kulisch_bf16_result_stream_reaches_line_rate(dut: Any) -> None:
    await check_native_result(
        dut, ConcreteFormat.BF16, AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH
    )
