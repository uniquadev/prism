"""The U280 board top runs reductions from the library driver, frame by frame at the MAC.

The board top is simulated without __synthesis__: the MAC of the OpenNIC
shell is replaced by stream ports in the clock of the MAC, and everything
between those ports and the core is what the bitstream contains: the clocks
of the MMCM, the reset blocks and the packet adapter of the shell, the
bring-up sequencer and the core. Frames enter at no more than 100 Gb/s,
since a MAC cannot be held back, and leave as a MAC must send them: at
least 60 bytes and without a gap inside a frame.
"""

from __future__ import annotations

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from prism_ccl.application.single import ReplayTransport, run_single
from prism_ccl.cli.single_run import reduction
from prism_ccl.domain.model import ConcreteFormat, OperationKey, ResultWirePolicy
from prism_ccl.domain.numbers import round_native
from prism_ccl.wire.data import PacketClass

# Shortest frame a 100G MAC sends without padding it: 60 bytes before the FCS.
MINIMUM_FRAME_BYTES = 60
# Of every five cycles of the MAC clock, three carry a beat of 64 bytes:
# 0.6 * 64 * 8 bit * 322 MHz = 99 Gb/s, just under the line rate.
RX_PATTERN = (1, 1, 1, 0, 0)
# One operation takes about 7 us; 62 us without the awaited frame is a failure.
TIMEOUT_CYCLES = 20_000


class BoardPorts:
    """Frames of the manager and the ranks through the MAC ports of the board top."""

    def __init__(self, dut: Any) -> None:
        self.dut = dut
        # The port is a vector of one clock; edges are taken on the scalar inside.
        self.clock = dut.cmac_port[0].cmac_subsystem_inst.cmac_clk
        self.pending: list[tuple[int, bytes]] = []
        self.history: list[tuple[int, bytes]] = []
        self.sent: list[tuple[int, bytes]] = []
        self.problems: list[str] = []
        self.phase = 0
        self._monitor: Any = None

    def start(self) -> None:
        self._monitor = cocotb.start_soon(self._capture())

    def stop(self) -> None:
        if self._monitor is not None:
            self._monitor.cancel()

    async def _capture(self) -> None:
        dut = self.dut
        frame = bytearray()
        while True:
            await RisingEdge(self.clock)
            await ReadOnly()
            valid = int(dut.sim_tx_tvalid.value)
            if not valid:
                if frame:
                    self.problems.append(f"a gap inside a frame after {len(frame)} bytes")
                continue
            keep = int(dut.sim_tx_tkeep.value)
            if keep != (1 << keep.bit_count()) - 1:
                self.problems.append(f"a beat with keep {keep:#x}")
            frame.extend(int(dut.sim_tx_tdata.value).to_bytes(64, "little")[: keep.bit_count()])
            if int(dut.sim_tx_tlast.value):
                if int(dut.sim_tx_tuser_err.value):
                    self.problems.append("a frame marked as an error")
                if len(frame) < MINIMUM_FRAME_BYTES:
                    self.problems.append(f"a frame of {len(frame)} bytes")
                self.pending.append((0, bytes(frame)))
                self.history.append((0, bytes(frame)))
                frame.clear()

    async def send(self, port: int, frame: bytes) -> None:
        assert port == 0
        dut = self.dut
        offsets = range(0, len(frame), 64)
        for offset in offsets:
            while not RX_PATTERN[self.phase]:
                dut.sim_rx_tvalid.value = 0
                self.phase = (self.phase + 1) % len(RX_PATTERN)
                await RisingEdge(self.clock)
            beat = frame[offset : offset + 64]
            dut.sim_rx_tdata.value = int.from_bytes(beat.ljust(64, b"\0"), "little")
            dut.sim_rx_tkeep.value = (1 << len(beat)) - 1
            dut.sim_rx_tlast.value = int(offset + 64 >= len(frame))
            dut.sim_rx_tvalid.value = 1
            self.phase = (self.phase + 1) % len(RX_PATTERN)
            await RisingEdge(self.clock)
        dut.sim_rx_tvalid.value = 0
        self.sent.append((port, frame))

    async def receive(
        self, packet_class: PacketClass, *, port: int, destination_mac: bytes | None = None
    ) -> bytes:
        for _ in range(TIMEOUT_CYCLES):
            for index, (seen, frame) in enumerate(self.pending):
                if (
                    seen == port
                    and frame[15] == packet_class
                    and (destination_mac is None or frame[:6] == destination_mac)
                ):
                    return self.pending.pop(index)[1]
            await RisingEdge(self.clock)
        raise TimeoutError(f"the board sent no {packet_class.name} frame on port {port}")


