"""Bounded, seeded packet reordering for frame-level experiments."""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeVar

from ..wire.data import PacketClass

PacketT = TypeVar("PacketT")


@dataclass(frozen=True, slots=True)
class ReorderRule:
    source: str
    destination: str
    packet_class: PacketClass
    probability: float
    window_packets: int = 2

    def __post_init__(self) -> None:
        if not self.source or not self.destination or self.source == self.destination:
            raise ValueError("reordering needs distinct named endpoints")
        if self.packet_class not in (PacketClass.DATA, PacketClass.RESULT):
            raise ValueError("only DATA and RESULT streams may be reordered")
        if not math.isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError("reorder probability must be between zero and one")
        if not 2 <= self.window_packets <= 32:
            raise ValueError("reorder window must contain 2..32 packets")


@dataclass(frozen=True, slots=True)
class ReorderPlan:
    """Rules name directed end-to-end flows, not physical switch ports."""

    seed: int = 0
    rules: tuple[ReorderRule, ...] = ()
    all_data_probability: float = 0.0
    all_data_window_packets: int = 2

    def __post_init__(self) -> None:
        if not math.isfinite(self.all_data_probability) or not 0 <= self.all_data_probability <= 1:
            raise ValueError("reorder probability must be between zero and one")
        if not 2 <= self.all_data_window_packets <= 32:
            raise ValueError("reorder window must contain 2..32 packets")
        keys = [(rule.source, rule.destination, rule.packet_class) for rule in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("a directed flow has more than one reorder rule")

    @classmethod
    def data(
        cls,
        probability: float,
        *,
        window_packets: int = 2,
        seed: int = 0,
        edges: Iterable[tuple[str, str]] | None = None,
    ) -> ReorderPlan:
        """Enable DATA reordering everywhere, or only on named directed edges."""
        if edges is None:
            return cls(
                seed, all_data_probability=probability, all_data_window_packets=window_packets
            )
        selected_edges = tuple(edges)
        if not selected_edges:
            raise ValueError("named reorder edges cannot be empty")
        return cls(
            seed,
            tuple(
                ReorderRule(source, destination, PacketClass.DATA, probability, window_packets)
                for source, destination in selected_edges
            ),
        )

    def rule_for(
        self, source: str, destination: str, packet_class: PacketClass
    ) -> ReorderRule | None:
        selected = next(
            (
                rule
                for rule in self.rules
                if (rule.source, rule.destination, rule.packet_class)
                == (source, destination, packet_class)
            ),
            None,
        )
        if selected is not None:
            return selected
        if packet_class == PacketClass.DATA and self.all_data_probability:
            return ReorderRule(
                source,
                destination,
                packet_class,
                self.all_data_probability,
                self.all_data_window_packets,
            )
        return None

    def require_window_capacity(self, packets: int) -> None:
        """Reject a perturbation beyond the receiver's packet window."""
        windows = [rule.window_packets for rule in self.rules if rule.probability > 0]
        if self.all_data_probability > 0:
            windows.append(self.all_data_window_packets)
        if any(window > packets for window in windows):
            raise ValueError(f"reorder window exceeds receive capacity {packets}")

    def arrange(
        self,
        packets: list[PacketT],
        *,
        source: str,
        destination: str,
        packet_class: PacketClass,
        stream_id: int,
        batch: int = 0,
    ) -> list[PacketT]:
        """Swap forward with probability p inside disjoint bounded windows."""
        rule = self.rule_for(source, destination, packet_class)
        if rule is None or rule.probability == 0 or len(packets) < 2:
            return list(packets)
        identity = (
            f"{self.seed}:{source}:{destination}:{int(packet_class)}:{stream_id}:{batch}"
        ).encode()
        rng = random.Random(int.from_bytes(hashlib.sha256(identity).digest()[:8], "big"))
        arranged: list[PacketT] = []
        for offset in range(0, len(packets), rule.window_packets):
            window = list(packets[offset : offset + rule.window_packets])
            for index in range(len(window) - 1):
                if rng.random() < rule.probability:
                    other = rng.randrange(index + 1, len(window))
                    window[index], window[other] = window[other], window[index]
            arranged.extend(window)
        return arranged
