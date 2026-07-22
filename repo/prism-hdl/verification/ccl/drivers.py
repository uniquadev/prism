"""Backpressure-aware AXI-stream stimulus drivers."""

from __future__ import annotations

from typing import Any, cast

from cocotb.triggers import RisingEdge

from .axi_stream import AxiStreamFrame


class AxiStreamSource:
    """Drive complete frames on a named DUT AXI-stream input."""

    def __init__(self, dut: object, prefix: str, *, beat_bytes: int = 64) -> None:
        if beat_bytes < 1:
            raise ValueError("beat_bytes must be positive")
        dynamic_dut = cast(Any, dut)  # Cocotb discovers DUT handles at runtime.
        self._clock = dynamic_dut.clk
        self._data = getattr(dynamic_dut, f"{prefix}_tdata")
        self._keep = getattr(dynamic_dut, f"{prefix}_tkeep")
        self._last = getattr(dynamic_dut, f"{prefix}_tlast")
        self._valid = getattr(dynamic_dut, f"{prefix}_tvalid")
        self._ready = getattr(dynamic_dut, f"{prefix}_tready")
        self._beat_bytes = beat_bytes

    async def send(self, frame: AxiStreamFrame) -> None:
        self._valid.value = 0
        offset = 0
        while offset < len(frame.data):
            beat = frame.data[offset : offset + self._beat_bytes]
            self._data.value = int.from_bytes(beat.ljust(self._beat_bytes, b"\0"), "little")
            self._keep.value = (1 << len(beat)) - 1
            self._last.value = int(offset + len(beat) == len(frame.data))
            self._valid.value = 1
            while True:
                await RisingEdge(self._clock)
                if int(self._ready.value):
                    break
            offset += len(beat)
        self._valid.value = 0
        self._last.value = 0
