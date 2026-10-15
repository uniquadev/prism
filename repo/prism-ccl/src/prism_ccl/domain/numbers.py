"""Exact scalar semantics; no host-float arithmetic or implicit flush-to-zero."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .model import FORMAT_BYTES, ConcreteFormat

KULISCH_SCALE_EXPONENT = -149
FLOAT_LAYOUTS: dict[ConcreteFormat, tuple[int, int, int]] = {
    ConcreteFormat.FP16: (5, 10, 15),
    ConcreteFormat.BF16: (8, 7, 127),
    ConcreteFormat.FP32: (8, 23, 127),
}
CANONICAL_NAN: dict[ConcreteFormat, int] = {
    ConcreteFormat.FP16: 0x7E00,
    ConcreteFormat.BF16: 0x7FC0,
    ConcreteFormat.FP32: 0x7FC00000,
}


@dataclass(frozen=True, slots=True)
class ExactValue:
    kind: str  # finite, zero, infinity, nan
    sign: bool
    value: Fraction | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"finite", "zero", "infinity", "nan"}:
            raise ValueError("unknown exact value kind")
        if self.kind in {"finite", "zero"} and self.value is None:
            raise ValueError("finite value requires a rational magnitude")
        if self.kind == "zero" and self.value != 0:
            raise ValueError("zero kind requires zero value")
        if self.kind in {"infinity", "nan"} and self.value is not None:
            raise ValueError("special value cannot carry a rational value")


def power_of_two(exponent: int) -> Fraction:
    return Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)


def required_kulisch_bits(maximum_original_terms: int) -> int:
    """Signed width at scale 2^-149 for any finite FP32 input SUM."""
    if not 0 < maximum_original_terms < 1 << 32:
        raise ValueError("original term bound must be in 1..2^32-1")
    return 278 + (maximum_original_terms - 1).bit_length()


def decode_native(bits: int, fmt: ConcreteFormat) -> ExactValue:
    if fmt not in FORMAT_BYTES or not 0 <= bits < 1 << (FORMAT_BYTES[fmt] * 8):
        raise ValueError("invalid native bit pattern")
    if fmt == ConcreteFormat.INT8:
        signed = bits - 256 if bits & 0x80 else bits
        return ExactValue("zero" if signed == 0 else "finite", signed < 0, Fraction(signed))
    exponent_bits, fraction_bits, bias = FLOAT_LAYOUTS[fmt]
    width = 1 + exponent_bits + fraction_bits
    sign = bool(bits >> (width - 1))
    exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
    fraction = bits & ((1 << fraction_bits) - 1)
    if exponent == (1 << exponent_bits) - 1:
        return ExactValue("nan" if fraction else "infinity", sign)
    if exponent == 0:
        if fraction == 0:
            return ExactValue("zero", sign, Fraction(0))
        magnitude = Fraction(fraction) * power_of_two(1 - bias - fraction_bits)
    else:
        magnitude = Fraction((1 << fraction_bits) | fraction) * power_of_two(
            exponent - bias - fraction_bits
        )
    value = -magnitude if sign else magnitude
    return ExactValue("finite", sign, value)


def _floor_log2(value: Fraction) -> int:
    numerator, denominator = value.numerator, value.denominator
    exponent = numerator.bit_length() - denominator.bit_length()
    if (exponent >= 0 and numerator < denominator << exponent) or (
        exponent < 0 and numerator << -exponent < denominator
    ):
        exponent -= 1
    return exponent


def _nearest_even(value: Fraction) -> int:
    quotient, remainder = divmod(value.numerator, value.denominator)
    doubled = 2 * remainder
    return quotient + int(
        doubled > value.denominator or (doubled == value.denominator and bool(quotient & 1))
    )


def round_native(value: ExactValue, fmt: ConcreteFormat) -> int:
    """RNE conversion of available value; exactness is checked separately."""
    if fmt == ConcreteFormat.INT8:
        if value.kind == "zero":
            return 0
        if value.kind != "finite" or value.value is None or value.value.denominator != 1:
            raise ValueError("INT8 needs a finite integral value")
        if not -128 <= value.value <= 127:
            raise ValueError("INT8 value is out of range")
        return int(value.value) & 0xFF
    exponent_bits, fraction_bits, bias = FLOAT_LAYOUTS[fmt]
    sign_field = int(value.sign) << (exponent_bits + fraction_bits)
    exponent_mask = (1 << exponent_bits) - 1
    if value.kind == "nan":
        return CANONICAL_NAN[fmt]
    if value.kind == "infinity":
        return sign_field | (exponent_mask << fraction_bits)
    if value.kind == "zero":
        return sign_field
    assert value.value is not None
    magnitude = abs(value.value)
    maximum_exponent = exponent_mask - 1 - bias
    minimum_exponent = 1 - bias
    exponent = _floor_log2(magnitude)
    if exponent > maximum_exponent:
        return sign_field | (exponent_mask << fraction_bits)
    if exponent >= minimum_exponent:
        significand = _nearest_even(magnitude / power_of_two(exponent - fraction_bits))
        if significand == 1 << (fraction_bits + 1):
            significand >>= 1
            exponent += 1
        if exponent > maximum_exponent:
            return sign_field | (exponent_mask << fraction_bits)
        return (
            sign_field | ((exponent + bias) << fraction_bits) | (significand - (1 << fraction_bits))
        )
    significand = _nearest_even(magnitude / power_of_two(minimum_exponent - fraction_bits))
    if significand == 1 << fraction_bits:
        return sign_field | (1 << fraction_bits)
    return sign_field | significand


def encode_native_lossless(value: ExactValue, fmt: ConcreteFormat) -> int:
    bits = round_native(value, fmt)
    decoded = decode_native(bits, fmt)
    if value.kind == "nan":
        if decoded.kind != "nan":
            raise ValueError("NaN cannot be encoded")
    elif decoded != value:
        raise ValueError(f"{fmt.name} cannot represent this value exactly")
    return bits


def is_lossless(value: ExactValue, fmt: ConcreteFormat) -> bool:
    try:
        encode_native_lossless(value, fmt)
    except ValueError:
        return False
    return True


def combine_exact(values: tuple[ExactValue, ...]) -> ExactValue:
    if not values:
        raise ValueError("SUM requires at least one original contribution")
    if any(value.kind == "nan" for value in values):
        return ExactValue("nan", False)
    infinities = {value.sign for value in values if value.kind == "infinity"}
    if len(infinities) == 2:
        return ExactValue("nan", False)
    if infinities:
        return ExactValue("infinity", next(iter(infinities)))
    total = sum((value.value for value in values if value.value is not None), Fraction(0))
    if total == 0:
        negative_zero = all(value.kind == "zero" and value.sign for value in values)
        return ExactValue("zero", negative_zero, Fraction(0))
    return ExactValue("finite", total < 0, total)


def kulisch_element_bytes(width_bits: int) -> int:
    if not 8 <= width_bits <= 4096:
        raise ValueError("Kulisch width must be in 8..4096 bits")
    return 1 + (width_bits + 7) // 8


def encode_kulisch(value: ExactValue, width_bits: int) -> bytes:
    """One-byte state tag, followed by sign-extended little-endian integer."""
    payload_bytes = kulisch_element_bytes(width_bits) - 1
    if value.kind == "nan":
        return bytes([1]) + bytes(payload_bytes)
    if value.kind == "infinity":
        return bytes([3 if value.sign else 2]) + bytes(payload_bytes)
    if value.kind == "zero":
        return bytes([5 if value.sign else 4]) + bytes(payload_bytes)
    assert value.value is not None
    scaled = value.value / power_of_two(KULISCH_SCALE_EXPONENT)
    if scaled.denominator != 1:
        raise ValueError("finite value is not aligned to Kulisch scale")
    integer = scaled.numerator
    if not -(1 << (width_bits - 1)) <= integer < 1 << (width_bits - 1):
        raise ValueError("finite value overflows Kulisch width")
    return bytes([0]) + integer.to_bytes(payload_bytes, "little", signed=True)


def decode_kulisch(data: bytes, width_bits: int) -> ExactValue:
    if len(data) != kulisch_element_bytes(width_bits):
        raise ValueError("invalid Kulisch element width")
    tag, integer_bytes = data[0], data[1:]
    integer = int.from_bytes(integer_bytes, "little", signed=True)
    if tag == 0:
        if integer == 0 or not -(1 << (width_bits - 1)) <= integer < 1 << (width_bits - 1):
            raise ValueError("noncanonical Kulisch finite integer")
        if integer.to_bytes(len(integer_bytes), "little", signed=True) != integer_bytes:
            raise ValueError("noncanonical Kulisch sign padding")
        return ExactValue("finite", integer < 0, Fraction(integer) * power_of_two(-149))
    if integer != 0:
        raise ValueError("Kulisch special state requires zero payload")
    if tag == 1:
        return ExactValue("nan", False)
    if tag in (2, 3):
        return ExactValue("infinity", tag == 3)
    if tag in (4, 5):
        return ExactValue("zero", tag == 5, Fraction(0))
    raise ValueError("invalid Kulisch state tag")
