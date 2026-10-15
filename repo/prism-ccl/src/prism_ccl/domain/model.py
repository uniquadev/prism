"""Value objects and operation invariants, independent of wire and runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ConcreteFormat(IntEnum):
    INT8 = 0x01
    FP16 = 0x02
    BF16 = 0x03
    FP32 = 0x04
    KULISCH = 0x80


class AccumulatorPolicy(IntEnum):
    FP32_ARRIVAL = 0x01
    KULISCH_FIXED = 0x80


class PartialWirePolicy(IntEnum):
    INT8 = 0x01
    FP16 = 0x02
    BF16 = 0x03
    FP32 = 0x04
    KULISCH = 0x80
    AUTO = 0xFF


class ResultWirePolicy(IntEnum):
    INT8 = 0x01
    FP16 = 0x02
    BF16 = 0x03
    FP32 = 0x04
    KULISCH = 0x80
    AUTO = 0xFF


class CollectiveKind(IntEnum):
    REDUCE = 0x01
    ALLREDUCE = 0x02


FORMAT_BYTES: dict[ConcreteFormat, int] = {
    ConcreteFormat.INT8: 1,
    ConcreteFormat.FP16: 2,
    ConcreteFormat.BF16: 2,
    ConcreteFormat.FP32: 4,
}


@dataclass(frozen=True, slots=True)
class OperationKey:
    job_id: int
    group_id: int
    group_generation: int
    operation_id: int
    operation_generation: int

    def __post_init__(self) -> None:
        for name, bits in (
            ("job_id", 64),
            ("group_id", 16),
            ("group_generation", 16),
            ("operation_id", 16),
            ("operation_generation", 32),
        ):
            value = getattr(self, name)
            if not 0 <= value < 1 << bits:
                raise ValueError(f"{name} exceeds {bits} bits")


@dataclass(frozen=True, slots=True)
class ScalarBits:
    format: ConcreteFormat
    bits: int

    def __post_init__(self) -> None:
        if self.format not in FORMAT_BYTES:
            raise ValueError("rank scalar must use a native concrete format")
        if not 0 <= self.bits < 1 << (8 * FORMAT_BYTES[self.format]):
            raise ValueError("scalar bit pattern exceeds its format width")


@dataclass(frozen=True, slots=True)
class TypedVector:
    format: ConcreteFormat
    bits: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.format not in FORMAT_BYTES:
            raise ValueError("rank vector must use a native concrete format")
        if not self.bits or len(self.bits) >= 1 << 32:
            raise ValueError("vector length must be in 1..2^32-1")
        limit = 1 << (8 * FORMAT_BYTES[self.format])
        if any(not 0 <= value < limit for value in self.bits):
            raise ValueError("vector contains an out-of-range bit pattern")

    def scalar(self, index: int) -> ScalarBits:
        return ScalarBits(self.format, self.bits[index])


@dataclass(frozen=True, slots=True)
class OperationConfig:
    key: OperationKey
    kind: CollectiveKind
    ranks: tuple[int, ...]
    element_count: int
    accumulator: AccumulatorPolicy
    partial_wire: PartialWirePolicy
    output_format: ResultWirePolicy
    reduce_destination: int | None
    maximum_original_terms: int
    kulisch_bits: int
    mtu: int = 1500

    def __post_init__(self) -> None:
        if not self.ranks or len(set(self.ranks)) != len(self.ranks):
            raise ValueError("rank IDs must be non-empty and unique")
        if any(not 0 <= rank < 1 << 16 for rank in self.ranks):
            raise ValueError("rank ID exceeds 16 bits")
        if not 0 < self.element_count < 1 << 32:
            raise ValueError("zero-length and oversized SUM vectors are invalid")
        if self.kind == CollectiveKind.REDUCE:
            if self.reduce_destination not in self.ranks:
                raise ValueError("Reduce destination must be a participating rank")
        elif self.reduce_destination is not None:
            raise ValueError("AllReduce has no single Reduce destination")
        if not len(self.ranks) <= self.maximum_original_terms < 1 << 32:
            raise ValueError("term bound must cover every original rank")
        try:
            object.__setattr__(self, "accumulator", AccumulatorPolicy(self.accumulator))
        except ValueError as error:
            raise ValueError("unknown accumulator policy") from error
        try:
            object.__setattr__(self, "output_format", ResultWirePolicy(self.output_format))
        except ValueError as error:
            raise ValueError("unknown RESULT wire policy") from error
        if not 576 <= self.mtu <= 9216:
            raise ValueError("MTU must be in the supported negotiation range")
        if not 8 <= self.kulisch_bits <= 4096:
            raise ValueError("Kulisch width must be in 8..4096 bits")
        if self.accumulator == AccumulatorPolicy.KULISCH_FIXED:
            if self.partial_wire not in (PartialWirePolicy.KULISCH, PartialWirePolicy.AUTO):
                raise ValueError("exact accumulation needs lossless partial transport")
            from .numbers import required_kulisch_bits

            if self.kulisch_bits < required_kulisch_bits(self.maximum_original_terms):
                raise ValueError("Kulisch width cannot represent the original-term bound")
        if self.accumulator == AccumulatorPolicy.FP32_ARRIVAL and self.partial_wire not in (
            PartialWirePolicy.FP32,
            PartialWirePolicy.AUTO,
        ):
            raise ValueError("FP32 accumulation supports FP32 or Auto partial transport")
