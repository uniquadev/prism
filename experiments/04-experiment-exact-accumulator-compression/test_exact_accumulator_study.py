"""Deterministic checks for the proposed codec and frame accounting."""

from __future__ import annotations

import importlib.util
import json
import math
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("exact_accumulator_study.py")
SPEC = importlib.util.spec_from_file_location("exact_accumulator_study", SOURCE)
assert SPEC and SPEC.loader
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


class ExactAccumulatorStudyTest(unittest.TestCase):
    def test_uniform_compression_uses_no_native_format_selection(self) -> None:
        # All zeros fit native INT8, but this baseline must retain Kulisch.
        result = study.study_chunk([0] * 36)
        self.assertEqual(result["source_group_counts"], {"uniform_kulisch": 2, "auto": 1})
        # First 35 values: MASK has 5 mask + 5 sign bytes, padded group = 16.
        # Final zero: INDEX has 1 byte, padded group = 8. One 56-byte header.
        self.assertEqual(result["compressed_uniform_kulisch"], {"frame_bytes": 80, "packets": 1})
        self.assertEqual(result["uniform_selected_encoding_groups"],
                         {"RAW": 0, "RANGE": 0, "INDEX": 1, "MASK": 1})

    def test_uniform_raw_only_matches_actual_ccl_frames(self) -> None:
        values = [0, 1, -1, (1 << 319) - 1, -(1 << 319)] * 15
        _, expected, packets = study.ccl_packets(study.exact_values(values), "KULISCH")
        actual, modes = study.adaptive_account(values, packets, (study.KulischEncoding.RAW,))
        self.assertEqual(actual, expected)
        self.assertEqual(modes["RAW"], expected[1])
        self.assertTrue(all(len(p.groups) == 1 for p in packets))
        self.assertTrue(all(len(p.groups[0].values) <= 35 for p in packets))

    def test_range_and_index_sign_count_precedes_position(self) -> None:
        value = (0x81 << 8) | (0x04 << 32)
        cases = (
            ("range", value, bytes([4, 1, 0x81, 0, 0, 0x04])),
            ("range", -value, bytes([0x44, 1, 0x81, 0, 0, 0x04])),
            ("range", 0, bytes([0, 0])),
            ("index", value, bytes([2, 1, 0x81, 4, 0x04])),
            ("index", -value, bytes([0x42, 1, 0x81, 4, 0x04])),
            ("index", 0, bytes([0])),
        )
        for mode, number, payload in cases:
            with self.subTest(mode=mode, value=number):
                self.assertEqual(study.encode_tile([number], mode), payload)
                self.assertEqual(study.decode_tile(payload, 1, mode), [number])

    def test_range_sign_count_covers_full_span(self) -> None:
        value = (1 << 312) | 1
        payload = bytes([0x68, 0, 1]) + bytes(38) + bytes([1])
        self.assertEqual(study.encode_tile([-value], "range"), payload)
        self.assertEqual(study.decode_tile(payload, 1, "range"), [-value])

    def test_all_proposed_modes_round_trip_signed_and_sparse(self) -> None:
        values = [0, 1, -1, (1 << 149) + (1 << 125),
                  -((1 << 149) + (1 << 125)), (1 << 319) - 1,
                  -(1 << 319)]
        for mode in ("raw", "range", "index", "mask"):
            with self.subTest(mode=mode):
                payload = study.encode_tile(values, mode)
                self.assertEqual(study.decode_tile(payload, len(values), mode), values)

    def test_fp16_subnormal_tie_and_packet_accounting(self) -> None:
        epsilon = math.ldexp(1, -24)
        self.assertEqual(study.f32(1.0 + epsilon), 1.0)
        self.assertEqual(study.f32(epsilon), epsilon)
        result = study.synthetic_case()
        self.assertEqual(result["n"], 726)
        self.assertEqual(result["exact_not_fp32"], 726)
        self.assertEqual(result["uniform_kulisch"], {"frame_bytes": 31048, "packets": 21})
        self.assertEqual(result["auto"], result["uniform_kulisch"])
        self.assertEqual(result["compressed_exact"], {"frame_bytes": 1860, "packets": 2})
        self.assertEqual(result["compressed_uniform_kulisch"], result["compressed_exact"])
        self.assertEqual(result["fixed_fp32"], {"frame_bytes": 3024, "packets": 2})
        self.assertEqual(result["selected_encoding_groups"],
                         {"RAW": 0, "RANGE": 0, "INDEX": 0, "MASK": 21})

    def test_proposed_numbergroup_keeps_format_and_encoding_separate(self) -> None:
        self.assertEqual(
            {encoding.name: int(encoding) for encoding in study.KulischEncoding},
            {"RAW": 0, "RANGE": 1, "INDEX": 2, "MASK": 3},
        )
        group = study.ProposedNumberGroup(
            study.ConcreteFormat.KULISCH, study.KulischEncoding.MASK, 4, 14
        )
        self.assertEqual(group.format, study.ConcreteFormat.KULISCH)
        self.assertEqual(group.encoding, study.KulischEncoding.MASK)
        self.assertEqual(group.count, 4)

    def test_input_hash_validation_rejects_modification(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as folder:
            for name in study.SOURCES:
                (Path(folder) / name).write_bytes(b"not official data")
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                study.checked_sources(Path(folder), download=False)

    def test_exact_sum_and_current_auto_agree_with_ccl(self) -> None:
        partials = [[1.0, math.ldexp(1, -24), 0.0, 0.0],
                    [1.0, -1.0, 0.0, 0.0],
                    [0.5, 0.25, 0.0, 0.0]]
        values = study.scaled_exact(partials)
        self.assertEqual(values[0], (1 << 149) + (1 << 125))
        self.assertEqual(values[1], 0)
        account, counts, _ = study.auto_account(values)
        self.assertEqual(sum(counts.values()), 3)
        self.assertEqual(account[1], 1)

    def test_numbergroup_limit_is_respected(self) -> None:
        total, packets = study.packet_bytes([(f"mode{i}", 0) for i in range(256)])
        self.assertEqual(packets, 2)
        self.assertEqual(total, 256 * 4 + 2 * study.FRAME_OVERHEAD)

    def test_saved_report_records_group_encoding_choices(self) -> None:
        report = json.loads(SOURCE.with_name("results.json").read_text(encoding="utf-8"))
        self.assertEqual(report["proposed_numbergroup"]["format"], "KULISCH")
        self.assertEqual(report["proposed_numbergroup"]["encoding_ids"],
                         {"RAW": 0, "RANGE": 1, "INDEX": 2, "MASK": 3})
        choices = {case["label"]: case["selected_encoding_groups"]
                   for case in report["cases"]}
        self.assertEqual(choices["Constructed / 1 + 2^-24"],
                         {"RAW": 0, "RANGE": 0, "INDEX": 0, "MASK": 21})
        self.assertEqual(choices["CFD / cavity01"],
                         {"RAW": 0, "RANGE": 41, "INDEX": 2, "MASK": 12})
        self.assertEqual(choices["HPC / bcsstk16"],
                         {"RAW": 0, "RANGE": 19, "INDEX": 0, "MASK": 7})
        self.assertEqual(choices["LLM / QKV"],
                         {"RAW": 0, "RANGE": 43, "INDEX": 0, "MASK": 44})
        self.assertEqual(choices["LLM / MLP"],
                         {"RAW": 0, "RANGE": 59, "INDEX": 1, "MASK": 53})


if __name__ == "__main__":
    unittest.main()
