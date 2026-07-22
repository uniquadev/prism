"""Frame-level Cocotb transport boundary used only by HDL verification."""

from __future__ import annotations

from typing import Protocol

from cocotb.queue import Queue
from prism_ccl.transport import (
    CollectiveTransport,
    Endpoint,
    TransportClosedError,
    TransportRequest,
    TransportResponse,
)

from .axi_stream import AxiStreamFrame


class FrameSource(Protocol):
    """Minimal source contract required by the frame transport."""

    async def send(self, frame: AxiStreamFrame) -> None:
        """Transmit one complete Ethernet frame."""


class DutFrameTransport:
    """Pair an AXI-stream source with a monitor-fed receive queue."""

    def __init__(self, source: FrameSource) -> None:
        self._source = source
        self._received: Queue[AxiStreamFrame] = Queue()

    async def send(self, frame: bytes) -> None:
        await self._source.send(AxiStreamFrame(frame))

    async def receive(self) -> bytes:
        return (await self._received.get()).data

    async def observe(self, frame: AxiStreamFrame) -> None:
        await self._received.put(frame)


class DutCollectiveSession(Protocol):
    """Scenario-specific encoder/decoder used by the generic Cocotb backend."""

    async def exchange(
        self,
        endpoint: Endpoint,
        request: TransportRequest,
        frames: DutFrameTransport,
    ) -> TransportResponse:
        """Drive the DUT lifecycle and return the rank-visible response."""

    async def cancel(self, endpoint: Endpoint, request: TransportRequest) -> None:
        """Cancel a pending simulator operation when the scenario supports it."""


class CocotbCollectiveTransport(CollectiveTransport):
    """Implement the public CCL transport contract over a Cocotb AXI port.

    Packet encoding and lifecycle details remain in a typed session object so this
    adapter owns only simulator lifecycle, rank-to-port mapping, and AXI frames.
    """

    def __init__(
        self,
        endpoint: Endpoint,
        frames: DutFrameTransport,
        session: DutCollectiveSession,
    ) -> None:
        if endpoint.rank is None:
            raise ValueError("a Cocotb collective endpoint must identify a rank")
        self._endpoint = endpoint
        self._frames = frames
        self._session = session
        self._active = False

    @property
    def endpoint(self) -> Endpoint:
        return self._endpoint

    async def start(self) -> None:
        self._active = True

    async def exchange(self, request: TransportRequest) -> TransportResponse:
        if not self._active:
            raise TransportClosedError("Cocotb transport is not started")
        if request.rank != self._endpoint.rank:
            raise ValueError("request rank does not match the Cocotb endpoint")
        return await self._session.exchange(self._endpoint, request, self._frames)

    async def cancel(self, request: TransportRequest) -> None:
        await self._session.cancel(self._endpoint, request)

    async def close(self) -> None:
        self._active = False
