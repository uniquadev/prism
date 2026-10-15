"""Frames to and from a PRISM node through raw Ethernet sockets (Linux).

A host that plays the manager and the ranks of an operation sends their frames
through one network interface per port of the node and receives the node's
answers on the same interfaces. The frames carry the MAC addresses of the
manager and the ranks, not that of the host, so each interface is put in
promiscuous mode while the transport is open. Opening raw sockets needs root
or the CAP_NET_RAW capability.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from ..wire.data import ETHERTYPE, PacketClass

# From <linux/if_packet.h> and <linux/if_ether.h>.
_ETH_P_ALL = 0x0003
_SOL_PACKET = 263
_PACKET_ADD_MEMBERSHIP = 1
_PACKET_MR_PROMISC = 1
# Largest frame a node sends: MTU 1500 plus the Ethernet header.
_RECEIVE_BYTES = 1514
# The node sends a result at line rate, faster than the host reads it: the
# socket holds a whole result of the largest vectors (several hundred frames).
_RECEIVE_BUFFER_BYTES = 16 << 20
_SO_RCVBUFFORCE = 33


class FrameSocket(Protocol):
    def send(self, data: bytes, /) -> int: ...

    def recv(self, size: int, /) -> bytes: ...

    def settimeout(self, value: float | None, /) -> None: ...

    def close(self) -> None: ...


def open_interface(name: str) -> FrameSocket:
    """A raw socket on the interface, in promiscuous mode."""
    raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(_ETH_P_ALL))
    raw.bind((name, 0))
    membership = struct.pack("iHH8s", socket.if_nametoindex(name), _PACKET_MR_PROMISC, 0, b"")
    raw.setsockopt(_SOL_PACKET, _PACKET_ADD_MEMBERSHIP, membership)
    try:
        # Beyond net.core.rmem_max, which needs CAP_NET_ADMIN.
        raw.setsockopt(socket.SOL_SOCKET, _SO_RCVBUFFORCE, _RECEIVE_BUFFER_BYTES)
    except PermissionError:
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _RECEIVE_BUFFER_BYTES)
    return raw


class RawEthernetTransport:
    """Sends a frame on the interface of a port and waits for the node's frames.

    ``interfaces`` maps each port of the node to the host interface cabled
    to it. A receive returns the first PRISM frame of the awaited class on
    that port (and to that destination, if given) and keeps every other PRISM
    frame for a later receive; frames of other protocols are dropped. It
    raises TimeoutError after ``timeout_s`` seconds without such a frame.
    """

    def __init__(
        self,
        interfaces: Mapping[int, str],
        *,
        timeout_s: float = 5.0,
        opener: Callable[[str], FrameSocket] = open_interface,
    ) -> None:
        self.timeout_s = timeout_s
        self.sockets = {port: opener(name) for port, name in interfaces.items()}
        self.pending: list[tuple[int, bytes]] = []
        self.sent: list[tuple[int, bytes]] = []
        self.own_sources: set[bytes] = set()
        self.received: list[tuple[int, bytes]] = []

    def close(self) -> None:
        for raw in self.sockets.values():
            raw.close()

    def __enter__(self) -> RawEthernetTransport:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    async def send(self, port: int, frame: bytes) -> None:
        self.sockets[port].send(frame)
        self.sent.append((port, frame))
        self.own_sources.add(frame[6:12])

    def _take(
        self, packet_class: PacketClass, port: int, destination_mac: bytes | None
    ) -> bytes | None:
        for index, (frame_port, frame) in enumerate(self.pending):
            if (
                frame_port == port
                and frame[15] == int(packet_class)
                and (destination_mac is None or frame[:6] == destination_mac)
            ):
                return self.pending.pop(index)[1]
        return None

    def _receive_blocking(
        self, packet_class: PacketClass, port: int, destination_mac: bytes | None
    ) -> bytes:
        found = self._take(packet_class, port, destination_mac)
        if found is not None:
            return found
        raw = self.sockets[port]
        deadline = time.monotonic() + self.timeout_s
        while (left := deadline - time.monotonic()) > 0:
            raw.settimeout(left)
            try:
                frame = raw.recv(_RECEIVE_BYTES)
            except TimeoutError:
                break
            if len(frame) < 16 or int.from_bytes(frame[12:14], "big") != ETHERTYPE:
                continue
            # The socket also sees what this host sent; only the node's
            # frames count, and those never carry a source the host used.
            if frame[6:12] in self.own_sources:
                continue
            self.received.append((port, frame))
            self.pending.append((port, frame))
            found = self._take(packet_class, port, destination_mac)
            if found is not None:
                return found
        raise TimeoutError(
            f"no {packet_class.name} frame from the node on port {port} within {self.timeout_s} s"
        )

    async def receive(
        self, packet_class: PacketClass, *, port: int, destination_mac: bytes | None = None
    ) -> bytes:
        return await asyncio.to_thread(self._receive_blocking, packet_class, port, destination_mac)
