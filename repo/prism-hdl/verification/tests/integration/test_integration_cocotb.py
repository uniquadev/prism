from __future__ import annotations

import os
import struct
from itertools import pairwise
from pathlib import Path
from typing import Any

import cocotb
from ccl.capture import ObservedCapture
from cocotb.clock import Clock
from cocotb.queue import Queue
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, SimTimeoutError, Timer, with_timeout
from cocotb.utils import get_sim_time
from prism_ccl.collectives.reference import fp32_sum_bits
from prism_ccl.protocol.constants import (
    CHUNK_PAYLOAD_BYTES,
    ETHERTYPE,
    AccumulatorProfile,
    CollectiveSemantic,
    ControlCommand,
    ControlFlag,
    DataFlag,
    NextHopType,
    NodeRole,
    Opcode,
    PartialWireFormat,
    ReductionOperator,
    Status,
    TlvType,
    WireFormat,
)
from prism_ccl.protocol.models import (
    Capabilities,
    ContributorBinding,
    GroupDescriptor,
    NextHopEntry,
    OperationDescriptor,
    ReplicationGroup,
    ResultRangeRoute,
    UpstreamAction,
)
from prism_ccl.protocol.serialization import (
    ControlFrame,
    ControlHeader,
    ControlWord,
    DataHeader,
    GroupHandleWire,
    OperationHandleWire,
    OperationIdentity,
    ResultHeader,
    Tlv,
    pack_tlvs,
)

LOCAL_MACS = (bytes.fromhex("025052495300"), bytes.fromhex("025052495301"))
HOST_MACS = (bytes.fromhex("020000000001"), bytes.fromhex("020000000002"))
JOB_ID = 0x1020304050607080
TRACE_NAME = "test_reduce_and_allreduce_cross_full_two_port_pipeline"


def ethernet(destination: bytes, source: bytes, payload: bytes) -> bytes:
    """Build a minimum-sized Ethernet frame around one PRISM payload."""

    frame = destination + source + ETHERTYPE.to_bytes(2, "big") + payload
    return frame + bytes(max(0, 60 - len(frame)))


def control_payload(
    cookie: int,
    transaction: int,
    command: ControlCommand,
    tlvs: tuple[Tlv, ...] = (),
) -> bytes:
    """Encode a control request; this is stateless protocol construction."""

    payload = pack_tlvs(tlvs)
    if len(payload) < 20:
        payload += struct.pack("!HHI", 0xFFFE, 0, 12) + bytes(16)
    return ControlFrame(
        ControlHeader(cookie, transaction, command, ControlFlag.REQUEST | ControlFlag.ACK_REQUIRED),
        payload,
    ).pack()


def handle_tlv(group_id: int) -> Tlv:
    return Tlv(TlvType.GROUP_HANDLE, GroupHandleWire(group_id, 1).pack())


def operation_tlv(operation_id: int) -> Tlv:
    return Tlv(TlvType.OPERATION_HANDLE, OperationHandleWire(operation_id, 1).pack())


