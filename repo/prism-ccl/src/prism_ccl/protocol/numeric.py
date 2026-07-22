"""Bit-pattern conversion for PRISM numeric wire datatypes.

This module owns scalar datatype interpretation and rounding. Collective
algorithms consume these codecs but do not duplicate format layouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .constants import WireFormat


@dataclass(frozen=True, slots=True)
class DecodedNumber:
    """One exact scalar decoded from a PRISM wire bit pattern."""

    kind: str
    sign: bool
    value: Fraction | None = None


@dataclass(frozen=True, slots=True)
class RoundResult:
    """A rounded scalar and its IEEE-style status flags."""

    bits: int
    overflow: bool = False
    underflow: bool = False
    inexact: bool = False


FLOAT_LAYOUTS: dict[WireFormat, tuple[int, int, int]] = {
    WireFormat.FP16: (5, 10, 15),
    WireFormat.BF16: (8, 7, 127),
    WireFormat.FP32: (8, 23, 127),
}

CANONICAL_NAN: dict[WireFormat, int] = {
    WireFormat.FP16: 0x7E00,
    WireFormat.BF16: 0x7FC0,
    WireFormat.FP32: 0x7FC00000,
}


def power_of_two(exponent: int) -> Fraction:
    """Return an exact power of two without host floating-point arithmetic."""

    return Fraction(1 << exponent, 1) if exponent >= 0 else Fraction(1, 1 << -exponent)


def _round_nearest_even(value: Fraction) -> tuple[int, bool]:
    quotient, remainder = divmod(value.numerator, value.denominator)
    doubled = remainder * 2
    increment = doubled > value.denominator or (doubled == value.denominator and bool(quotient & 1))
    return quotient + int(increment), remainder != 0


def _floor_log2(value: Fraction) -> int:
    if value <= 0:
        raise ValueError("logarithm input must be positive")
    numerator = value.numerator
    denominator = value.denominator
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        if numerator < denominator << exponent:
            exponent -= 1
    elif numerator << -exponent < denominator:
        exponent -= 1
    return exponent


def float_layout(wire_format: WireFormat) -> tuple[int, int, int]:
    """Return exponent width, fraction width, and bias for a float format."""

    try:
        return FLOAT_LAYOUTS[wire_format]
    except KeyError as error:
        raise ValueError(f"unsupported floating wire format: {wire_format!r}") from error


def canonical_nan_bits(wire_format: WireFormat) -> int:
    """Return the canonical quiet-NaN encoding for a floating wire format."""

    try:
        return CANONICAL_NAN[wire_format]
    except KeyError as error:
        raise ValueError(f"unsupported floating wire format: {wire_format!r}") from error


def infinity_bits(wire_format: WireFormat, *, sign: bool) -> int:
    """Encode signed infinity for a floating wire format."""

    exponent_bits, fraction_bits, _ = float_layout(wire_format)
    return (int(sign) << (exponent_bits + fraction_bits)) | (
        ((1 << exponent_bits) - 1) << fraction_bits
    )


def decode_bits(bits: int, wire_format: WireFormat) -> DecodedNumber:
    """Decode one wire element exactly from its integer bit pattern."""

    if wire_format == WireFormat.INT8:
        if not 0 <= bits <= 0xFF:
            raise ValueError("INT8 bit pattern does not fit in one byte")
        integer = bits - 0x100 if bits & 0x80 else bits
        return DecodedNumber("zero" if integer == 0 else "finite", False, Fraction(integer))
    exponent_bits, fraction_bits, bias = float_layout(wire_format)
    width = 1 + exponent_bits + fraction_bits
    if not 0 <= bits < 1 << width:
        raise ValueError(f"{wire_format.name} bit pattern exceeds {width} bits")
    sign = bool(bits >> (width - 1))
    exponent_mask = (1 << exponent_bits) - 1
    fraction_mask = (1 << fraction_bits) - 1
    exponent = (bits >> fraction_bits) & exponent_mask
    fraction = bits & fraction_mask
    if exponent == exponent_mask:
        return DecodedNumber("nan" if fraction else "infinity", sign)
    if exponent == 0:
        if fraction == 0:
            return DecodedNumber("zero", sign, Fraction(0))
        magnitude = Fraction(fraction) * power_of_two(1 - bias - fraction_bits)
    else:
        magnitude = Fraction((1 << fraction_bits) | fraction) * power_of_two(
            exponent - bias - fraction_bits
        )
    return DecodedNumber("finite", sign, -magnitude if sign else magnitude)


def round_fraction(
    value: Fraction, wire_format: WireFormat, *, zero_sign: bool = False
) -> RoundResult:
    """Round an exact finite value using round-to-nearest, ties-to-even."""

    exponent_bits, fraction_bits, bias = float_layout(wire_format)
    sign = value < 0 or (value == 0 and zero_sign)
    magnitude = abs(value)
    sign_field = int(sign) << (exponent_bits + fraction_bits)
    if magnitude == 0:
        return RoundResult(sign_field)
    maximum_exponent = ((1 << exponent_bits) - 2) - bias
    minimum_normal_exponent = 1 - bias
    exponent = _floor_log2(magnitude)
    infinity = infinity_bits(wire_format, sign=sign)
    if exponent > maximum_exponent:
        return RoundResult(infinity, overflow=True, inexact=True)
    if exponent >= minimum_normal_exponent:
        scaled = magnitude / power_of_two(exponent - fraction_bits)
        significand, inexact = _round_nearest_even(scaled)
        if significand == 1 << (fraction_bits + 1):
            significand >>= 1
            exponent += 1
        if exponent > maximum_exponent:
            return RoundResult(infinity, overflow=True, inexact=True)
        exponent_field = exponent + bias
        bits = sign_field | (exponent_field << fraction_bits) | (significand - (1 << fraction_bits))
        return RoundResult(bits, inexact=inexact)
    unit = power_of_two(minimum_normal_exponent - fraction_bits)
    fraction, inexact = _round_nearest_even(magnitude / unit)
    if fraction == 0:
        return RoundResult(sign_field, underflow=inexact, inexact=inexact)
    if fraction == 1 << fraction_bits:
        return RoundResult(sign_field | (1 << fraction_bits), underflow=inexact, inexact=inexact)
    return RoundResult(sign_field | fraction, underflow=inexact, inexact=inexact)


def canonicalize_bits(bits: int, wire_format: WireFormat) -> int:
    """Canonicalize NaN while preserving every non-NaN bit pattern."""

    decoded = decode_bits(bits, wire_format)
    return canonical_nan_bits(wire_format) if decoded.kind == "nan" else bits
