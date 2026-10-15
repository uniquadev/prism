"""The static SINGLE simulator catalog matches the admitted RTL tuple."""

from dataclasses import replace

import pytest

from prism_ccl.domain.capabilities import single_rtl_capabilities
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationConfig,
    OperationKey,
    PartialWirePolicy,
    ResultWirePolicy,
)
from prism_ccl.domain.numbers import required_kulisch_bits


def config(output_format: ResultWirePolicy) -> OperationConfig:
    return OperationConfig(
        OperationKey(1, 1, 0, 1, 0),
        CollectiveKind.ALLREDUCE,
        (0, 1),
        64,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.KULISCH,
        output_format,
        None,
        2,
        required_kulisch_bits(2),
        1500,
    )


def test_every_advertised_native_tuple_is_explicit() -> None:
    catalog = single_rtl_capabilities()
    native = (
        ConcreteFormat.INT8,
        ConcreteFormat.FP16,
        ConcreteFormat.BF16,
        ConcreteFormat.FP32,
    )
    assert len(catalog.records) == 50
    assert {record.maximum_replay_frames_per_binding for record in catalog.records} == {2}
    for partial in (PartialWirePolicy.AUTO, PartialWirePolicy.KULISCH):
        for input_format in native:
            for output_format in (
                ResultWirePolicy.INT8,
                ResultWirePolicy.FP16,
                ResultWirePolicy.BF16,
                ResultWirePolicy.FP32,
                ResultWirePolicy.AUTO,
            ):
                catalog.require(replace(config(output_format), partial_wire=partial), input_format)
    for accumulator in (AccumulatorPolicy.FP32_ARRIVAL,):
        for output in (ResultWirePolicy.FP32, ResultWirePolicy.AUTO):
            catalog.require(
                replace(
                    config(output),
                    accumulator=accumulator,
                    partial_wire=PartialWirePolicy.FP32,
                    element_count=4096,
                ),
                ConcreteFormat.FP32,
            )
    for input_format in native:
        catalog.require(
            replace(
                config(ResultWirePolicy.FP32),
                output_format=ResultWirePolicy.KULISCH,
                kulisch_bits=320,
            ),
            input_format,
        )


def test_unimplemented_or_oversize_tuples_are_not_advertised() -> None:
    catalog = single_rtl_capabilities()
    base = config(ResultWirePolicy.FP32)
    rejected = (
        replace(
            base,
            accumulator=AccumulatorPolicy.FP32_ARRIVAL,
            partial_wire=PartialWirePolicy.FP32,
            output_format=ResultWirePolicy.FP16,
        ),
        replace(base, element_count=4097),
        replace(
            base,
            maximum_original_terms=17,
            kulisch_bits=required_kulisch_bits(17),
        ),
        replace(base, mtu=9000),
    )
    for candidate in rejected:
        with pytest.raises(ValueError):
            catalog.require(candidate, ConcreteFormat.FP32)
    with pytest.raises(ValueError):
        catalog.require(
            replace(
                base,
                accumulator=AccumulatorPolicy.FP32_ARRIVAL,
                partial_wire=PartialWirePolicy.FP32,
            ),
            ConcreteFormat.FP16,
        )
    with pytest.raises(ValueError):
        replace(base, kulisch_bits=required_kulisch_bits(2) - 1)