class PrismIntegrationWorld:
    """Own the stateful DUT world used by full-pipeline scenarios.

    The world owns clock/reset, AXI handshakes, response queues, observations,
    diagnostics, and management lifecycle operations. Pure packet construction
    remains outside the class because it has no world state.
    """

    def __init__(self, dut: Any) -> None:
        self.dut = dut
        self.rx_observed: list[list[tuple[int, bytes]]] = [[], []]
        self.tx_observed: list[list[tuple[int, bytes]]] = [[], []]
        self.rx_queues = [Queue(), Queue()]
        self.tx_queues = [Queue(), Queue()]

    async def start(self, *, stall_outputs: bool = True) -> None:
        cocotb.start_soon(Clock(self.dut.clk, 4, unit="ns").start())
        self.dut.rst_n.value = 0
        self.dut.millisecond_tick.value = 0
        self.dut.laboratory_extension_enabled.value = 1
        self.dut.local_mac_0.value = int.from_bytes(LOCAL_MACS[0], "big")
        self.dut.local_mac_1.value = int.from_bytes(LOCAL_MACS[1], "big")
        for port in range(2):
            getattr(self.dut, f"s{port}_tvalid").value = 0
            getattr(self.dut, f"s{port}_tdata").value = 0
            getattr(self.dut, f"s{port}_tkeep").value = 0
            getattr(self.dut, f"s{port}_tlast").value = 0
            getattr(self.dut, f"s{port}_tuser").value = 0
            getattr(self.dut, f"m{port}_tready").value = 1
        for _ in range(8):
            await RisingEdge(self.dut.clk)
        self.dut.rst_n.value = 1
        for port in range(2):
            cocotb.start_soon(
                self._monitor(f"s{port}_", self.rx_queues[port], self.rx_observed[port])
            )
            cocotb.start_soon(
                self._monitor(f"m{port}_", self.tx_queues[port], self.tx_observed[port])
            )
            if stall_outputs:
                cocotb.start_soon(self._drive_output_ready(port))

    async def _drive_output_ready(self, port: int) -> None:
        """Apply repeatable independent stalls to the complete egress pipeline."""

        cycle = 0
        signal = getattr(self.dut, f"m{port}_tready")
        while True:
            await FallingEdge(self.dut.clk)
            cycle += 1
            signal.value = int((cycle + 2 * port) % 7 not in (2, 3))

    async def _send_frame(self, port: int, frame: bytes) -> None:
        prefix = f"s{port}_"
        for offset in range(0, len(frame), 64):
            beat = frame[offset : offset + 64]
            await FallingEdge(self.dut.clk)
            getattr(self.dut, prefix + "tdata").value = int.from_bytes(beat, "little")
            getattr(self.dut, prefix + "tkeep").value = (1 << len(beat)) - 1
            getattr(self.dut, prefix + "tlast").value = offset + len(beat) == len(frame)
            getattr(self.dut, prefix + "tuser").value = 0
            getattr(self.dut, prefix + "tvalid").value = 1
            while True:
                await ReadOnly()
                accepted = int(getattr(self.dut, prefix + "tready").value)
                await RisingEdge(self.dut.clk)
                if accepted:
                    break
                await FallingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        getattr(self.dut, prefix + "tvalid").value = 0

    async def _monitor(
        self,
        prefix: str,
        queue: Queue,
        observed: list[tuple[int, bytes]],
    ) -> None:
        frame = bytearray()
        frame_timestamp_ns: int | None = None
        while True:
            await FallingEdge(self.dut.clk)
            await ReadOnly()
            if not (
                int(getattr(self.dut, prefix + "tvalid").value)
                and int(getattr(self.dut, prefix + "tready").value)
            ):
                continue
            data = int(getattr(self.dut, prefix + "tdata").value).to_bytes(64, "little")
            keep = int(getattr(self.dut, prefix + "tkeep").value)
            last = int(getattr(self.dut, prefix + "tlast").value)
            await RisingEdge(self.dut.clk)
            if not frame:
                frame_timestamp_ns = int(get_sim_time(unit="ns"))
            frame.extend(data[index] for index in range(64) if keep & (1 << index))
            if last:
                complete = bytes(frame)
                assert frame_timestamp_ns is not None
                observed.append((frame_timestamp_ns, complete))
                frame.clear()
                frame_timestamp_ns = None
                # Queue wake-up must occur after the read-only simulator phase.
                await Timer(1, unit="ps")
                await queue.put(complete)

    def _log_control_timeout(self, command: ControlCommand, transaction: int) -> None:
        core = self.dut.u_core
        self.dut._log.error(
            "control timeout command=%s txn=%d core(req=%s result=%s hdr=%s byte=%s tx=%s/%s)",
            command.name,
            transaction,
            core.control_request_valid.value,
            core.control_result_valid.value,
            core.response_header_valid.value,
            core.response_byte_valid.value,
            core.control_tx_valid.value,
            core.control_tx_ready.value,
        )
        reassembler = core.u_control_reassembler
        decoder = core.u_tlv_decoder
        stager = core.u_control_stager
        sessions = core.u_control_executor.u_session_table
        self.dut._log.error(
            "reassembler(write=%s output=%s header=%s context=%s fragment=%s offset=%s "
            "contexts=%s complete=%s lengths=%s input_lengths=%s) "
            "decoder(state=%s consumed=%s event=%s) stager(valid=%s status=%s length=%s index=%s) "
            "sessions(valid=%s result=%s)",
            reassembler.write_active.value,
            reassembler.output_active.value,
            reassembler.output_header_sent.value,
            reassembler.output_context.value,
            reassembler.output_fragment.value,
            reassembler.output_offset.value,
            reassembler.context_valid.value,
            reassembler.context_complete.value,
            reassembler.total_length.value,
            core.fragment_length.value,
            decoder.state.value,
            decoder.bytes_consumed.value,
            decoder.m_event_valid.value,
            stager.m_request_valid.value,
            stager.staging_status.value,
            stager.current_length.value,
            stager.value_index.value,
            sessions.valid.value,
            sessions.m_result_valid.value,
        )

    async def exchange_control(
        self,
        cookie: int,
        transaction: int,
        command: ControlCommand,
        tlvs: tuple[Tlv, ...] = (),
    ) -> ControlFrame:
        request = ethernet(
            LOCAL_MACS[0],
            HOST_MACS[0],
            control_payload(cookie, transaction, command, tlvs),
        )
        await self._send_frame(0, request)
        try:
            raw = await with_timeout(self.tx_queues[0].get(), 50, "us")
        except SimTimeoutError:
            self._log_control_timeout(command, transaction)
            raise
        assert raw[:6] == HOST_MACS[0], raw.hex()
        response = ControlFrame.unpack(raw[14:])
        assert response.header.transaction_id == transaction
        assert response.header.status == Status.OK
        return response

    async def install_group(
        self,
        cookie: int,
        transaction: int,
        group_id: int,
        destinations: tuple[int, ...],
    ) -> None:
        replication = ReplicationGroup(
            1,
            tuple(
                NextHopEntry(path, port, NextHopType.RANK, HOST_MACS[port])
                for path, port in enumerate(destinations)
            ),
        )
        descriptor = GroupDescriptor(
            NodeRole.SINGLE,
            2,
            (
                ContributorBinding(0, 0, HOST_MACS[0]),
                ContributorBinding(1, 1, HOST_MACS[1]),
            ),
            UpstreamAction(False, 0, 0, bytes(6)),
            (replication,),
        )
        response = await self.exchange_control(
            cookie,
            transaction,
            ControlCommand.GROUP_STAGE,
            (handle_tlv(group_id), *descriptor.management_tlvs()),
        )
        assert response.header.command == ControlCommand.GROUP_STAGE_RESPONSE
        response = await self.exchange_control(
            cookie,
            transaction + 1,
            ControlCommand.GROUP_COMMIT,
            (handle_tlv(group_id),),
        )
        assert response.header.command == ControlCommand.GROUP_COMMIT_RESPONSE

    async def prepare_operation(
        self,
        cookie: int,
        transaction: int,
        group_id: int,
        operation_id: int,
        semantic: CollectiveSemantic,
        profile: AccumulatorProfile,
        element_count: int = 4,
    ) -> None:
        elements_per_chunk = CHUNK_PAYLOAD_BYTES // 4
        chunk_count = (element_count + elements_per_chunk - 1) // elements_per_chunk
        route = ResultRangeRoute(0, chunk_count - 1, 1)
        descriptor = OperationDescriptor(
            semantic,
            ReductionOperator.SUM,
            WireFormat.FP32,
            profile,
            PartialWireFormat.FP32,
            WireFormat.FP32,
            element_count=element_count,
            max_reduction_terms=2,
            requested_window_chunks=chunk_count,
            requested_replay_slots=max(2, chunk_count),
            timeout_ms=1000,
            retry_limit=2,
            result_delivery_role=True,
            result_range_routes=(route,),
        )
        response = await self.exchange_control(
            cookie,
            transaction,
            ControlCommand.OP_PREPARE,
            (
                handle_tlv(group_id),
                operation_tlv(operation_id),
                Tlv(TlvType.OPERATION_DESCRIPTOR, descriptor.pack()),
                Tlv(TlvType.RESULT_ROUTE_RANGE, route.pack()),
            ),
        )
        assert response.header.command == ControlCommand.OP_PREPARE_RESPONSE
        response = await self.exchange_control(
            cookie,
            transaction + 1,
            ControlCommand.OP_COMMIT,
            (operation_tlv(operation_id),),
        )
        assert response.header.command == ControlCommand.OP_COMMIT_RESPONSE

    def _log_data_timeout(self, port: int) -> None:
        core = self.dut.u_core
        store = core.u_result_store
        self.dut._log.error(
            "data timeout port=%d ingress=%s class=%s status=%s data=%s "
            "depacketized=%s queued=%s bank_arbiter=%s/%s bank_converted=%s/%s "
            "reduced=%s/%s output=%s/%s chunk=%s/%s routed=%s/%s jobs=%s result=%s",
            port,
            core.ingress_packet_valid.value,
            core.ingress_class.value,
            core.ingress_status.value,
            core.data_packet_valid.value,
            core.depacketized_valid.value,
            core.queued_valid.value,
            core.bank_arbiter_valid.value,
            core.bank_arbiter_ready.value,
            core.bank_converted_valid.value,
            core.bank_converted_ready.value,
            core.reduced_valid.value,
            core.reduced_ready.value,
            core.output_valid.value,
            core.output_ready.value,
            core.ready_chunk_valid.value,
            core.ready_chunk_ready.value,
            core.routed_job_valid.value,
            core.routed_job_ready.value,
            core.job_fifo_input_valid.value,
            core.result_axis_valid.value,
        )
        self.dut._log.error(
            "arithmetic banks(arbiter=%s/%s converted=%s/%s reduced=%s/%s "
            "queued_reduced=%s/%s) "
            "store(claimed=%s ready=%s next_chunk=%s)",
            core.bank_arbiter_valid.value,
            core.bank_arbiter_ready.value,
            core.bank_converted_valid.value,
            core.bank_converted_ready.value,
            core.bank_reduced_valid.value,
            core.bank_reduced_ready.value,
            core.queued_reduced_valid.value,
            core.queued_reduced_ready.value,
            store.slot_claimed.value,
            store.slot_ready.value,
            store.next_chunk_to_route.value,
        )

    async def run_collective(
        self,
        group_id: int,
        operation_id: int,
        destinations: tuple[int, ...],
        element_count: int = 4,
    ) -> list[int]:
        if element_count == 4:
            values = (
                (0x3F800000, 0x40000000, 0xBF800000, 0x00000001),
                (0x40400000, 0xC0000000, 0x3F800000, 0x00000001),
            )
        else:
            values = (
                (0x3F800000,) * element_count,
                (0x40400000,) * element_count,
            )
        identity = OperationIdentity(JOB_ID, group_id, 1, operation_id, 1)
        elements_per_chunk = CHUNK_PAYLOAD_BYTES // 4
        chunk_count = (element_count + elements_per_chunk - 1) // elements_per_chunk
        frames: list[list[bytes]] = [[], []]
        for contributor in range(2):
            for chunk_index in range(chunk_count):
                first = chunk_index * elements_per_chunk
                last = min(first + elements_per_chunk, element_count)
                payload = b"".join(
                    value.to_bytes(4, "little") for value in values[contributor][first:last]
                )
                flags = DataFlag.ACK_REQUIRED
                if chunk_index == chunk_count - 1:
                    flags |= DataFlag.LAST_CHUNK
                frames[contributor].append(
                    ethernet(
                        LOCAL_MACS[contributor],
                        HOST_MACS[contributor],
                        DataHeader(identity, contributor, chunk_index, flags).pack(payload),
                    )
                )

        expected_tiles = (element_count + 15) // 16
        output_cycles: list[int] = []

        async def observe_reduced_tiles() -> None:
            cycle = 0
            while len(output_cycles) < expected_tiles:
                await FallingEdge(self.dut.clk)
                await ReadOnly()
                if int(self.dut.u_core.output_valid.value) and int(
                    self.dut.u_core.output_ready.value
                ):
                    output_cycles.append(cycle)
                await RisingEdge(self.dut.clk)
                cycle += 1

        output_monitor = cocotb.start_soon(observe_reduced_tiles())

        async def send_contributor(port: int) -> None:
            for frame in frames[port]:
                await self._send_frame(port, frame)

        senders = [
            cocotb.start_soon(send_contributor(0)),
            cocotb.start_soon(send_contributor(1)),
        ]
        for sender in senders:
            await sender

        expected = [
            fp32_sum_bits([(0, values[0][lane]), (1, values[1][lane])], ordered=True)
            for lane in range(element_count)
        ]
        for port in destinations:
            for chunk_index in range(chunk_count):
                try:
                    raw = await with_timeout(self.tx_queues[port].get(), 100, "us")
                except SimTimeoutError:
                    self._log_data_timeout(port)
                    raise
                word = ControlWord.unpack(raw[14:16])
                assert word.opcode == Opcode.COL_RES
                header, payload = ResultHeader.unpack(raw[14:])
                assert header.identity == identity
                assert header.chunk_index == chunk_index
                first = chunk_index * elements_per_chunk
                last = min(first + elements_per_chunk, element_count)
                actual = [
                    int.from_bytes(payload[offset : offset + 4], "little")
                    for offset in range(0, (last - first) * 4, 4)
                ]
                assert actual == expected[first:last]
                assert bool(header.flags & DataFlag.LAST_CHUNK) == (chunk_index == chunk_count - 1)
                assert not (header.flags & DataFlag.ACCUMULATION_INEXACT)
        await with_timeout(output_monitor, 100, "us")
        return output_cycles

    def write_traces(self) -> tuple[Path, ...]:
        capture = ObservedCapture(Path(os.environ["PRISM_TRACE_ROOT"]), TRACE_NAME)
        for port in range(2):
            for frame in self.rx_observed[port]:
                capture.record(port=port, direction="rx", frame=frame)
            for frame in self.tx_observed[port]:
                capture.record(port=port, direction="tx", frame=frame)
        return capture.write()


