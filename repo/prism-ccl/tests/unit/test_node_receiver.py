from __future__ import annotations

from dataclasses import replace

import pytest

from prism_ccl.application.node import NodeReceiver
from prism_ccl.application.window import Admission
from prism_ccl.domain.capabilities import software_capabilities
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationKey,
    PartialWirePolicy,
)
from prism_ccl.domain.topology import PrismCapacity
from prism_ccl.wire.control import (
    ContextRecord,
    ControlCommand,
    ControlPacket,
    ControlStatus,
    EndpointBindingRecord,
    NodeRole,
    PeerKind,
    encode_control_frame,
)
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

AM = bytes.fromhex("020000000000")
NODE = bytes.fromhex("020000000003")
R0 = bytes.fromhex("020000000001")
R1 = bytes.fromhex("020000000002")
KEY = OperationKey(1, 1, 0, 1, 1)
FP32 = frozenset({ConcreteFormat.FP32})


def _record() -> ContextRecord:
    return ContextRecord(
        NodeRole.SINGLE,
        None,
        (10, 11),
        (10, 11),
        2,
        8,
        8192,
        1,
        280,
        1500,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.AUTO,
        ConcreteFormat.FP32,
        FP32,
        CollectiveKind.ALLREDUCE,
        AM,
        1,
        2,
        FP32,
        (
            EndpointBindingRecord(10, 1, 2, PeerKind.RANK, R0, 0, 1, FP32, True),
            EndpointBindingRecord(11, 1, 3, PeerKind.RANK, R1, 1, 1, FP32, True),
        ),
    )


def _node() -> NodeReceiver:
    return NodeReceiver(
        mac=NODE,
        ports={1: 1500, 2: 1500, 3: 1500},
        capacity=PrismCapacity(8, 16, 8, 8192, True, True),
        capabilities=software_capabilities(),
        manager_mac=AM,
        manager_port=1,
    )


def _control(
    node: NodeReceiver,
    command: ControlCommand,
    *,
    record: ContextRecord | None = None,
    key: OperationKey = KEY,
    transaction: int | None = None,
) -> tuple[bytes, ControlStatus]:
    packet = ControlPacket(
        key,
        int(command) if transaction is None else transaction,
        0xFFFE,
        0xFFFE,
        command,
        body=record.pack() if record is not None else b"",
    )
    frame = encode_control_frame(packet, destination_mac=NODE, source_mac=AM, mtu=1500)
    reply = node.handle_control(frame, ingress_port=1, mtu=1500)
    return frame, ControlStatus(reply.status)


def _data(
    node: NodeReceiver,
    *,
    endpoint: int = 10,
    source: bytes = R0,
    source_endpoint: int = 1,
    ingress: int = 2,
) -> Admission:
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        source_endpoint,
        endpoint,
        endpoint,
        0,
        0,
        (NumberGroup(ConcreteFormat.FP32, (0x3F800000,)),),
        True,
    )
    frame = encode_data_frame(
        packet, destination_mac=NODE, source_mac=source, mtu=1500, kulisch_bits=280
    )
    return node.accept_data(frame, ingress_port=ingress)[0]


def test_context_binding_golden_bytes_are_independent_of_decoder() -> None:
    expected = bytes.fromhex(
        "01020200ffff0000000200080000200000000001011805dc80ff040802000000"
        "02000000000000010000000208000000"
        "000a000b000a000b"
        "000a00010002010102000000000100000000000108000000"
        "000b00010003010102000000000200010000000108000000"
    )
    assert len(expected) == 104
    assert _record().pack() == expected
    assert ContextRecord.unpack(expected) == _record()


def test_receiver_rejects_exact_fp32_with_eight_kulisch_bits_before_stage_ack() -> None:
    node = _node()
    _frame, status = _control(node, ControlCommand.STAGE, record=replace(_record(), kulisch_bits=8))
    assert status == ControlStatus.UNSUPPORTED
    assert not node.contexts and node.reserved_bytes == 0


