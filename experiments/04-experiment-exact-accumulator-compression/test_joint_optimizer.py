"""Independent exhaustive oracle plus executable wire-payload checks."""

from functools import lru_cache
import random
import unittest

import joint_optimizer as joint

s = joint.study


def exhaustive(values, regime, budget, header=56):
    """Enumerate all interval formats/codecs and both packet decisions.

    Uses actual encoded payloads, no production cost formulas, Pareto pruning,
    minimum-interval shortcut, lookahead limit or production DP state arrays.
    """
    words, *_ = joint.prepare(values)
    options = {}
    for start in range(len(values)):
        for end in range(start + 1, len(values) + 1):
            sizes = []
            for f, name in enumerate(joint.FORMATS):
                if regime == "kulisch_compressed" and f != 4:
                    continue
                block = words[f][start:end]
                if any(word is None for word in block):
                    continue
                compressed = regime == "numbergroups_all_compressed" or (
                    f == 4 and regime != "numbergroups_only")
                for mode in joint.CODECS if compressed else ("raw",):
                    payload = s.encode_tile(values[start:end], mode) if f == 4 else joint.encode_native(block, mode)
                    sizes.append(4 + ((len(payload) + 3) // 4) * 4)
            options[start, end] = sizes

    @lru_cache(None)
    def visit(start, used):
        if start == len(values):
            return 0
        best = float("inf")
        for end in range(start + 1, len(values) + 1):
            for size in options[start, end]:
                if size <= budget:
                    best = min(best, header + size + visit(end, size))
                if used and used + size <= budget:
                    best = min(best, size + visit(end, used + size))
        return best
    return visit(0, 0)


class JointOptimizerTest(unittest.TestCase):
    def test_native_bit_patterns_round_trip(self):
        rng = random.Random(713)
        for width in (1, 2, 4):
            # All byte patterns, including signs, signed zero, float special
            # patterns; dataset eligibility remains finite exact values only.
            words = [bytes(width), bytes([255]) * width]
            words += [rng.randbytes(width) for _ in range(100)]
            for mode in joint.CODECS:
                payload = joint.encode_native(words, mode)
                self.assertEqual(joint.decode_native_payload(payload, len(words), width, mode), words)

    def test_reject_invalid_native_payload(self):
        for mode, payload in (("mask", b"\x10"), ("range", b"\x04\x02abcd"),
                              ("index", b"\x02\x00a\x00b"), ("raw", b"x")):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                joint.decode_native_payload(payload, 2, 4, mode)

    def test_exact_against_exhaustive_partition_format_codec_packet_oracle(self):
        rng = random.Random(17)
        pool = [0, 1 << 149, -(1 << 149), (1 << 149) + (1 << 125),
                1, 1 << 240, 127 << 149, 128 << 149, (1 << 149) + (1 << 126)]
        cases = [[0] * 6, [1, 1, 1 << 240, 1 << 240], pool[:6]]
        cases += [[rng.choice(pool) for _ in range(rng.randint(1, 7))] for _ in range(30)]
        for values in cases:
            for regime in joint.REGIMES:
                for budget in (16, 47, 68):
                    with self.subTest(values=values, regime=regime, budget=budget):
                        expected = exhaustive(values, regime, budget)
                        if expected == float("inf"):
                            with self.assertRaises(ValueError):
                                joint.optimize(values, regime, body_budget=budget)
                        else:
                            self.assertEqual(joint.optimize(values, regime, body_budget=budget)["frame_bytes"], expected)

    def test_all_interval_costs_match_actual_payloads(self):
        values = [0, 1, -1, 1 << 149, -(1 << 149), (1 << 319) - 1, -(1 << 319)]
        prepared = joint.prepare(values)
        words, valid, masks, ranges, indices = prepared
        for regime in joint.REGIMES:
            costs, _, _ = joint._group_options(valid, masks, ranges, indices,
                                              joint.REGIMES.index(regime), s.BODY_BUDGET)
            for start in range(len(values)):
                for end in range(start + 1, len(values) + 1):
                    # Check single-group costs explicitly, not segmentation.
                    sizes = []
                    for f in range(5):
                        if regime == "kulisch_compressed" and f != 4:
                            continue
                        if any(word is None for word in words[f][start:end]):
                            continue
                        compress = regime == "numbergroups_all_compressed" or (f == 4 and regime != "numbergroups_only")
                        for mode in joint.CODECS if compress else ("raw",):
                            payload = s.encode_tile(values[start:end], mode) if f == 4 else joint.encode_native(words[f][start:end], mode)
                            sizes.append(s.group_size(len(payload)))
                    self.assertEqual(int(costs[start, end]) * 4, min(sizes))

    def test_joint_choice_can_keep_native_representable_values_in_kulisch(self):
        values = [(1 << 149) + (1 << 125), 1 << 149] * 16
        old = s.study_chunk(values)
        optimized = joint.optimize(values, "numbergroups_kulisch_compressed")
        self.assertEqual(old["compressed_exact"]["frame_bytes"], 376)
        self.assertEqual(optimized["frame_bytes"], 136)
        self.assertEqual(optimized["groups"], 1)
        self.assertEqual(optimized["format_encoding_groups"], {"KULISCH/MASK": 1})

    def test_splitting_and_native_compression_can_each_help(self):
        values = [1] * 16 + [1 << 240] * 16
        uniform = joint.optimize(values, "kulisch_compressed")
        self.assertEqual(uniform["frame_bytes"], 112)
        self.assertEqual(uniform["groups"], 2)
        zeros = [0] * 4096
        compressed = joint.optimize(zeros, "numbergroups_all_compressed")
        self.assertEqual(compressed["frame_bytes"], 64)
        self.assertEqual(compressed["groups"], 1)
        self.assertEqual(compressed["format_encoding_groups"], {"INT8/MASK": 1})

    def test_candidate_supersets_never_worse(self):
        rng = random.Random(9)
        values = [rng.choice([0, 1, 1 << 149, -(1 << 150), (1 << 149) + (1 << 125)]) for _ in range(80)]
        results = {r: joint.optimize(values, r)["frame_bytes"] for r in joint.REGIMES}
        self.assertLessEqual(results["numbergroups_all_compressed"], results["numbergroups_kulisch_compressed"])
        self.assertLessEqual(results["numbergroups_kulisch_compressed"], results["numbergroups_only"])
        self.assertLessEqual(results["numbergroups_kulisch_compressed"], results["kulisch_compressed"])

    def test_raw_optimal_grouping_is_not_compressed_optimal_grouping(self):
        values = [(1 << 149) + (1 << 125), 1 << 149] * 16
        raw = joint.optimize(values, "numbergroups_only")
        frozen = joint.compress_fixed_groups(values, raw)
        compressed = joint.optimize(values, "numbergroups_all_compressed")
        self.assertGreater(frozen["frame_bytes"], compressed["frame_bytes"])

    def test_native_compression_strictly_improves_a_nonzero_case(self):
        # 0.5 is exactly FP16/BF16, but not INT8. Its native word has one
        # occupied byte, so MASK benefits without Kulisch's separate signs.
        values = [1 << 148] * 32
        raw = joint.optimize(values, "numbergroups_only")
        kulisch_codec = joint.optimize(values, "numbergroups_kulisch_compressed")
        all_codecs = joint.optimize(values, "numbergroups_all_compressed")
        self.assertEqual(raw["frame_bytes"], 124)
        self.assertEqual(kulisch_codec["frame_bytes"], 104)
        self.assertEqual(all_codecs["frame_bytes"], 96)
        self.assertEqual(all_codecs["format_encoding_groups"], {"FP16/MASK": 1})

    def test_constructed_thesis_example(self):
        result = joint.optimize([(1 << 149) + (1 << 125)] * 726, "numbergroups_all_compressed")
        self.assertEqual(result["frame_bytes"], 1676)
        self.assertEqual(result["packets"], 2)
        self.assertEqual(result["format_encoding_groups"], {"KULISCH/MASK": 2})

    def test_fp32_group_keeps_its_format_when_compressed(self):
        # 0.5 + 2^-24 is FP32-exact but neither FP16- nor BF16-exact.
        # Its FP32 pattern is 0x3f000001: MASK sends two occupied bytes.
        values = [(1 << 148) + (1 << 125)] * 32
        result = joint.optimize(values, "numbergroups_all_compressed")
        self.assertEqual(result["format_encoding_groups"], {"FP32/MASK": 1})
        self.assertEqual(result["frame_bytes"], 128)
        words = [bytes.fromhex("0100003f")] * 32
        encoded = joint.encode_native(words, "mask")
        self.assertEqual(len(encoded), 65)
        self.assertEqual(joint.decode_native_payload(encoded, 32, 4, "mask"), words)

    def test_raw_plan_matches_current_ccl_serialization(self):
        from prism_ccl.wire.data import DataPacket, NumberGroup
        rng = random.Random(3)
        values = [rng.choice([0, 1, (1 << 149) + (1 << 125), 1 << 149]) for _ in range(100)]
        result = joint.optimize(values, "numbergroups_only")
        prepared = joint.prepare(values)[0]
        frames = []
        for i, packet in enumerate(result["packet_plan"]):
            groups = []
            for group in packet["groups"]:
                start, count = group["first_element"], group["count"]
                fmt = getattr(s.ConcreteFormat, group["format"])
                if group["format"] == "KULISCH":
                    encoded = tuple(b"\0" + v.to_bytes(40, "little", signed=True) for v in values[start:start + count])
                else:
                    f = joint.FORMATS.index(group["format"])
                    encoded = tuple(int.from_bytes(w, "little") for w in prepared[f][start:start + count])
                groups.append(NumberGroup(fmt, encoded))
            wire = DataPacket(s.PacketClass.RESULT, s.OperationKey(1, 1, 0, 1, 0),
                              1, 2, 0, i, packet["first_element"], tuple(groups),
                              last=i == len(result["packet_plan"]) - 1)
            frames.append(s.encode_data_frame(wire, destination_mac=b"\0" * 6,
                                             source_mac=b"\0" * 6, mtu=s.MTU,
                                             kulisch_bits=s.KULISCH_BITS))
        self.assertEqual(sum(map(len, frames)), result["frame_bytes"])


if __name__ == "__main__":
    unittest.main()
