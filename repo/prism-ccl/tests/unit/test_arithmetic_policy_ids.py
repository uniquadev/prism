"""Arithmetic policy IDs are explicit and unknown values are rejected."""

from dataclasses import replace

import pytest

from prism_ccl.domain.capabilities import single_rtl_capabilities, software_capabilities
from prism_ccl.domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    ConcreteFormat,
    OperationConfig,
    OperationKey,
    PartialWirePolicy,
    ResultWirePolicy,
)
from prism_ccl.wire.control import ContextRecord, EndpointBindingRecord, NodeRole, PeerKind


def _record() -> ContextRecord:
    formats = frozenset({ConcreteFormat.FP32})
    return ContextRecord(
        NodeRole.SINGLE,
        None,
        (10,),
        (10,),
        1,
        8,
        8192,
        1,
        280,
        1500,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.AUTO,
        ConcreteFormat.FP32,
        formats,
        CollectiveKind.ALLREDUCE,
        bytes.fromhex("020000000000"),
        1,
        1,
        formats,
        (
            EndpointBindingRecord(
                10, 1, 2, PeerKind.RANK, bytes.fromhex("020000000001"), 0, 1, formats, True
            ),
        ),
    )


def config(output: ResultWirePolicy) -> OperationConfig:
    return OperationConfig(
        OperationKey(1, 1, 0, 1, 0),
        CollectiveKind.ALLREDUCE,
        (0, 1),
        64,
        AccumulatorPolicy.KULISCH_FIXED,
        PartialWirePolicy.KULISCH,
        output,
        None,
        2,
        280,
        1500,
    )


def test_only_assigned_policy_ids_are_advertised() -> None:
    assert {int(policy) for policy in AccumulatorPolicy} == {0x01, 0x80}
    assert int(AccumulatorPolicy.FP32_ARRIVAL) == 0x01
    assert int(AccumulatorPolicy.KULISCH_FIXED) == 0x80
    for catalog in (software_capabilities(), single_rtl_capabilities()):
        assert {int(record.accumulator) for record in catalog.records} == {0x01, 0x80}


def test_unassigned_policy_cannot_enter_operation_config() -> None:
    with pytest.raises(ValueError):
        AccumulatorPolicy(0x02)
    with pytest.raises(ValueError):
        replace(config(ResultWirePolicy.FP32), accumulator=0x02)


def test_unassigned_policy_is_rejected_in_context_both_directions() -> None:
    raw = bytearray(_record().pack())
    raw[24] = 0x02
    with pytest.raises(ValueError):
        ContextRecord.unpack(bytes(raw))
    with pytest.raises(ValueError):
        replace(_record(), accumulator=0x02).pack()
