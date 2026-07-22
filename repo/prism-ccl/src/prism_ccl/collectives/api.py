"""Public asynchronous communicator API for REDUCE and ALLREDUCE."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Generator
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum

from ..protocol.constants import (
    AccumulatorProfile,
    CollectiveSemantic,
    ReductionOperator,
    WireFormat,
)
from ..transport import (
    CollectiveTimeoutError,
    CollectiveTransport,
    TransportRequest,
    TransportResponse,
)

Datatype = WireFormat
Operator = ReductionOperator


class CommunicatorError(RuntimeError):
    """Base error for communicator misuse or lifecycle failures."""


class CommunicatorClosedError(CommunicatorError):
    """Raised when a collective is submitted outside the active lifecycle."""


class RequestStatus(Enum):
    """Observable lifecycle of a nonblocking collective request."""

    PENDING = "pending"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CollectiveConfig:
    """Arithmetic and deadline configuration shared by collective calls."""

    operator: Operator = Operator.SUM
    datatype: Datatype = Datatype.FP32
    output_datatype: Datatype = Datatype.FP32
    accumulator: AccumulatorProfile = AccumulatorProfile.FP32_ARRIVAL
    maximum_terms: int = 2
    compiled_widths: tuple[int, ...] = (64, 288, 320)
    timeout_seconds: float | None = 5.0

    def __post_init__(self) -> None:
        if self.operator != Operator.SUM:
            raise ValueError("only SUM is defined by the current PRISM profile")
        if self.datatype == Datatype.INVALID or self.output_datatype == Datatype.INVALID:
            raise ValueError("collective datatypes must be valid wire formats")
        if self.accumulator == AccumulatorProfile.INVALID:
            raise ValueError("accumulator profile must be valid")
        if self.maximum_terms < 1:
            raise ValueError("maximum_terms must be positive")
        if (
            not self.compiled_widths
            or any(width < 1 for width in self.compiled_widths)
            or len(set(self.compiled_widths)) != len(self.compiled_widths)
        ):
            raise ValueError("compiled_widths must be non-empty, positive, and unique")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive or None")


@dataclass(frozen=True, slots=True)
class CollectiveResult:
    """One rank's visible result and sticky runtime warnings."""

    values: tuple[int, ...] | None
    warnings: tuple[str, ...] = ()

    @property
    def accumulation_inexact(self) -> bool:
        return "ACCUMULATION_INEXACT" in self.warnings


class CollectiveRequest:
    """Awaitable handle for a nonblocking collective."""

    def __init__(
        self,
        task: asyncio.Task[CollectiveResult],
        request: TransportRequest,
        transport: CollectiveTransport,
    ) -> None:
        self._task = task
        self._request = request
        self._transport = transport

    @property
    def status(self) -> RequestStatus:
        if self._task.cancelled():
            return RequestStatus.CANCELLED
        if not self._task.done():
            return RequestStatus.PENDING
        return RequestStatus.FAILED if self._task.exception() else RequestStatus.COMPLETE

    async def wait(self) -> CollectiveResult:
        return await self._task

    async def cancel(self) -> None:
        if self._task.done():
            return
        await self._transport.cancel(self._request)
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    def __await__(self) -> Generator[object, None, CollectiveResult]:
        return self.wait().__await__()


class Communicator:
    """Rank-local, transport-independent collective communicator."""

    def __init__(
        self,
        *,
        communicator_id: str,
        ranks: tuple[int, ...],
        rank: int,
        transport: CollectiveTransport,
    ) -> None:
        if not communicator_id:
            raise ValueError("communicator_id must not be empty")
        if not ranks or len(set(ranks)) != len(ranks) or any(item < 0 for item in ranks):
            raise ValueError("ranks must be non-empty, unique, and non-negative")
        if rank not in ranks:
            raise ValueError("local rank must belong to the communicator")
        self.communicator_id = communicator_id
        self.ranks = ranks
        self.rank = rank
        self._transport = transport
        self._sequence = 0
        self._active = False

    async def start(self) -> None:
        if not self._active:
            await self._transport.start()
            self._active = True

    async def close(self) -> None:
        if self._active:
            await self._transport.close()
            self._active = False

    async def __aenter__(self) -> Communicator:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def ireduce(
        self,
        values: tuple[int, ...],
        *,
        root: int,
        config: CollectiveConfig | None = None,
    ) -> CollectiveRequest:
        if root not in self.ranks:
            raise ValueError("REDUCE root must belong to the communicator")
        return self._submit(
            values,
            semantic=CollectiveSemantic.REDUCE,
            root=root,
            config=config or CollectiveConfig(),
        )

    async def reduce(
        self,
        values: tuple[int, ...],
        *,
        root: int,
        config: CollectiveConfig | None = None,
    ) -> CollectiveResult:
        return await self.ireduce(values, root=root, config=config)

    def iallreduce(
        self,
        values: tuple[int, ...],
        *,
        config: CollectiveConfig | None = None,
    ) -> CollectiveRequest:
        return self._submit(
            values,
            semantic=CollectiveSemantic.ALLREDUCE,
            root=None,
            config=config or CollectiveConfig(),
        )

    async def allreduce(
        self,
        values: tuple[int, ...],
        *,
        config: CollectiveConfig | None = None,
    ) -> CollectiveResult:
        return await self.iallreduce(values, config=config)

    def _submit(
        self,
        values: tuple[int, ...],
        *,
        semantic: CollectiveSemantic,
        root: int | None,
        config: CollectiveConfig,
    ) -> CollectiveRequest:
        if not self._active:
            raise CommunicatorClosedError("communicator is not started")
        if not values:
            raise ValueError("collective values must not be empty")
        request = TransportRequest(
            communicator_id=self.communicator_id,
            sequence=self._sequence,
            rank=self.rank,
            ranks=self.ranks,
            semantic=semantic,
            root=root,
            operator=config.operator,
            datatype=config.datatype,
            output_datatype=config.output_datatype,
            accumulator=config.accumulator,
            maximum_terms=config.maximum_terms,
            compiled_widths=config.compiled_widths,
            values=values,
        )
        self._sequence += 1
        operation = self._exchange(request, config.timeout_seconds)
        task = asyncio.create_task(operation)
        return CollectiveRequest(task, request, self._transport)

    async def _exchange(
        self, request: TransportRequest, timeout_seconds: float | None
    ) -> CollectiveResult:
        operation: Coroutine[object, object, TransportResponse] = self._transport.exchange(request)
        try:
            if timeout_seconds is None:
                response = await operation
            else:
                response = await asyncio.wait_for(operation, timeout_seconds)
        except TimeoutError as error:
            await self._transport.cancel(request)
            raise CollectiveTimeoutError(
                f"collective sequence {request.sequence} timed out"
            ) from error
        return CollectiveResult(response.values, response.warnings)
