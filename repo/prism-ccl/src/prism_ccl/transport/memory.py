"""Deterministic in-memory transport for CCL tests and examples."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..protocol.constants import CollectiveSemantic
from .contracts import (
    CollectiveEvaluator,
    CollectiveTransport,
    Endpoint,
    TransportClosedError,
    TransportError,
    TransportRequest,
    TransportResponse,
)


@dataclass(slots=True)
class _PendingCollective:
    requests: dict[int, TransportRequest] = field(default_factory=dict)
    futures: dict[int, asyncio.Future[TransportResponse]] = field(default_factory=dict)


class InMemoryCollectiveNetwork:
    """Shared rendezvous that delegates collective semantics to an evaluator."""

    def __init__(self, evaluator: CollectiveEvaluator) -> None:
        self._evaluator = evaluator
        self._lock = asyncio.Lock()
        self._pending: dict[tuple[str, int], _PendingCollective] = {}

    async def exchange(self, request: TransportRequest) -> TransportResponse:
        loop = asyncio.get_running_loop()
        async with self._lock:
            key = (request.communicator_id, request.sequence)
            pending = self._pending.setdefault(key, _PendingCollective())
            if request.rank in pending.requests:
                raise TransportError(f"rank {request.rank} submitted sequence twice")
            if request.rank not in request.ranks:
                raise TransportError("request rank is not a communicator member")
            future: asyncio.Future[TransportResponse] = loop.create_future()
            pending.requests[request.rank] = request
            pending.futures[request.rank] = future
            if set(pending.requests) == set(request.ranks):
                self._complete(key, pending)
        return await asyncio.shield(future)

    async def cancel(self, request: TransportRequest) -> None:
        async with self._lock:
            key = (request.communicator_id, request.sequence)
            pending = self._pending.get(key)
            if pending is None:
                return
            future = pending.futures.pop(request.rank, None)
            pending.requests.pop(request.rank, None)
            if future is not None and not future.done():
                future.cancel()
            if not pending.requests:
                self._pending.pop(key, None)

    def _complete(self, key: tuple[str, int], pending: _PendingCollective) -> None:
        requests = tuple(pending.requests.values())
        first = requests[0]
        invariant = (
            first.ranks,
            first.semantic,
            first.root,
            first.operator,
            first.datatype,
            first.output_datatype,
            first.accumulator,
            first.maximum_terms,
            first.compiled_widths,
            len(first.values),
        )
        if any(
            (
                item.ranks,
                item.semantic,
                item.root,
                item.operator,
                item.datatype,
                item.output_datatype,
                item.accumulator,
                item.maximum_terms,
                item.compiled_widths,
                len(item.values),
            )
            != invariant
            for item in requests[1:]
        ):
            self._fail(key, pending, TransportError("collective metadata disagrees across ranks"))
            return
        try:
            values, warnings = self._evaluator(requests)
        except Exception as error:  # propagate reference-model validation faithfully
            self._fail(key, pending, error)
            return
        for rank, future in pending.futures.items():
            visible = first.semantic == CollectiveSemantic.ALLREDUCE or rank == first.root
            if not future.done():
                future.set_result(TransportResponse(values if visible else None, warnings))
        self._pending.pop(key, None)

    def _fail(
        self,
        key: tuple[str, int],
        pending: _PendingCollective,
        error: BaseException,
    ) -> None:
        for future in pending.futures.values():
            if not future.done():
                future.set_exception(error)
        self._pending.pop(key, None)


class InMemoryTransport(CollectiveTransport):
    """One rank endpoint attached to an in-memory collective network."""

    def __init__(self, network: InMemoryCollectiveNetwork, *, endpoint: Endpoint) -> None:
        self._network = network
        self._endpoint = endpoint
        self._started = False

    @property
    def endpoint(self) -> Endpoint:
        return self._endpoint

    async def start(self) -> None:
        self._started = True

    async def exchange(self, request: TransportRequest) -> TransportResponse:
        if not self._started:
            raise TransportClosedError("transport is not started")
        if self.endpoint.rank is not None and self.endpoint.rank != request.rank:
            raise TransportError("transport endpoint rank does not match request rank")
        return await self._network.exchange(request)

    async def cancel(self, request: TransportRequest) -> None:
        await self._network.cancel(request)

    async def close(self) -> None:
        self._started = False
