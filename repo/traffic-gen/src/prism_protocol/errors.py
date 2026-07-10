"""Structured PRISM host-library errors."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import Status


@dataclass(slots=True)
class PrismError(Exception):
    status: Status
    message: str
    switch_id: str | None = None
    transaction_id: int | None = None

    def __str__(self) -> str:
        location = f" switch={self.switch_id}" if self.switch_id else ""
        transaction = f" txn={self.transaction_id}" if self.transaction_id is not None else ""
        return f"{self.status.name}: {self.message}{location}{transaction}"


class ProtocolDecodeError(PrismError):
    def __init__(self, message: str) -> None:
        super().__init__(Status.INVALID_REQUEST, message)


class GenerationWrapRequiresNewJob(PrismError):
    def __init__(self, message: str = "generation wrapped; open a fresh Job/session") -> None:
        super().__init__(Status.GENERATION_MISMATCH, message)


class InvalidHandleError(PrismError):
    def __init__(self, message: str) -> None:
        super().__init__(Status.INVALID_STATE, message)
