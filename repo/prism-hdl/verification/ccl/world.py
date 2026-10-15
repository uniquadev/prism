"""PrismWorld binding to one already elaborated two-port SINGLE DUT."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from prism_ccl.application.reordering import ReorderPlan
from prism_ccl.application.single import (
    RankBinding,
    SingleBinding,
    compile_single,
    rank_data_frames,
)
from prism_ccl.application.software import Scenario
from prism_ccl.domain.capabilities import single_rtl_capabilities
from prism_ccl.domain.model import ConcreteFormat, ResultWirePolicy
from prism_ccl.domain.numbers import ExactValue, decode_kulisch, decode_native
from prism_ccl.domain.topology import PhysicalNetwork
from prism_ccl.wire.control import (
    ControlCommand,
    ControlPacket,
    ControlStatus,
    decode_control_frame,
    encode_control_frame,
)
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
)

from .capture import ObservedCapture


@dataclass(frozen=True, slots=True)
class CocotbResult:
    rank_bits: dict[int, tuple[int, ...]] | None
    sent_frames: tuple[tuple[int, bytes], ...]
    frames: tuple[tuple[int, bytes], ...]
    cycles: int
    stalled_output_beats: int
    released_context: bool
    data_to_result_cycles: int
    timing: CocotbTiming
    stalled_input_beats: tuple[int, ...]
    final_contribution_latency_cycles: int | None = None
    final_contribution_ingress_cycles: int | None = None
    final_packet_to_result_cycles: int | None = None
    rank_values: dict[int, tuple[ExactValue, ...]] | None = None
    rank_groups: dict[int, tuple[NumberGroup, ...]] | None = None


@dataclass(frozen=True, slots=True)
class FrameObservation:
    direction: str
    port: int
    first_cycle: int
    last_cycle: int
    frame: bytes


@dataclass(frozen=True, slots=True)
class CocotbTiming:
    stage_first_cycle: int
    commit_ack_last_cycle: int
    data_first_cycle: int
    data_last_cycle: int
    result_first_cycle: int
    result_last_cycle: int

    @property
    def collective_cycles(self) -> int:
        return self.result_last_cycle - self.stage_first_cycle + 1

    @property
    def setup_cycles(self) -> int:
        return self.commit_ack_last_cycle - self.stage_first_cycle + 1

    @property
    def data_to_result_cycles(self) -> int:
        return self.result_last_cycle - self.data_first_cycle + 1

    @property
    def data_window_cycles(self) -> int:
        return self.data_last_cycle - self.data_first_cycle + 1

    @property
    def result_window_cycles(self) -> int:
        return self.result_last_cycle - self.result_first_cycle + 1


def summarize_timing(
    observations: Sequence[FrameObservation],
    *,
    mtu: int,
    belongs: Callable[[bytes], bool] | None = None,
) -> CocotbTiming:
    """Use accepted AXI beats, not the host's frame dequeue time.

    DATA and RESULT frames that `belongs` turns down are not of the operation
    that is measured: another operation may still be on the wire.
    """
    stage = None
    commit_ack = None
    data: list[FrameObservation] = []
    results: list[FrameObservation] = []
    for observed in observations:
        packet_class = PacketClass(observed.frame[15])
        if (
            belongs is not None
            and packet_class in (PacketClass.DATA, PacketClass.RESULT)
            and not belongs(observed.frame)
        ):
            continue
        if observed.direction == "rx" and packet_class == PacketClass.DATA:
            data.append(observed)
        elif observed.direction == "tx" and packet_class == PacketClass.RESULT:
            results.append(observed)
        elif packet_class == PacketClass.CONTROL:
            control = decode_control_frame(observed.frame, mtu=mtu)
            if observed.direction == "rx" and control.command == ControlCommand.STAGE:
                stage = observed
            elif (
                observed.direction == "tx"
                and control.command == ControlCommand.ACK
                and control.transaction_id == 11
            ):
                commit_ack = observed
    if stage is None or commit_ack is None or not data or not results:
        raise AssertionError("incomplete STAGE, COMMIT ACK, DATA or RESULT observations")
    timing = CocotbTiming(
        stage.first_cycle,
        commit_ack.last_cycle,
        min(observed.first_cycle for observed in data),
        max(observed.last_cycle for observed in data),
        min(observed.first_cycle for observed in results),
        max(observed.last_cycle for observed in results),
    )
    if not (
        timing.stage_first_cycle
        <= timing.commit_ack_last_cycle
        < timing.data_first_cycle
        <= timing.result_last_cycle
    ):
        raise AssertionError("observed collective milestones are out of order")
    return timing


class CompiledFramePorts:
    """Keep AXI beats and Cocotb scheduling out of the scenario and domain."""

    def __init__(
        self,
        dut: Any,
        *,
        timeout_cycles: int,
        physical_ports: int = 2,
        output_stall_period: int = 0,
        capture: ObservedCapture | None = None,
    ) -> None:
        if output_stall_period == 1 or output_stall_period < 0:
            raise ValueError("output stall period must be zero or at least two cycles")
        if not 1 <= physical_ports <= 2:
            raise ValueError("Cocotb scalar wrapper exposes one or two physical ports")
        self.dut = dut
        self.physical_ports = physical_ports
        self.timeout_cycles = timeout_cycles
        self.output_stall_period = output_stall_period
        self.capture = capture
        self.pending: list[tuple[int, bytes]] = []
        self.history: list[tuple[int, bytes]] = []
        self.transmitted: list[tuple[int, bytes]] = []
        self.observations: list[FrameObservation] = []
        self.cycles = 0
        self.stalled_output_beats = 0
        self.stalled_input_beats = [0] * physical_ports
        self._monitor: Any = None

    async def start(self, node_mac: bytes, *, start_clock: bool = True) -> None:
        if start_clock:
            cocotb.start_soon(Clock(self.dut.clk, 4, unit="ns").start())
        self.dut.rst_n.value = 0
        self.dut.millisecond_tick.value = 0
        self.dut.laboratory_extension_enabled.value = 0
        for port in range(self.physical_ports):
            getattr(self.dut, f"local_mac_{port}").value = int.from_bytes(node_mac, "big")
            for name in ("tdata", "tkeep", "tlast", "tuser", "tvalid"):
                getattr(self.dut, f"s{port}_{name}").value = 0
            getattr(self.dut, f"m{port}_tready").value = 1
        for _ in range(3):
            await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.dut.rst_n.value = 1
        self._monitor = cocotb.start_soon(self._capture())

    async def _capture(self) -> None:
        partial = [bytearray() for _ in range(self.physical_ports)]
        ingress_partial = [bytearray() for _ in range(self.physical_ports)]
        ingress_start: list[int | None] = [None] * self.physical_ports
        egress_start: list[int | None] = [None] * self.physical_ports
        held_beats: list[tuple[int, int, int, int] | None] = [None] * self.physical_ports
        while True:
            await FallingEdge(self.dut.clk)
            if self.output_stall_period:
                ready = int(self.cycles % self.output_stall_period != 0)
                for port in range(self.physical_ports):
                    getattr(self.dut, f"m{port}_tready").value = ready
            await ReadOnly()
            self.cycles += 1
            for port in range(self.physical_ports):
                rx_valid = int(getattr(self.dut, f"s{port}_tvalid").value)
                rx_ready = int(getattr(self.dut, f"s{port}_tready").value)
                if rx_valid and not rx_ready:
                    self.stalled_input_beats[port] += 1
                if rx_valid and rx_ready:
                    started = ingress_start[port]
                    if started is None:
                        started = self.cycles
                        ingress_start[port] = started
                    data = int(getattr(self.dut, f"s{port}_tdata").value)
                    keep = int(getattr(self.dut, f"s{port}_tkeep").value)
                    ingress_partial[port].extend(
                        value
                        for lane, value in enumerate(data.to_bytes(64, "little"))
                        if keep & (1 << lane)
                    )
                    if int(getattr(self.dut, f"s{port}_tlast").value):
                        frame_bytes = bytes(ingress_partial[port])
                        self.observations.append(
                            FrameObservation("rx", port, started, self.cycles, frame_bytes)
                        )
                        if self.capture is not None:
                            self.capture.record(
                                port=port,
                                direction="rx",
                                frame=(int(get_sim_time(unit="ns")), frame_bytes),
                            )
                        ingress_partial[port].clear()
                        ingress_start[port] = None
                valid = int(getattr(self.dut, f"m{port}_tvalid").value)
                ready = int(getattr(self.dut, f"m{port}_tready").value)
                beat = (
                    int(getattr(self.dut, f"m{port}_tdata").value),
                    int(getattr(self.dut, f"m{port}_tkeep").value),
                    int(getattr(self.dut, f"m{port}_tlast").value),
                    int(getattr(self.dut, f"m{port}_frame_bytes").value),
                )
                if held_beats[port] is not None and (not valid or beat != held_beats[port]):
                    raise AssertionError(f"DUT changed stalled AXI beat on port {port}")
                held_beats[port] = beat if valid and not ready else None
                if valid and not ready:
                    self.stalled_output_beats += 1
                if valid and ready:
                    started = egress_start[port]
                    if started is None:
                        started = self.cycles
                        egress_start[port] = started
                    keep = beat[1]
                    if keep != (1 << keep.bit_count()) - 1:
                        raise AssertionError("DUT emitted a noncontiguous AXI TKEEP")
                    partial[port].extend(beat[0].to_bytes(64, "little")[: keep.bit_count()])
                    if beat[2]:
                        if len(partial[port]) != beat[3]:
                            raise AssertionError("DUT frame length disagrees with AXI beats")
                        frame = (port, bytes(partial[port]))
                        self.pending.append(frame)
                        self.history.append(frame)
                        self.observations.append(
                            FrameObservation("tx", port, started, self.cycles, frame[1])
                        )
                        if self.capture is not None:
                            self.capture.record(
                                port=port,
                                direction="tx",
                                frame=(int(get_sim_time(unit="ns")), frame[1]),
                            )
                        partial[port].clear()
                        egress_start[port] = None

    async def send(self, port: int, frame: bytes) -> None:
        await self.send_many(port, (frame,))

    async def send_many(self, port: int, frames: Sequence[bytes]) -> None:
        for frame in frames:
            for offset in range(0, len(frame), 64):
                beat = frame[offset : offset + 64]
                for _ in range(self.timeout_cycles):
                    await FallingEdge(self.dut.clk)
                    getattr(self.dut, f"s{port}_tdata").value = int.from_bytes(
                        beat.ljust(64, b"\0"), "little"
                    )
                    getattr(self.dut, f"s{port}_tkeep").value = (1 << len(beat)) - 1
                    getattr(self.dut, f"s{port}_tlast").value = int(
                        offset + len(beat) == len(frame)
                    )
                    getattr(self.dut, f"s{port}_tvalid").value = 1
                    await ReadOnly()
                    if int(getattr(self.dut, f"s{port}_tready").value):
                        await RisingEdge(self.dut.clk)
                        break
                else:
                    raise TimeoutError(f"DUT ingress port {port} stalled for a full frame")
            self.transmitted.append((port, frame))
        await FallingEdge(self.dut.clk)
        getattr(self.dut, f"s{port}_tvalid").value = 0

    async def receive(
        self,
        packet_class: PacketClass,
        *,
        port: int | None = None,
        destination_mac: bytes | None = None,
    ) -> bytes:
        for _ in range(self.timeout_cycles):
            for index, (seen_port, frame) in enumerate(self.pending):
                if (
                    frame[15] == packet_class
                    and (port is None or seen_port == port)
                    and (destination_mac is None or frame[:6] == destination_mac)
                ):
                    self.pending.pop(index)
                    return frame
            await FallingEdge(self.dut.clk)
        raise TimeoutError(f"DUT emitted no {packet_class.name} on port {port}")

    def stop(self) -> None:
        if self._monitor is not None:
            self._monitor.cancel()


class CocotbSingleBackend:
    """Run one PrismWorld operation against an already compiled SINGLE instance."""

    def __init__(
        self,
        dut: Any,
        *,
        prism_name: str,
        manager_mac: bytes = bytes.fromhex("020000000000"),
        timeout_cycles: int = 6000,
        output_stall_period: int = 0,
        start_clock: bool = True,
        capture_dir: Path | None = None,
        reorder: ReorderPlan | None = None,
        physical_ports: int = 2,
        preload_first_rank: bool = False,
        preload_all_but_last: bool = False,
        preload_settle_cycles: int = 64,
        prelude: Callable[[CompiledFramePorts], Awaitable[None]] | None = None,
    ) -> None:
        if preload_settle_cycles < 0:
            raise ValueError("preload settle cycles cannot be negative")
        if preload_first_rank and preload_all_but_last:
            raise ValueError("choose one preload mode")
        self.dut = dut
        self.prism_name = prism_name
        self.manager_mac = manager_mac
        self.timeout_cycles = timeout_cycles
        self.output_stall_period = output_stall_period
        self.start_clock = start_clock
        self.capture_dir = capture_dir
        self.reorder = reorder or ReorderPlan()
        self.physical_ports = physical_ports
        self.preload_first_rank = preload_first_rank
        self.preload_all_but_last = preload_all_but_last
        self.preload_settle_cycles = preload_settle_cycles
        # Traffic to drive after the reset and before the operation starts.
        self.prelude = prelude

    async def run(self, network: PhysicalNetwork, scenario: Scenario) -> CocotbResult:
        binding = compile_single(
            network, scenario, self.prism_name, physical_ports=self.physical_ports
        )
        if binding.manager_mac != self.manager_mac:
            raise ValueError("scenario AM MAC differs from compiled DUT trust binding")
        rank_names = {
            node.rank_id: node.name for node in scenario.tree.nodes if node.rank_id is not None
        }
        expected_reorder_flows = {
            (rank_names[rank.rank], self.prism_name, PacketClass.DATA) for rank in binding.ranks
        }
        if any(
            (rule.source, rule.destination, rule.packet_class) not in expected_reorder_flows
            for rule in self.reorder.rules
        ):
            raise ValueError("SINGLE reorder rule does not name a bound rank DATA flow")
        ports = CompiledFramePorts(
            self.dut,
            timeout_cycles=self.timeout_cycles,
            physical_ports=self.physical_ports,
            output_stall_period=self.output_stall_period,
            capture=ObservedCapture(self.capture_dir) if self.capture_dir is not None else None,
        )
        await ports.start(binding.node_mac, start_clock=self.start_clock)
        staged = False
        try:
            if self.prelude is not None:
                await self.prelude(ports)
                # What follows is measured and checked on its own.
                ports.pending.clear()
                ports.history.clear()
                ports.transmitted.clear()
                ports.observations.clear()
            window_packets = min(
                single_rtl_capabilities()
                .require(scenario.config, vector.format)
                .maximum_replay_frames_per_binding
                for vector in scenario.vectors.values()
            )
            self.reorder.require_window_capacity(window_packets)
            await self._control(
                ports, scenario, binding, ControlCommand.STAGE, 10, binding.context.pack()
            )
            staged = True
            await self._control(ports, scenario, binding, ControlCommand.COMMIT, 11)

            async def send_rank(rank_binding: RankBinding) -> list[DataPacket]:
                frames, sent_packets = rank_data_frames(scenario, binding, rank_binding)
                order = self.reorder.arrange(
                    list(range(len(frames))),
                    source=rank_names[rank_binding.rank],
                    destination=self.prism_name,
                    packet_class=PacketClass.DATA,
                    stream_id=rank_binding.local_endpoint,
                )
                frames = [frames[index] for index in order]
                sent_packets = [sent_packets[index] for index in order]
                await ports.send_many(rank_binding.port, frames)
                return sent_packets

            async def send_port(ranks: list[RankBinding]) -> None:
                for rank_binding in ranks:
                    await send_rank(rank_binding)

            port_ranks: dict[int, list[RankBinding]] = {}
            for rank_binding in binding.ranks:
                port_ranks.setdefault(rank_binding.port, []).append(rank_binding)
            if self.preload_first_rank or self.preload_all_but_last:
                if (
                    (self.preload_first_rank and len(binding.ranks) != 2)
                    or self.reorder.all_data_probability > 0
                    or any(rule.probability > 0 for rule in self.reorder.rules)
                ):
                    raise ValueError("preload measurement requires ordered DATA")
                *prior, final = sorted(binding.ranks, key=lambda rank: rank.rank)
                for rank_binding in prior:
                    await send_rank(rank_binding)
                for _ in range(self.preload_settle_cycles):
                    await RisingEdge(self.dut.clk)
                if any(
                    observed.direction == "tx"
                    and PacketClass(observed.frame[15]) == PacketClass.RESULT
                    for observed in ports.observations
                ):
                    raise AssertionError("RESULT appeared before the final rank contributed")
                await send_rank(final)
            else:
                tasks = [cocotb.start_soon(send_port(ranks)) for ranks in port_ranks.values()]
                for task in tasks:
                    await task

            native_output = scenario.config.output_format in (
                ResultWirePolicy.INT8,
                ResultWirePolicy.FP16,
                ResultWirePolicy.BF16,
                ResultWirePolicy.FP32,
            )
            rank_bits: dict[int, tuple[int, ...]] | None = {} if native_output else None
            rank_values: dict[int, tuple[ExactValue, ...]] = {}
            rank_groups: dict[int, tuple[NumberGroup, ...]] = {}
            for rank_binding in binding.ranks:
                if not rank_binding.result_enabled:
                    continue
                pieces: dict[int, tuple[int | bytes, ...]] = {}
                packet_groups: dict[int, tuple[NumberGroup, ...]] = {}
                identities: dict[int, bytes] = {}
                watermark = 0
                last_seen = False
                received_frames = 0
                while watermark != scenario.config.element_count or not last_seen:
                    frame = await ports.receive(
                        PacketClass.RESULT,
                        port=rank_binding.port,
                        destination_mac=rank_binding.peer_mac,
                    )
                    result = decode_data_frame(
                        frame,
                        mtu=scenario.config.mtu,
                        kulisch_bits=scenario.config.kulisch_bits,
                    )
                    if result.accumulation_inexact:
                        raise ArithmeticError(
                            f"operation {scenario.config.key}: rank {rank_binding.rank} "
                            "received ACCUMULATION_INEXACT; no result vector is valid"
                        )
                    received_frames += 1
                    if received_frames > scenario.config.element_count:
                        raise AssertionError("RESULT stream exceeds the vector packet bound")
                    if (
                        result.packet_class != PacketClass.RESULT
                        or result.operation != scenario.config.key
                        or result.source_endpoint != rank_binding.local_endpoint
                        or result.destination_endpoint != rank_binding.peer_endpoint
                        or result.stream_id != rank_binding.peer_endpoint
                        or result.first_element + result.element_count
                        > scenario.config.element_count
                        or result.last
                        != (
                            result.first_element + result.element_count
                            == scenario.config.element_count
                        )
                        or (
                            scenario.config.output_format != ResultWirePolicy.AUTO
                            and any(
                                group.format != ConcreteFormat(int(scenario.config.output_format))
                                for group in result.groups
                            )
                        )
                    ):
                        raise AssertionError(
                            f"operation {scenario.config.key}: rank {rank_binding.rank} "
                            f"received a mismatched RESULT"
                        )
                    previous = identities.get(result.packet_id)
                    if previous is not None:
                        raise AssertionError("duplicate RESULT packet")
                    if previous is None:
                        start = result.first_element
                        end = start + result.element_count
                        if any(
                            start < position + len(values) and end > position
                            for position, values in pieces.items()
                        ):
                            raise AssertionError(
                                "RESULT intervals overlap under different packet IDs"
                            )
                        identities[result.packet_id] = frame
                        decoded_values = tuple(
                            value for group in result.groups for value in group.values
                        )
                        pieces[start] = decoded_values
                        packet_groups[start] = result.groups
                        if result.last:
                            last_seen = True
                        while watermark in pieces:
                            watermark += len(pieces[watermark])
                ordered = tuple(value for first in sorted(pieces) for value in pieces[first])
                rank_groups[rank_binding.rank] = tuple(
                    group for first in sorted(packet_groups) for group in packet_groups[first]
                )
                rank_values[rank_binding.rank] = tuple(
                    decode_kulisch(value, scenario.config.kulisch_bits)
                    if isinstance(value, bytes)
                    else decode_native(value, group.format)
                    for group in rank_groups[rank_binding.rank]
                    for value in group.values
                )
                if native_output:
                    assert rank_bits is not None
                    if any(not isinstance(value, int) for value in ordered):
                        raise AssertionError("native RESULT contains non-native values")
                    rank_bits[rank_binding.rank] = cast(tuple[int, ...], ordered)
            timing = summarize_timing(
                ports.observations,
                mtu=scenario.config.mtu,
                belongs=lambda frame: (
                    decode_data_frame(
                        frame, mtu=scenario.config.mtu, kulisch_bits=scenario.config.kulisch_bits
                    ).operation
                    == scenario.config.key
                ),
            )
            final_latency = None
            final_ingress = None
            final_packet_to_result = None
            if self.preload_first_rank or self.preload_all_but_last:
                final_data = [
                    observed
                    for observed in ports.observations
                    if observed.direction == "rx"
                    and observed.port == final.port
                    and PacketClass(observed.frame[15]) == PacketClass.DATA
                    and observed.frame[6:12] == final.peer_mac
                    and decode_data_frame(
                        observed.frame,
                        mtu=scenario.config.mtu,
                        kulisch_bits=scenario.config.kulisch_bits,
                    ).destination_endpoint
                    == final.local_endpoint
                ]
                if not final_data or timing.result_first_cycle <= final_data[0].first_cycle:
                    raise AssertionError("final DATA and RESULT milestones are inconsistent")
                final_latency = timing.result_first_cycle - final_data[0].first_cycle
                final_ingress = final_data[-1].last_cycle - final_data[0].first_cycle + 1
                final_packet_to_result = timing.result_first_cycle - final_data[-1].last_cycle
            await self._control(ports, scenario, binding, ControlCommand.RELEASE, 12)
            return CocotbResult(
                rank_bits,
                tuple(ports.transmitted),
                tuple(ports.history),
                ports.cycles,
                ports.stalled_output_beats,
                True,
                timing.data_to_result_cycles,
                timing,
                tuple(ports.stalled_input_beats),
                final_latency,
                final_ingress,
                final_packet_to_result,
                rank_values,
                rank_groups,
            )
        except Exception as error:
            if staged:
                try:
                    await self._control(ports, scenario, binding, ControlCommand.ABORT, 13)
                except (AssertionError, TimeoutError) as cleanup_error:
                    raise RuntimeError(
                        f"operation {scenario.config.key} failed ({error}); "
                        f"ABORT also failed ({cleanup_error})"
                    ) from error
            raise
        finally:
            ports.stop()
            if ports.capture is not None:
                ports.capture.write()

    async def _control(
        self,
        ports: CompiledFramePorts,
        scenario: Scenario,
        binding: SingleBinding,
        command: ControlCommand,
        transaction: int,
        body: bytes = b"",
    ) -> None:
        packet = ControlPacket(scenario.config.key, transaction, 0xFFFE, 0xFFFE, command, body=body)
        await ports.send(
            0,
            encode_control_frame(
                packet,
                destination_mac=binding.node_mac,
                source_mac=binding.manager_mac,
                mtu=scenario.config.mtu,
            ),
        )
        response = decode_control_frame(
            await ports.receive(PacketClass.CONTROL, port=0), mtu=scenario.config.mtu
        )
        if (
            response.command != ControlCommand.ACK
            or response.transaction_id != transaction
            or response.status != ControlStatus.OK
        ):
            raise AssertionError(
                f"operation {scenario.config.key}: {command.name} returned {response}"
            )
