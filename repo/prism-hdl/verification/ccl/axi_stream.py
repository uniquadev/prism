"""AXI-stream frame types shared by Cocotb drivers and monitors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AxiStreamFrame:
    """One complete Ethernet frame observed at an AXI-stream boundary."""

    data: bytes
    user: int = 0

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("AXI-stream frame must not be empty")
        if self.user < 0:
            raise ValueError("AXI-stream user metadata must be non-negative")
