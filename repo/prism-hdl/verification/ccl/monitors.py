"""AXI-stream monitors that reconstruct only DUT-observed frames."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from cocotb.triggers import RisingEdge

from .axi_stream import AxiStreamFrame


class AxiStreamSink:
    """Monitor a named DUT AXI-stream output and emit complete frames."""

    def __init__(self, dut: object, prefix: str, *, beat_bytes: int = 64) -> None:
        dynamic_dut = cast(Any, dut)  # Cocotb discovers DUT handles at runtime.
        self._clock = dynamic_dut.clk
        self._data = getattr(dynamic_dut, f"{prefix}_tdata")
        self._keep = getattr(dynamic_dut, f"{prefix}_tkeep")
        self._last = getattr(dynamic_dut, f"{prefix}_tlast")
        self._valid = getattr(dynamic_dut, f"{prefix}_tvalid")
        self._ready = getattr(dynamic_dut, f"{prefix}_tready")
        self._beat_bytes = beat_bytes

    async def run(self, callback: Callable[[AxiStreamFrame], Awaitable[None]]) -> None:
        payload = bytearray()
        self._ready.value = 1
        while True:
            await RisingEdge(self._clock)
            if not (int(self._valid.value) and int(self._ready.value)):
                continue
            data = int(self._data.value)
            keep = int(self._keep.value)
            for byte_index in range(self._beat_bytes):
                if keep & (1 << byte_index):
                    payload.append((data >> (8 * byte_index)) & 0xFF)
            if int(self._last.value):
                await callback(AxiStreamFrame(bytes(payload)))
                payload.clear()