_booted = False


async def boot(dut: Any) -> None:
    """Power the board on once: the MMCM locks, the shell and the core leave reset."""
    global _booted
    if _booted:
        return
    dut.sysclk_n.value = 0
    dut.sim_rx_tvalid.value = 0
    dut.sim_rx_tdata.value = 0
    dut.sim_rx_tkeep.value = 0
    dut.sim_rx_tlast.value = 0
    dut.sim_rx_tuser_err.value = 0
    dut.sim_tx_tready.value = 1
    # The oscillator stops with this test; the MMCM keeps the lock it has by then.
    cocotb.start_soon(Clock(dut.sysclk_p, 10, unit="ns").start())
    for _ in range(200):
        await Timer(1, unit="us")
        if int(dut.core_rst_n.value) and int(dut.cmac_rst_done.value):
            break
    else:
        raise AssertionError("the board did not leave its reset within 200 us")
    # The bring-up sequencer has reset the MAC and written its registers.
    await Timer(20, unit="us")
    assert int(dut.hbm_cattrip.value) == 0
    assert int(dut.cmac_rst_done.value) == 1
    _booted = True


_operations = 0


async def run_reduction(
    dut: Any, input_format: ConcreteFormat, output: ResultWirePolicy, elements: int
) -> None:
    global _operations
    await boot(dut)
    # The board stays powered across the tests, so each operation is a new one.
    _operations += 1
    scenario, binding, expected = reduction(
        input_format, output, elements, key=OperationKey(1, 1, 0, _operations, 0)
    )
    ports = BoardPorts(dut)
    ports.start()
    try:
        outcome = await run_single(scenario, binding, ports)
        # Frames still on their way would belong to the next operation.
        await Timer(5, unit="us")
    finally:
        ports.stop()
    assert not ports.problems, ports.problems
    assert outcome.rank_values == {1: expected}
    if output != ResultWirePolicy.AUTO and output != ResultWirePolicy.KULISCH:
        native = ConcreteFormat(int(output))
        assert outcome.rank_bits == {1: tuple(round_native(x, native) for x in expected)}
    # Every frame the board sent was one the operation expected.
    assert not ports.pending, f"{len(ports.pending)} frames nobody asked for"
    replay = ReplayTransport(ports.history)
    assert await run_single(scenario, binding, replay) == outcome
    assert replay.sent == ports.sent


@cocotb.test()
async def fp32_reduction_with_an_fp32_result(dut: Any) -> None:
    await run_reduction(dut, ConcreteFormat.FP32, ResultWirePolicy.FP32, 512)


@cocotb.test()
async def fp32_reduction_with_an_automatic_result(dut: Any) -> None:
    await run_reduction(dut, ConcreteFormat.FP32, ResultWirePolicy.AUTO, 512)


@cocotb.test()
async def bf16_reduction_with_a_kulisch_result(dut: Any) -> None:
    await run_reduction(dut, ConcreteFormat.BF16, ResultWirePolicy.KULISCH, 256)


@cocotb.test()
async def int8_reduction_with_an_int8_result(dut: Any) -> None:
    await run_reduction(dut, ConcreteFormat.INT8, ResultWirePolicy.INT8, 1024)


@cocotb.test()
async def fp16_reduction_of_a_long_vector(dut: Any) -> None:
    await run_reduction(dut, ConcreteFormat.FP16, ResultWirePolicy.FP16, 4096)
