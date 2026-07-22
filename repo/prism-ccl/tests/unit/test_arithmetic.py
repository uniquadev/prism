from __future__ import annotations

import unittest
from fractions import Fraction

from prism_ccl.collectives.reference import (
    fp32_add_bits,
    fp32_sum_bits,
    kulisch_sum_bits,
    select_kulisch_width,
)
from prism_ccl.protocol.constants import WireFormat
from prism_ccl.protocol.numeric import canonicalize_bits, decode_bits, round_fraction


class ArithmeticReferenceTests(unittest.TestCase):
    def test_decode_and_round_known_values(self) -> None:
        self.assertEqual(decode_bits(0x3F800000, WireFormat.FP32).value, Fraction(1))
        self.assertEqual(decode_bits(0x00000001, WireFormat.FP32).value, Fraction(1, 1 << 149))
        self.assertEqual(round_fraction(Fraction(3, 2), WireFormat.FP32).bits, 0x3FC00000)
        self.assertEqual(round_fraction(Fraction(1, 1 << 149), WireFormat.FP32).bits, 0x00000001)

    def test_fp32_normative_special_cases(self) -> None:
        self.assertEqual(canonicalize_bits(0x7FA12345, WireFormat.FP32), 0x7FC00000)
        self.assertEqual(fp32_add_bits(0x7F800000, 0xFF800000), 0x7FC00000)
        self.assertEqual(fp32_add_bits(0x80000000, 0x80000000), 0x80000000)
        self.assertEqual(fp32_add_bits(0x80000000, 0x00000000), 0x00000000)

    def test_fp32_ordered_is_independent_of_arrival_permutation(self) -> None:
        contributions = [(0, 0x3F800000), (1, 0x33800000), (2, 0xBF800000)]
        expected = fp32_sum_bits(contributions, ordered=True)
        permuted = [contributions[2], contributions[0], contributions[1]]
        self.assertEqual(fp32_sum_bits(permuted, ordered=True), expected)
        self.assertNotEqual(fp32_sum_bits(permuted, ordered=False), expected)

    def test_kulisch_width_selection_and_fallback(self) -> None:
        exact = select_kulisch_width(WireFormat.FP32, 256, (64, 288, 320))
        self.assertEqual((exact.required_width, exact.selected_width), (286, 288))
        self.assertTrue(exact.sufficient)
        fallback = select_kulisch_width(WireFormat.FP32, 2048, (64, 288))
        self.assertEqual((fallback.required_width, fallback.selected_width), (289, 288))
        self.assertTrue(fallback.accumulation_inexact)

    def test_kulisch_is_order_independent_and_warning_is_sticky(self) -> None:
        values = [0x3F800000, 0x33800000, 0xBF800000]
        forward = kulisch_sum_bits(
            values,
            input_format=WireFormat.FP32,
            maximum_terms=3,
            compiled_widths=(288, 320),
        )
        reverse = kulisch_sum_bits(
            reversed(values),
            input_format=WireFormat.FP32,
            maximum_terms=3,
            compiled_widths=(288, 320),
        )
        self.assertEqual(forward.bits, reverse.bits)
        inherited = kulisch_sum_bits(
            values,
            input_format=WireFormat.FP32,
            maximum_terms=3,
            compiled_widths=(288, 320),
            upstream_inexact=(False, True, False),
        )
        self.assertTrue(inherited.accumulation_inexact)

    def test_kulisch_saturates_both_signs_and_sets_warning(self) -> None:
        positive = kulisch_sum_bits(
            [0x7F, 0x7F],
            input_format=WireFormat.INT8,
            maximum_terms=2,
            compiled_widths=(8,),
        )
        self.assertEqual(positive.bits, 0x42FE0000)
        self.assertTrue(positive.saturated)
        self.assertTrue(positive.accumulation_inexact)

        negative = kulisch_sum_bits(
            [0x80, 0x80],
            input_format=WireFormat.INT8,
            maximum_terms=2,
            compiled_widths=(8,),
        )
        self.assertEqual(negative.bits, 0xC3000000)
        self.assertTrue(negative.saturated)
        self.assertTrue(negative.accumulation_inexact)

    def test_kulisch_special_values_signed_zero_and_rounding(self) -> None:
        def reduce(values: list[int]):
            return kulisch_sum_bits(
                values,
                input_format=WireFormat.FP32,
                maximum_terms=len(values),
                compiled_widths=(320,),
            )

        self.assertEqual(reduce([0x7FA12345, 0x3F800000]).bits, 0x7FC00000)
        self.assertTrue(reduce([0x7F800000, 0xFF800000]).canonical_nan)
        self.assertEqual(reduce([0x80000000, 0x80000000]).bits, 0x80000000)
        self.assertEqual(reduce([0x80000000, 0x00000000]).bits, 0x00000000)
        tie = reduce([0x3F800000, 0x33800000])
        above_tie = reduce([0x3F800000, 0x33C00000])
        self.assertEqual(tie.bits, 0x3F800000)
        self.assertEqual(above_tie.bits, 0x3F800001)
        self.assertTrue(tie.rounding.inexact)


if __name__ == "__main__":
    unittest.main()
