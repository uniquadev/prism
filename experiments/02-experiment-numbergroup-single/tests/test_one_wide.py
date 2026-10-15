"""Keep the NumberGroup comparison tied to its actual numeric values."""

from collections import Counter

import pytest
from prism_ccl.application.packing import select_auto_groups
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.domain.numbers import combine_exact, decode_native, is_lossless

from src.numbergroup_single.workloads import one_wide_vectors


@pytest.mark.parametrize("fmt", (ConcreteFormat.FP16, ConcreteFormat.BF16, ConcreteFormat.FP32))
def test_one_wide_needs_exactly_one_kulisch_value(fmt: ConcreteFormat) -> None:
    first, second = one_wide_vectors(fmt, 64)
    sums = tuple(
        combine_exact((decode_native(a, fmt), decode_native(b, fmt)))
        for a, b in zip(first, second, strict=True)
    )
    assert not is_lossless(sums[0], ConcreteFormat.FP32)
    assert all(is_lossless(value, fmt) for value in sums[1:])
    formats = Counter(group.format for group in select_auto_groups(sums, 320))
    assert formats[ConcreteFormat.KULISCH] == 1
    assert sum(len(group.values) for group in select_auto_groups(sums, 320)) == 64
    elements = Counter()
    for group in select_auto_groups(sums, 320):
        elements[group.format] += len(group.values)
    assert elements == {ConcreteFormat.KULISCH: 1, fmt: 63}


def test_one_wide_rejects_single_element() -> None:
    with pytest.raises(ValueError, match="at least two"):
        one_wide_vectors(ConcreteFormat.FP32, 1)
