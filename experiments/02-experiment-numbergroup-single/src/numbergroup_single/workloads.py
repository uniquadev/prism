"""Bit-exact input vectors for reproducible transport comparisons."""

from prism_ccl.domain.model import ConcreteFormat


def one_wide_vectors(input_format: ConcreteFormat, count: int) -> tuple[tuple[int, ...], ...]:
    """One exact-only sum followed by values that retain the selected native format."""
    exact_term, native_term = {
        ConcreteFormat.FP16: (0x0001, 0x3C01),
        ConcreteFormat.BF16: (0x0001, 0x4980),
        ConcreteFormat.FP32: (0x33800000, 0x3F800008),
    }[input_format]
    one = {
        ConcreteFormat.FP16: 0x3C00,
        ConcreteFormat.BF16: 0x3F80,
        ConcreteFormat.FP32: 0x3F800000,
    }[input_format]
    if count < 2:
        raise ValueError("one_wide requires at least two elements")
    return ((one, *([native_term] * (count - 1))), (exact_term, *([0] * (count - 1))))