def test_receiver_uses_installed_binding_and_commit_gate() -> None:
    node = _node()
    frame, status = _control(node, ControlCommand.STAGE, record=_record())
    assert status == ControlStatus.OK
    assert node.reserved_bytes == 8192
    assert node.contexts[KEY].record.bindings[0].peer_mac == R0
    assert node.handle_control(frame, ingress_port=1, mtu=1500).status == ControlStatus.OK
    with pytest.raises(ValueError, match="not committed"):
        _data(node)
    assert _control(node, ControlCommand.RELEASE)[1] == ControlStatus.BAD_STATE
    assert _control(node, ControlCommand.COMMIT)[1] == ControlStatus.OK
    assert _control(node, ControlCommand.COMMIT, transaction=22)[1] == ControlStatus.BAD_STATE
    for changes in ({"source": R1}, {"source_endpoint": 2}, {"ingress": 3}, {"endpoint": 11}):
        with pytest.raises(ValueError, match="binding"):
            _data(node, **changes)
    assert _data(node) == Admission.ACCEPTED
    assert _data(node) == Admission.DUPLICATE
    window = node.contexts[KEY].windows[(PacketClass.DATA, 10)]  # type: ignore[index]
    chunk = window.peek_contiguous()
    assert chunk is not None
    window.release_contiguous(chunk)
    assert _control(node, ControlCommand.RELEASE, transaction=23)[1] == ControlStatus.BAD_STATE
    assert _data(node, endpoint=11, source=R1, ingress=3) == Admission.ACCEPTED
    other = node.contexts[KEY].windows[(PacketClass.DATA, 11)]  # type: ignore[index]
    chunk = other.peek_contiguous()
    assert chunk is not None
    other.release_contiguous(chunk)
    assert _control(node, ControlCommand.RELEASE, transaction=24)[1] == ControlStatus.OK
    assert (
        _control(node, ControlCommand.STAGE, record=_record(), transaction=25)[1]
        == ControlStatus.STALE_GENERATION
    )
    assert not node.contexts and node.reserved_bytes == 0
    assert _control(node, ControlCommand.RELEASE, transaction=24)[1] == ControlStatus.OK


def test_invalid_binding_capability_transaction_and_generation() -> None:
    node = _node()
    bad = replace(
        _record(), bindings=(replace(_record().bindings[0], local_port=99), _record().bindings[1])
    )
    assert _control(node, ControlCommand.STAGE, record=bad)[1] == ControlStatus.BINDING_INVALID
    unsupported = replace(
        _record(),
        accumulator=AccumulatorPolicy.FP32_ARRIVAL,
        partial_wire=PartialWirePolicy.KULISCH,
        output_format=ConcreteFormat.BF16,
    )
    assert (
        _control(node, ControlCommand.STAGE, record=unsupported, transaction=31)[1]
        == ControlStatus.UNSUPPORTED
    )
    stage_frame, status = _control(node, ControlCommand.STAGE, record=_record(), transaction=32)
    assert status == ControlStatus.OK
    changed = replace(_record(), element_count=2)
    assert (
        _control(node, ControlCommand.STAGE, record=changed, transaction=32)[1]
        == ControlStatus.TRANSACTION_CONFLICT
    )
    assert node.handle_control(stage_frame, ingress_port=1, mtu=1500).status == ControlStatus.OK
    newer = replace(KEY, operation_generation=2)
    assert (
        _control(node, ControlCommand.STAGE, record=_record(), key=newer, transaction=33)[1]
        == ControlStatus.BAD_STATE
    )
    concurrent = replace(KEY, operation_id=2)
    assert (
        _control(node, ControlCommand.STAGE, record=_record(), key=concurrent, transaction=36)[1]
        == ControlStatus.NO_RESOURCE
    )
    assert _control(node, ControlCommand.ABORT)[1] == ControlStatus.OK
    assert node.reserved_intervals == 0
    assert (
        _control(node, ControlCommand.STAGE, record=_record(), transaction=37)[1]
        == ControlStatus.STALE_GENERATION
    )
    assert (
        _control(node, ControlCommand.STAGE, record=_record(), key=newer, transaction=34)[1]
        == ControlStatus.OK
    )
    assert _control(node, ControlCommand.ABORT, key=newer)[1] == ControlStatus.OK
    stale = replace(KEY, operation_generation=0)
    assert (
        _control(node, ControlCommand.STAGE, record=_record(), key=stale, transaction=35)[1]
        == ControlStatus.STALE_GENERATION
    )


def test_retired_generation_cannot_reopen_after_ack_journal_eviction() -> None:
    node = _node()
    frame, status = _control(node, ControlCommand.STAGE, record=_record())
    assert status == ControlStatus.OK
    assert _control(node, ControlCommand.ABORT)[1] == ControlStatus.OK
    # A retained duplicate ACK must not reinstall the retired context.
    assert node.handle_control(frame, ingress_port=1, mtu=1500).status == ControlStatus.OK
    assert not node.contexts
    for transaction in range(100, 165):
        assert _control(node, ControlCommand.ABORT, transaction=transaction)[1] == ControlStatus.OK
    assert (
        node.handle_control(frame, ingress_port=1, mtu=1500).status
        == ControlStatus.STALE_GENERATION
    )
    assert not node.contexts and node.reserved_bytes == 0
    with pytest.raises(ValueError, match="not committed"):
        _data(node)
