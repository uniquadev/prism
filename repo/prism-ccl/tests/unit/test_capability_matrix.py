"""Every model advertisement is tested as a tuple, not mask product."""

from __future__ import annotations

from dataclasses import replace

import pytest

from prism_ccl.domain.capabilities import software_capabilities
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationConfig,
    OperationKey,
    PartialWirePolicy,
)
from prism_ccl.domain.numbers import required_kulisch_bits
from prism_ccl.domain.topology import PrismCapacity
from prism_ccl.wire.capabilities import decode_capabilities, encode_capability_pages


def _config(
    accumulator: AccumulatorPolicy,
    partial: PartialWirePolicy,
    output: ConcreteFormat,
    *,
    mtu: int = 1500,
) -> OperationConfig:
    return OperationConfig(
        OperationKey(1, 2, 3, 4, 5),
        CollectiveKind.ALLREDUCE,
        (0, 1, 2),
        9,
        accumulator,
        partial,
        output,
        None,
        3,
        required_kulisch_bits(3),
        mtu,
    )


def test_every_advertised_tuple_and_mtu_round_trips_through_capability_pages() -> None:
    catalog = software_capabilities()
    assert len(catalog.records) == 60
    capacity = PrismCapacity(8, 16, 32, 65536, True, True)
    for mtu in (576, 1500, 9000):
        pages = encode_capability_pages(catalog, capacity, mtu=mtu)
        recovered = tuple(
            record for page in pages for record in decode_capabilities(page)[0].records
        )
        assert recovered == catalog.records
        assert all(record.maximum_replay_frames_per_binding == 32 for record in recovered)
        assert all(decode_capabilities(page)[1] == capacity for page in pages)
        for record in recovered:
            config = _config(record.accumulator, record.partial_wire, record.output_format, mtu=mtu)
            assert catalog.require(config, record.input_format) == record
            with pytest.raises(ValueError, match="not advertised"):
                catalog.require(replace(config, mtu=1600), record.input_format)


@pytest.mark.parametrize("depth", (0, 33))
def test_invalid_replay_depth_is_not_an_advertised_capability(depth: int) -> None:
    capacity = PrismCapacity(8, 16, 32, 65536, True, True)
    page = bytearray(encode_capability_pages(software_capabilities(), capacity, mtu=576)[0])
    page[22:24] = depth.to_bytes(2, "big")
    with pytest.raises(ValueError, match="replay depth"):
        decode_capabilities(bytes(page))


def test_unsupported_cross_products_and_limits_are_rejected() -> None:
    catalog = software_capabilities()
    fp32_arrival = _config(
        AccumulatorPolicy.FP32_ARRIVAL, PartialWirePolicy.FP32, ConcreteFormat.FP32
    )
    with pytest.raises(ValueError, match="not advertised"):
        catalog.require(fp32_arrival, ConcreteFormat.FP16)
    auto = _config(AccumulatorPolicy.KULISCH_FIXED, PartialWirePolicy.AUTO, ConcreteFormat.FP32)
    with pytest.raises(ValueError, match="not advertised"):
        catalog.require(
            replace(
                auto,
                maximum_original_terms=(1 << 20) + 1,
                kulisch_bits=required_kulisch_bits((1 << 20) + 1),
            ),
            ConcreteFormat.FP32,
        )
    with pytest.raises(ValueError, match="not advertised"):
        catalog.require(replace(auto, element_count=(1 << 32) - 1, mtu=1600), ConcreteFormat.FP32)
    with pytest.raises(ValueError, match="lossless partial"):
        replace(auto, partial_wire=PartialWirePolicy.FP32)
    with pytest.raises(ValueError, match="width"):
        replace(auto, kulisch_bits=279)