@cocotb.test()
async def test_reduce_and_allreduce_cross_full_two_port_pipeline(dut: Any) -> None:
    world = PrismIntegrationWorld(dut)
    await world.start()

    caps = await world.exchange_control(0, 1, ControlCommand.CAPS_QUERY)
    assert caps.header.command == ControlCommand.CAPS_RESPONSE
    capability_tlvs = caps.tlvs()
    boot_id = next(tlv.as_u64() for tlv in capability_tlvs if tlv.type == TlvType.DEVICE_BOOT_ID)
    advertised = Capabilities.from_tlvs(
        boot_id,
        next(tlv for tlv in capability_tlvs if tlv.type == TlvType.CAPABILITIES),
    )
    assert advertised.input_formats == set(WireFormat) - {WireFormat.INVALID}
    assert advertised.partial_formats == {PartialWireFormat.FP32}
    assert advertised.output_formats == {WireFormat.FP16, WireFormat.BF16, WireFormat.FP32}
    session = await world.exchange_control(
        0,
        2,
        ControlCommand.SESSION_OPEN,
        (Tlv.u64(TlvType.JOB_ID, JOB_ID), Tlv.u64(TlvType.SECURITY_PROFILE, 0)),
    )
    cookie = next(tlv.as_u64() for tlv in session.tlvs() if tlv.type == TlvType.SESSION_COOKIE)

    await world.install_group(cookie, 10, 1, (0,))
    await world.prepare_operation(
        cookie,
        20,
        1,
        1,
        CollectiveSemantic.REDUCE,
        AccumulatorProfile.FP32_ARRIVAL,
    )
    await world.run_collective(1, 1, (0,))
    assert world.tx_queues[1].empty()
    released = await world.exchange_control(
        cookie,
        22,
        ControlCommand.OP_RELEASE,
        (operation_tlv(1),),
    )
    assert released.header.command == ControlCommand.OP_RELEASE_RESPONSE

    await world.install_group(cookie, 30, 2, (0, 1))
    await world.prepare_operation(
        cookie,
        40,
        2,
        2,
        CollectiveSemantic.ALLREDUCE,
        AccumulatorProfile.FP32_ORDERED,
        element_count=1472,
    )
    output_cycles = await world.run_collective(2, 2, (0, 1), element_count=1472)
    longest_run = 1
    current_run = 1
    for left, right in pairwise(output_cycles):
        current_run = current_run + 1 if right == left + 1 else 1
        longest_run = max(longest_run, current_run)
    assert longest_run >= 23
    dut._log.info(
        "two_rank_fp32_steady_tiles_per_cycle=1 lanes=16 payload_rate_gbps=128.0 longest_run=%d",
        longest_run,
    )
    world.write_traces()


