"""Explicit supported arithmetic tuples; never infer a Cartesian product."""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    AccumulatorPolicy,
    ConcreteFormat,
    OperationConfig,
    PartialWirePolicy,
    ResultWirePolicy,
)
from .numbers import required_kulisch_bits


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    input_format: ConcreteFormat
    accumulator: AccumulatorPolicy
    partial_wire: PartialWirePolicy
    output_format: ResultWirePolicy
    maximum_original_terms: int
    maximum_vector_elements: int
    maximum_kulisch_bits: int
    mtus: tuple[int, ...]
    maximum_window_intervals: int
    maximum_window_bytes: int
    maximum_replay_frames_per_binding: int = 32
    fixed_kulisch_bits: int | None = None

    def __post_init__(self) -> None:
        if self.input_format == ConcreteFormat.KULISCH:
            raise ValueError("rank input must use a native format")
        if not self.mtus or any(not 576 <= mtu <= 9216 for mtu in self.mtus):
            raise ValueError("capability MTUs are invalid")
        if (
            min(
                self.maximum_original_terms,
                self.maximum_vector_elements,
                self.maximum_kulisch_bits,
                self.maximum_window_intervals,
                self.maximum_window_bytes,
                self.maximum_replay_frames_per_binding,
            )
            <= 0
        ):
            raise ValueError("capability limits must be positive")

    def supports(self, config: OperationConfig, input_format: ConcreteFormat) -> bool:
        return (
            input_format == self.input_format
            and config.accumulator == self.accumulator
            and config.partial_wire == self.partial_wire
            and config.output_format == self.output_format
            and config.maximum_original_terms <= self.maximum_original_terms
            and config.element_count <= self.maximum_vector_elements
            and config.kulisch_bits <= self.maximum_kulisch_bits
            and (self.fixed_kulisch_bits is None or config.kulisch_bits == self.fixed_kulisch_bits)
            and config.mtu in self.mtus
            and (
                config.accumulator != AccumulatorPolicy.KULISCH_FIXED
                or config.kulisch_bits >= required_kulisch_bits(config.maximum_original_terms)
            )
        )


class CapabilityCatalog:
    def __init__(self, records: tuple[CapabilityRecord, ...]) -> None:
        if not records:
            raise ValueError("capability catalog cannot be empty")
        keys = [
            (record.input_format, record.accumulator, record.partial_wire, record.output_format)
            for record in records
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate arithmetic capability tuple")
        self.records = records

    def require(self, config: OperationConfig, input_format: ConcreteFormat) -> CapabilityRecord:
        for record in self.records:
            if record.supports(config, input_format):
                return record
        raise ValueError("arithmetic configuration is not advertised")


def software_capabilities() -> CapabilityCatalog:
    """Model-only records; these do not advertise any current RTL ability."""
    records: list[CapabilityRecord] = []
    native = (
        ConcreteFormat.INT8,
        ConcreteFormat.FP16,
        ConcreteFormat.BF16,
        ConcreteFormat.FP32,
    )
    for input_format in native:
        for output_format in ResultWirePolicy:
            for accumulator, partial in (
                (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO),
                (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH),
            ):
                records.append(
                    CapabilityRecord(
                        input_format,
                        accumulator,
                        partial,
                        output_format,
                        1 << 20,
                        (1 << 32) - 1,
                        4096,
                        (576, 1500, 9000),
                        32,
                        65536,
                    )
                )
    for partial in (PartialWirePolicy.FP32, PartialWirePolicy.AUTO):
        for output_format in ResultWirePolicy:
            records.append(
                CapabilityRecord(
                    ConcreteFormat.FP32,
                    AccumulatorPolicy.FP32_ARRIVAL,
                    partial,
                    output_format,
                    1 << 20,
                    (1 << 32) - 1,
                    4096,
                    (576, 1500, 9000),
                    32,
                    65536,
                )
            )
    return CapabilityCatalog(tuple(records))


def single_rtl_capabilities() -> CapabilityCatalog:
    """Implemented SINGLE tuples, not a board claim."""
    native = (
        ConcreteFormat.INT8,
        ConcreteFormat.FP16,
        ConcreteFormat.BF16,
        ConcreteFormat.FP32,
    )
    exact_records = tuple(
        CapabilityRecord(
            input_format,
            accumulator,
            partial,
            output_format,
            16,
            4096,
            4096,
            (576, 1500),
            16,
            65536,
            2,
            None,
        )
        for accumulator, partial in (
            (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO),
            (AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.KULISCH),
        )
        for input_format in native
        for output_format in (
            ResultWirePolicy.INT8,
            ResultWirePolicy.FP16,
            ResultWirePolicy.BF16,
            ResultWirePolicy.FP32,
            ResultWirePolicy.KULISCH,
            ResultWirePolicy.AUTO,
        )
    )
    return CapabilityCatalog(
        (
            *exact_records,
            *(
                CapabilityRecord(
                    ConcreteFormat.FP32,
                    AccumulatorPolicy.FP32_ARRIVAL,
                    PartialWirePolicy.FP32,
                    output,
                    16,
                    4096,
                    320,
                    (576, 1500),
                    16,
                    65536,
                    2,
                )
                for output in (ResultWirePolicy.FP32, ResultWirePolicy.AUTO)
            ),
        )
    )
