"""Reproducible Ethernet MTU cost comparison, excluding unadvertised jumbo paths."""

from __future__ import annotations

from dataclasses import dataclass

from ..application.packing import group_cost
from ..domain.model import ConcreteFormat
from ..wire.data import CONTROL_WORD_BYTES, DATA_HEADER_BYTES


@dataclass(frozen=True, slots=True)
class FixedTransportCost:
    mtu: int
    format: ConcreteFormat
    elements: int
    packets: int
    numeric_bytes: int
    ethernet_payload_bytes: int
    line_bytes: int

    @property
    def numeric_efficiency(self) -> float:
        return self.numeric_bytes / self.line_bytes


def fixed_transport_cost(
    elements: int, fmt: ConcreteFormat, *, mtu: int, kulisch_bits: int = 279
) -> FixedTransportCost:
    if elements <= 0 or not 576 <= mtu <= 9216:
        raise ValueError("positive element count and supported MTU required")
    maximum = max(
        count
        for count in range(1, 65536)
        if CONTROL_WORD_BYTES + DATA_HEADER_BYTES + group_cost(fmt, count, kulisch_bits) <= mtu
    )
    remaining = elements
    packets = payload = numeric = line = 0
    width = (
        (1 + (kulisch_bits + 7) // 8)
        if fmt == ConcreteFormat.KULISCH
        else {
            ConcreteFormat.INT8: 1,
            ConcreteFormat.FP16: 2,
            ConcreteFormat.BF16: 2,
            ConcreteFormat.FP32: 4,
        }[fmt]
    )
    while remaining:
        count = min(remaining, maximum)
        prism_payload = (
            CONTROL_WORD_BYTES + DATA_HEADER_BYTES + group_cost(fmt, count, kulisch_bits)
        )
        packets += 1
        numeric += count * width
        payload += prism_payload
        # 14-byte Ethernet header + 4-byte FCS + 8-byte preamble/SFD +
        # 12-byte interframe gap. FCS is not part of the PRISM/AXI frame.
        line += max(64, 14 + prism_payload + 4) + 8 + 12
        remaining -= count
    return FixedTransportCost(mtu, fmt, elements, packets, numeric, payload, line)


def main() -> None:
    for fmt in (ConcreteFormat.FP32, ConcreteFormat.KULISCH):
        for mtu in (576, 1500, 9000):
            cost = fixed_transport_cost(1000, fmt, mtu=mtu)
            print(
                f"{fmt.name} mtu={mtu} packets={cost.packets} "
                f"line_bytes={cost.line_bytes} numeric_efficiency={cost.numeric_efficiency:.4f}"
            )


if __name__ == "__main__":
    main()