@cocotb.test()
async def test_two_rank_fp32_sustains_100g_result_egress(dut: Any) -> None:
    world = PrismIntegrationWorld(dut)
    await world.start(stall_outputs=False)

    control_rx_start = len(world.rx_observed[0])
    control_tx_start = len(world.tx_observed[0])
    session = await world.exchange_control(
        0,
        1,
        ControlCommand.SESSION_OPEN,
        (Tlv.u64(TlvType.JOB_ID, JOB_ID), Tlv.u64(TlvType.SECURITY_PROFILE, 0)),
    )
    session_open_rtt_ns = (
        world.tx_observed[0][control_tx_start][0] - world.rx_observed[0][control_rx_start][0]
    )
    cookie = next(tlv.as_u64() for tlv in session.tlvs() if tlv.type == TlvType.SESSION_COOKIE)
    await world.install_group(cookie, 10, 1, (0,))
    await world.prepare_operation(
        cookie,
        20,
        1,
        1,
        CollectiveSemantic.REDUCE,
        AccumulatorProfile.FP32_ORDERED,
        element_count=1472,
    )

    data_rx_start = len(world.rx_observed[0])
    tx_start = len(world.tx_observed[0])
    output_cycles = await world.run_collective(1, 1, (0,), element_count=1472)
    result_frames = world.tx_observed[0][tx_start:]
    assert len(result_frames) == 4
    first_result_latency_ns = result_frames[0][0] - world.rx_observed[0][data_rx_start][0]

    longest_run = 1
    current_run = 1
    for left, right in pairwise(output_cycles):
        current_run = current_run + 1 if right == left + 1 else 1
        longest_run = max(longest_run, current_run)
    assert longest_run >= 23

    frame_start_intervals_ns = [right[0] - left[0] for left, right in pairwise(result_frames)]
    payload_rate_gbps = min(
        (CHUNK_PAYLOAD_BYTES * 8) / interval for interval in frame_start_intervals_ns
    )
    assert payload_rate_gbps >= 100.0
    dut._log.info(
        "two_rank_fp32_result_rate_gbps=%.2f internal_tile_rate_gbps=128.0 "
        "longest_full_tile_run=%d frame_intervals_ns=%s first_result_latency_ns=%d "
        "session_open_rtt_ns=%d",
        payload_rate_gbps,
        longest_run,
        frame_start_intervals_ns,
        first_result_latency_ns,
        session_open_rtt_ns,
    )
