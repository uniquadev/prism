"""Bit-exact arithmetic reference for PRISM reduction profiles."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from ..protocol.constants import AccumulatorProfile, ReductionOperator, WireFormat
from ..protocol.models import required_accumulator_state_bits
from ..protocol.numeric import (
    RoundResult,
    canonical_nan_bits,
    canonicalize_bits,
    decode_bits,
    infinity_bits,
    power_of_two,
    round_fraction,
)
from ..transport.contracts import TransportError, TransportRequest


@dataclass(frozen=True, slots=True)
class KulischSelection:
    required_width: int
    selected_width: int
    selected_index: int
    sufficient: bool

    @property
    def accumulation_inexact(self) -> bool:
        return not self.sufficient


@dataclass(frozen=True, slots=True)
class KulischResult:
    bits: int
    selection: KulischSelection
    accumulation_inexact: bool
    saturated: bool
    canonical_nan: bool
    positive_infinity: bool
    negative_infinity: bool
    rounding: RoundResult


def fp32_add_bits(left_bits: int, right_bits: int) -> int:
    """Perform one normative PRISM binary32 addition."""

    left = decode_bits(left_bits, WireFormat.FP32)
    right = decode_bits(right_bits, WireFormat.FP32)
    if left.kind == "nan" or right.kind == "nan":
        return canonical_nan_bits(WireFormat.FP32)
    if left.kind == "infinity" and right.kind == "infinity":
        if left.sign != right.sign:
            return canonical_nan_bits(WireFormat.FP32)
        return (int(left.sign) << 31) | 0x7F800000
    if left.kind == "infinity":
        return (int(left.sign) << 31) | 0x7F800000
    if right.kind == "infinity":
        return (int(right.sign) << 31) | 0x7F800000
    assert left.value is not None and right.value is not None
    exact = left.value + right.value
    zero_sign = exact == 0 and left.kind == right.kind == "zero" and left.sign == right.sign
    return round_fraction(exact, WireFormat.FP32, zero_sign=zero_sign and left.sign).bits


def fp32_sum_bits(contributions: Iterable[tuple[int, int]], *, ordered: bool) -> int:
    """Fold contributors without inserting a zero seed."""

    values = list(contributions)
    if not values:
        raise ValueError("at least one contribution is required")
    if ordered:
        values.sort(key=lambda item: item[0])
    result = canonicalize_bits(values[0][1], WireFormat.FP32)
    for _, value in values[1:]:
        result = fp32_add_bits(result, value)
    return result


def select_kulisch_width(
    input_format: WireFormat,
    maximum_terms: int,
    compiled_widths: Sequence[int],
) -> KulischSelection:
    widths = tuple(compiled_widths)
    if not widths or any(width <= 0 for width in widths) or len(widths) != len(set(widths)):
        raise ValueError("compiled Kulisch widths must be non-empty, positive, and unique")
    required = required_accumulator_state_bits(
        AccumulatorProfile.KULISCH_FP32,
        ReductionOperator.SUM,
        input_format,
        maximum_terms,
    )
    sufficient = [(width, index) for index, width in enumerate(widths) if width >= required]
    if sufficient:
        selected, index = min(sufficient)
        return KulischSelection(required, selected, index, True)
    selected = max(widths)
    return KulischSelection(required, selected, widths.index(selected), False)


def _kulisch_unit(wire_format: WireFormat) -> Fraction:
    units = {
        WireFormat.INT8: Fraction(1),
        WireFormat.FP16: power_of_two(-24),
        WireFormat.BF16: power_of_two(-133),
        WireFormat.FP32: power_of_two(-149),
    }
    try:
        return units[wire_format]
    except KeyError as error:
        raise ValueError(f"unsupported Kulisch input format: {wire_format!r}") from error


def kulisch_sum_bits(
    values: Iterable[int],
    *,
    input_format: WireFormat,
    output_format: WireFormat = WireFormat.FP32,
    maximum_terms: int,
    compiled_widths: Sequence[int],
    upstream_inexact: Iterable[bool] | None = None,
) -> KulischResult:
    """Stream deposits into a signed saturating accumulator and round once."""

    encoded = list(values)
    if not encoded:
        raise ValueError("at least one contribution is required")
    inherited = list(upstream_inexact or (False for _ in encoded))
    if len(inherited) != len(encoded):
        raise ValueError("upstream warning count does not match contribution count")
    selection = select_kulisch_width(input_format, maximum_terms, compiled_widths)
    minimum = -(1 << (selection.selected_width - 1))
    maximum = (1 << (selection.selected_width - 1)) - 1
    unit = _kulisch_unit(input_format)
    accumulator = 0
    saturated = False
    saw_nan = False
    saw_positive_infinity = False
    saw_negative_infinity = False
    saw_finite_nonzero = False
    zero_signs: set[bool] = set()
    for bits in encoded:
        decoded = decode_bits(bits, input_format)
        if decoded.kind == "nan":
            saw_nan = True
        elif decoded.kind == "infinity":
            saw_negative_infinity |= decoded.sign
            saw_positive_infinity |= not decoded.sign
        else:
            assert decoded.value is not None
            if decoded.value == 0:
                zero_signs.add(decoded.sign)
            else:
                saw_finite_nonzero = True
            deposit = decoded.value / unit
            if deposit.denominator != 1:
                raise AssertionError("finite input is not aligned to its Kulisch unit")
            candidate = accumulator + deposit.numerator
            if candidate > maximum:
                accumulator = maximum
                saturated = True
            elif candidate < minimum:
                accumulator = minimum
                saturated = True
            else:
                accumulator = candidate
    warning = selection.accumulation_inexact or saturated or any(inherited)
    canonical_nan = saw_nan or (saw_positive_infinity and saw_negative_infinity)
    if canonical_nan:
        rounded = RoundResult(canonical_nan_bits(output_format))
    elif saw_positive_infinity or saw_negative_infinity:
        rounded = RoundResult(infinity_bits(output_format, sign=saw_negative_infinity))
    else:
        zero_sign = accumulator == 0 and not saw_finite_nonzero and zero_signs == {True}
        rounded = round_fraction(Fraction(accumulator) * unit, output_format, zero_sign=zero_sign)
    return KulischResult(
        bits=rounded.bits,
        selection=selection,
        accumulation_inexact=warning,
        saturated=saturated,
        canonical_nan=canonical_nan,
        positive_infinity=saw_positive_infinity,
        negative_infinity=saw_negative_infinity,
        rounding=rounded,
    )


def evaluate_reference_collective(
    requests: tuple[TransportRequest, ...],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Evaluate a complete rendezvous using the independent reference model."""

    if not requests:
        raise TransportError("a collective requires at least one request")
    first = requests[0]
    if first.accumulator in (
        AccumulatorProfile.FP32_ARRIVAL,
        AccumulatorProfile.FP32_ORDERED,
    ):
        if first.datatype != WireFormat.FP32 or first.output_datatype != WireFormat.FP32:
            raise TransportError("FP32 accumulator profiles require FP32 input and output")
        ordered = first.accumulator == AccumulatorProfile.FP32_ORDERED
        reduced = tuple(
            fp32_sum_bits(
                ((request.rank, request.values[index]) for request in requests),
                ordered=ordered,
            )
            for index in range(len(first.values))
        )
        return reduced, ()

    results = tuple(
        kulisch_sum_bits(
            (request.values[index] for request in requests),
            input_format=first.datatype,
            output_format=first.output_datatype,
            maximum_terms=first.maximum_terms,
            compiled_widths=first.compiled_widths,
        )
        for index in range(len(first.values))
    )
    warnings = (
        ("ACCUMULATION_INEXACT",) if any(result.accumulation_inexact for result in results) else ()
    )
    return tuple(result.bits for result in results), warnings
