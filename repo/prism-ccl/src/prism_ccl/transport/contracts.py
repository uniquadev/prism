"""Typed asynchronous transport contracts for PRISM collectives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..protocol.constants import (
    AccumulatorProfile,
    CollectiveSemantic,
    ReductionOperator,
    WireFormat,
)


class TransportError(RuntimeError):
    """Base class for transport failures."""


class TransportClosedError(TransportError):
    """Raised when an operation uses a closed transport."""


class CollectiveTimeoutError(TransportError):
    """Raised when a collective exceeds its configured deadline."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Logical endpoint mapped to a PRISM port and optional rank."""

    port: int
    rank: int | None = None

    def __post_init__(self) -> None:
        if self.port < 0:
            raise ValueError("endpoint port must be non-negative")
        if self.rank is not None and self.rank < 0:
            raise ValueError("endpoint rank must be non-negative")


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """One rank contribution submitted to a transport backend."""

    communicator_id: str
    sequence: int
    rank: int
    ranks: tuple[int, ...]
    semantic: CollectiveSemantic
    root: int | None
    operator: ReductionOperator
    datatype: WireFormat
    output_datatype: WireFormat
    accumulator: AccumulatorProfile
    maximum_terms: int
    compiled_widths: tuple[int, ...]
    values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """Transport-neutral collective completion returned to one rank."""

    values: tuple[int, ...] | None
    warnings: tuple[str, ...] = ()


type CollectiveEvaluation = tuple[tuple[int, ...], tuple[str, ...]]
type CollectiveEvaluator = Callable[[tuple[TransportRequest, ...]], CollectiveEvaluation]


@runtime_checkable
class CollectiveTransport(Protocol):
    """Backend contract used by :class:`prism_ccl.collectives.Communicator`."""

    @property
    def endpoint(self) -> Endpoint:
        """Return the logical endpoint owned by this transport instance."""

    async def start(self) -> None:
        """Allocate transport resources."""

    async def exchange(self, request: TransportRequest) -> TransportResponse:
        """Submit one contribution and await this rank's completion."""

    async def cancel(self, request: TransportRequest) -> None:
        """Cancel one pending contribution when supported."""

    async def close(self) -> None:
        """Release transport resources and reject new exchanges."""
