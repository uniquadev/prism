"""The raw Ethernet transport filters and keeps the node's frames."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from prism_ccl.application.single import run_single
from prism_ccl.cli.single_run import NODE_MAC, reduction
from prism_ccl.domain.model import ConcreteFormat, OperationKey, ResultWirePolicy
from prism_ccl.transport.raw import RawEthernetTransport
from prism_ccl.wire.data import ETHERTYPE, PacketClass


def _frame(
    destination: bytes, source: bytes, packet_class: PacketClass, *, ethertype: int = ETHERTYPE
) -> bytes:
    return (
        destination
        + source
        + ethertype.to_bytes(2, "big")
        + bytes((0x20, int(packet_class)))
        + bytes(44)
    )


class FakeSocket:
    """Hands out queued frames, then times out like a socket."""

    def __init__(self, incoming: list[bytes]) -> None:
        self.incoming = list(incoming)
        self.sent: list[bytes] = []
        self.closed = False

    def send(self, data: bytes, /) -> int:
        self.sent.append(data)
        return len(data)

    def recv(self, size: int, /) -> bytes:
        if not self.incoming:
            raise TimeoutError
        return self.incoming.pop(0)[:size]

    def settimeout(self, value: float | None, /) -> None:
        pass

    def close(self) -> None:
        self.closed = True


MANAGER = bytes.fromhex("0250524953ff")
RANK = bytes.fromhex("02000000000b")


def test_other_protocols_and_own_frames_are_dropped_and_others_kept() -> None:
    own = _frame(NODE_MAC, MANAGER, PacketClass.CONTROL)
    result = _frame(RANK, NODE_MAC, PacketClass.RESULT)
    ack = _frame(MANAGER, NODE_MAC, PacketClass.CONTROL)
    socket = FakeSocket(
        [_frame(RANK, NODE_MAC, PacketClass.RESULT, ethertype=0x0800), own, result, ack]
    )
    with RawEthernetTransport({0: "eth0"}, timeout_s=0.1, opener=lambda _name: socket) as transport:
        asyncio.run(transport.send(0, own))
        assert asyncio.run(transport.receive(PacketClass.CONTROL, port=0)) == ack
        # The RESULT read on the way waits for its own receive.
        assert (
            asyncio.run(transport.receive(PacketClass.RESULT, port=0, destination_mac=RANK))
            == result
        )
        assert transport.received == [(0, result), (0, ack)]
    assert socket.sent == [own]
    assert socket.closed


def test_a_missing_frame_times_out() -> None:
    socket = FakeSocket([])
    with (
        RawEthernetTransport({0: "eth0"}, timeout_s=0.05, opener=lambda _name: socket) as transport,
        pytest.raises(TimeoutError, match="CONTROL"),
    ):
        asyncio.run(transport.receive(PacketClass.CONTROL, port=0))


def test_an_operation_without_an_answer_fails_with_a_timeout() -> None:
    scenario, binding, _expected = reduction(ConcreteFormat.FP32, ResultWirePolicy.FP32, 64)
    socket = FakeSocket([])
    with (
        RawEthernetTransport({0: "eth0"}, timeout_s=0.05, opener=lambda _name: socket) as transport,
        pytest.raises(TimeoutError),
    ):
        asyncio.run(run_single(scenario, binding, transport))
    # Only the stage left: nothing was staged, so nothing is aborted.
    assert len(socket.sent) == 1


def test_the_reduction_rejects_a_length_the_pattern_does_not_fill() -> None:
    with pytest.raises(ValueError, match="multiple"):
        reduction(ConcreteFormat.FP32, ResultWirePolicy.FP32, 12)


def test_the_reduction_carries_the_key_it_is_given() -> None:
    key = OperationKey(7, 1, 0, 3, 0)
    scenario, _binding, _expected = reduction(
        ConcreteFormat.FP32, ResultWirePolicy.FP32, 64, key=key
    )
    assert scenario.config.key == key


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.geteuid() != 0,
    reason="raw sockets need Linux and root",
)
def test_a_frame_crosses_a_real_interface() -> None:
    frame = _frame(RANK, NODE_MAC, PacketClass.RESULT)
    with (
        RawEthernetTransport({0: "lo"}, timeout_s=1.0) as host,
        RawEthernetTransport({0: "lo"}, timeout_s=1.0) as node,
    ):
        asyncio.run(node.send(0, frame))
        assert asyncio.run(host.receive(PacketClass.RESULT, port=0, destination_mac=RANK)) == frame
        # The sender does not take its own frame for one of the node's.
        with pytest.raises(TimeoutError):
            asyncio.run(node.receive(PacketClass.RESULT, port=0))
