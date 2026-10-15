"""Exact, offline grouping/codec/packet optimizer; not a CCL or RTL change.

Run with: uv run --no-project --with numpy --with numba python joint_optimizer.py
Optimality is for the finite, ordered values and the codecs defined here, not
for all possible compression schemes. See JOINT_OPTIMIZER.md for the proof.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np
from numba import njit

import exact_accumulator_study as study
from prism_ccl.domain.numbers import decode_native, encode_native_lossless

FORMATS = ("INT8", "FP16", "BF16", "FP32", "KULISCH")
CODECS = ("raw", "range", "index", "mask")
REGIMES = (
    "numbergroups_only", "kulisch_compressed",
    "numbergroups_kulisch_compressed", "numbergroups_all_compressed",
)


def encode_native(words: list[bytes], mode: str) -> bytes:
    """Compress raw native bit patterns, including their sign/exponent bits.

    Unlike Kulisch sign/magnitude codecs, there is no separate native sign.
    RANGE/INDEX count bytes have zero high bits. MASK uses ceil(width/8) bytes.
    """
    if not words or len(words[0]) not in (1, 2, 4):
        raise ValueError("expected nonempty native words of width 1, 2 or 4")
    width = len(words[0])
    if any(len(word) != width for word in words):
        raise ValueError("mixed native widths")
    if mode == "raw":
        return b"".join(words)
    out = bytearray()
    if mode == "mask":
        positions = [i for i in range(width) if any(word[i] for word in words)]
        out.extend(sum(1 << i for i in positions).to_bytes((width + 7) // 8, "little"))
        for word in words:
            out.extend(word[i] for i in positions)
        return bytes(out)
    for word in words:
        positions = [i for i, byte in enumerate(word) if byte]
        if mode == "range":
            first = positions[0] if positions else 0
            count = positions[-1] - first + 1 if positions else 0
            out.extend((count, first))
            out.extend(word[first:first + count])
        elif mode == "index":
            out.append(len(positions))
            for i in positions:
                out.extend((i, word[i]))
        else:
            raise ValueError(mode)
    return bytes(out)


def decode_native_payload(payload: bytes, count: int, width: int, mode: str) -> list[bytes]:
    if count <= 0 or width not in (1, 2, 4):
        raise ValueError("invalid native geometry")
    if mode == "raw":
        if len(payload) != count * width:
            raise ValueError("raw length")
        return [payload[i * width:(i + 1) * width] for i in range(count)]
    cursor = 0
    positions = []
    if mode == "mask":
        mask_width = (width + 7) // 8
        if len(payload) < mask_width:
            raise ValueError("missing mask")
        mask = int.from_bytes(payload[:mask_width], "little")
        if mask >> width:
            raise ValueError("mask outside word")
        positions = [i for i in range(width) if mask >> i & 1]
        cursor = mask_width
    words = []
    for _ in range(count):
        word = bytearray(width)
        if mode == "mask":
            for position in positions:
                if cursor >= len(payload):
                    raise ValueError("truncated mask values")
                word[position] = payload[cursor]
                cursor += 1
        elif mode == "range":
            if cursor + 2 > len(payload):
                raise ValueError("truncated range header")
            size, first = payload[cursor:cursor + 2]
            cursor += 2
            if first >= width or first + size > width or cursor + size > len(payload):
                raise ValueError("invalid native range")
            word[first:first + size] = payload[cursor:cursor + size]
            cursor += size
        elif mode == "index":
            if cursor >= len(payload):
                raise ValueError("truncated index header")
            size = payload[cursor]
            cursor += 1
            if size > width or cursor + 2 * size > len(payload):
                raise ValueError("invalid native index size")
            previous = -1
            for _ in range(size):
                position, byte = payload[cursor:cursor + 2]
                cursor += 2
                if not previous < position < width:
                    raise ValueError("invalid native index position")
                previous = position
                word[position] = byte
        else:
            raise ValueError(mode)
        words.append(bytes(word))
    if cursor != len(payload):
        raise ValueError("trailing payload")
    return words


def prepare(values: list[int]):
    """All lossless native alternatives, not just the narrowest format."""
    if not values or len(values) > 4096:
        raise ValueError("one operation must contain 1..4096 values")
    if any(not -(1 << 319) <= value < (1 << 319) for value in values):
        raise ValueError("value outside signed Kulisch range")
    exact = study.exact_values(values)
    words: list[list[bytes | None]] = []
    valid = np.zeros((5, len(values)), dtype=np.bool_)
    masks = np.zeros((5, len(values)), dtype=np.uint64)
    ranges = np.zeros((5, len(values)), dtype=np.int16)
    indices = np.zeros((5, len(values)), dtype=np.int16)
    for f, name in enumerate(FORMATS):
        row = []
        for i, value in enumerate(values):
            if f == 4:
                raw = abs(value).to_bytes(40, "little")
            else:
                try:
                    bits = encode_native_lossless(exact[i], getattr(study.ConcreteFormat, name))
                except ValueError:
                    row.append(None)
                    continue
                raw = bits.to_bytes(study.WIDTH[name], "little")
            row.append(raw)
            valid[f, i] = True
            positions = [j for j, byte in enumerate(raw) if byte]
            masks[f, i] = sum(1 << j for j in positions)
            ranges[f, i] = 2 + (positions[-1] - positions[0] + 1 if positions else 0)
            indices[f, i] = 1 + 2 * len(positions)
        words.append(row)
    return words, valid, masks, ranges, indices


@njit(cache=True)
def _popcount(value):
    count = 0
    while value:
        value &= value - np.uint64(1)
        count += 1
    return count


@njit(cache=True)
def _group_options(valid, masks, ranges, indices, regime, budget):
    """Minimum aligned group cost for every contiguous interval that fits."""
    n = valid.shape[1]
    costs = np.zeros((n, n + 1), dtype=np.int16)
    formats = np.zeros((n, n + 1), dtype=np.int8)
    codecs = np.zeros((n, n + 1), dtype=np.int8)
    widths = (1, 2, 2, 4, 41)
    for start in range(n):
        live = np.ones(5, dtype=np.bool_)
        union = np.zeros(5, dtype=np.uint64)
        range_sum = np.zeros(5, dtype=np.int64)
        index_sum = np.zeros(5, dtype=np.int64)
        for end in range(start + 1, n + 1):
            count = end - start
            best = budget + 1
            best_f = 0
            best_c = 0
            for f in range(5):
                live[f] = live[f] and valid[f, end - 1]
                if not live[f] or (regime == 1 and f != 4):
                    continue
                union[f] |= masks[f, end - 1]
                range_sum[f] += ranges[f, end - 1]
                index_sum[f] += indices[f, end - 1]
                compressed = regime == 3 or (regime in (1, 2) and f == 4)
                for codec in range(4 if compressed else 1):
                    if codec == 0:
                        payload = count * widths[f]
                    elif codec == 1:
                        payload = range_sum[f]
                    elif codec == 2:
                        payload = index_sum[f]
                    else:
                        payload = (5 + (count + 7) // 8 if f == 4 else 1)
                        payload += count * _popcount(union[f])
                    size = 4 + ((payload + 3) // 4) * 4
                    if size < best:
                        best, best_f, best_c = size, f, codec
            if best > budget:
                # All candidate costs are nondecreasing as an interval grows;
                # invalid formats never become valid again.
                break
            costs[start, end] = best // 4
            formats[start, end] = best_f
            codecs[start, end] = best_c
    return costs, formats, codecs


@njit(cache=True)
def _shortest_path(costs, budget_units, header):
    """DAG state: output prefix and occupied bytes in the current packet.

    Retain only nondominated source labels: a cheaper/equal prefix with more
    free packet space can reproduce every continuation of a dominated label.
    No beam, lookahead limit, approximate pruning or solver tolerance is used.
    """
    n = costs.shape[0]
    inf = 1 << 60
    distance = np.full((n + 1, budget_units + 1), inf, dtype=np.int64)
    parent_i = np.full((n + 1, budget_units + 1), -1, dtype=np.int32)
    parent_r = np.full((n + 1, budget_units + 1), -1, dtype=np.int16)
    distance[0, 0] = 0
    frontier = np.empty(budget_units + 1, dtype=np.int16)
    states = 0
    for start in range(n):
        best = inf
        best_r = 0
        length = 0
        for r in range(budget_units + 1):
            if distance[start, r] < best:
                best = distance[start, r]
                best_r = r
                frontier[length] = r
                length += 1
        states += length
        if best == inf:
            continue
        for end in range(start + 1, n + 1):
            cost = costs[start, end]
            if cost == 0:
                break
            # Start a new packet, including one header even for the first.
            proposed = best + header + 4 * cost
            if proposed < distance[end, cost]:
                distance[end, cost] = proposed
                parent_i[end, cost] = start
                parent_r[end, cost] = -best_r - 1
            for k in range(length):
                r = frontier[k]
                if r == 0 or r + cost > budget_units:
                    continue
                proposed = distance[start, r] + 4 * cost
                if proposed < distance[end, r + cost]:
                    distance[end, r + cost] = proposed
                    parent_i[end, r + cost] = start
                    parent_r[end, r + cost] = r
    last = np.argmin(distance[n])
    return distance[n, last], last, parent_i, parent_r, states


def optimize(values: list[int], regime: str, *, body_budget: int = study.BODY_BUDGET,
             header: int = study.FRAME_OVERHEAD, prepared=None) -> dict:
    """Global minimum frame bytes for one ordered operation and codec regime."""
    if regime not in REGIMES or not 8 <= body_budget <= study.BODY_BUDGET or header < 0:
        raise ValueError("invalid optimization constraints")
    words, valid, masks, ranges, indices = prepared if prepared is not None else prepare(values)
    costs, formats, codecs = _group_options(
        valid, masks, ranges, indices, REGIMES.index(regime), body_budget)
    total, remaining, parent_i, parent_r, states = _shortest_path(costs, body_budget // 4, header)
    end = len(values)
    if parent_i[end, remaining] < 0:
        raise ValueError("no representation fits MTU")
    edges = []
    while end:
        start = int(parent_i[end, remaining])
        predecessor = int(parent_r[end, remaining])
        edges.append((start, end, int(formats[start, end]), int(codecs[start, end]), predecessor < 0))
        remaining = -predecessor - 1 if predecessor < 0 else predecessor
        end = start
    packets = []
    counts = Counter()
    payload_total = descriptor_total = padding_total = 0
    for start, end, f, codec, new_packet in reversed(edges):
        name, mode = FORMATS[f], CODECS[codec]
        if new_packet:
            packets.append({"first_element": start, "body_bytes": 0, "groups": []})
        if f == 4:
            payload = study.encode_tile(values[start:end], mode)
            if study.decode_tile(payload, end - start, mode) != values[start:end]:
                raise AssertionError("Kulisch round trip")
        else:
            raw_words = words[f][start:end]
            payload = encode_native(raw_words, mode)
            decoded = decode_native_payload(payload, end - start, study.WIDTH[name], mode)
            if decoded != raw_words:
                raise AssertionError("native bit-pattern round trip")
            for i, word in enumerate(decoded, start):
                value = decode_native(int.from_bytes(word, "little"), getattr(study.ConcreteFormat, name))
                if value.value != study.exact_fraction(values[i]):
                    raise AssertionError("native numerical exactness")
        padded = study.group_size(len(payload))
        if padded != int(costs[start, end]) * 4:
            raise AssertionError("analytic cost differs from actual encoded payload")
        packets[-1]["groups"].append({"first_element": start, "count": end - start,
                                      "format": name, "encoding": mode.upper(),
                                      "payload_bytes": len(payload), "group_bytes": padded})
        packets[-1]["body_bytes"] += padded
        counts[f"{name}/{mode.upper()}"] += 1
        payload_total += len(payload)
        descriptor_total += 4
        padding_total += padded - 4 - len(payload)
    for packet in packets:
        if not packet["body_bytes"] <= body_budget or len(packet["groups"]) > 255:
            raise AssertionError("packet limit")
    if payload_total + descriptor_total + padding_total + header * len(packets) != total:
        raise AssertionError("frame total reconciliation")
    return {"frame_bytes": int(total), "packets": len(packets),
            "payload_bytes": payload_total, "descriptor_bytes": descriptor_total,
            "padding_bytes": padding_total, "header_bytes": header * len(packets),
            "groups": sum(counts.values()), "format_encoding_groups": dict(sorted(counts.items())),
            "pareto_source_states": int(states), "packet_plan": packets}


def compress_fixed_groups(values: list[int], raw_plan: dict, prepared=None) -> dict:
    """Diagnostic: compress the raw-optimal grouping without changing formats.

    Repacketization may move a whole group, but does not split/merge groups.
    This is deliberately not the joint optimizer.
    """
    words, *_ = prepared if prepared is not None else prepare(values)
    accounting = []
    for packet in raw_plan["packet_plan"]:
        for group in packet["groups"]:
            start, count = group["first_element"], group["count"]
            f = FORMATS.index(group["format"])
            candidates = []
            for mode in CODECS:
                payload = (study.encode_tile(values[start:start + count], mode) if f == 4
                           else encode_native(words[f][start:start + count], mode))
                candidates.append((study.group_size(len(payload)), mode, len(payload)))
            _, mode, size = min(candidates)
            accounting.append((f"{FORMATS[f]}/{mode}", size))
    total, packets = study.packet_bytes(accounting, merge_equal=False)
    return {"frame_bytes": total, "packets": packets, "groups": len(accounting)}


def evaluate(label, partials, metadata):
    values = study.scaled_exact(partials)
    output = {"label": label, "n": len(values), "metadata": metadata, "methods": {}}
    chunks = [values[i:i + 4096] for i in range(0, len(values), 4096)]
    prepared = [prepare(chunk) for chunk in chunks]
    raw_plans = None
    for regime in REGIMES:
        started = time.perf_counter()
        plans = [optimize(chunk, regime, prepared=p) for chunk, p in zip(chunks, prepared)]
        if regime == "numbergroups_only":
            raw_plans = plans
        result = {key: sum(p[key] for p in plans) for key in (
            "frame_bytes", "packets", "payload_bytes", "descriptor_bytes", "padding_bytes",
            "header_bytes", "groups", "pareto_source_states")}
        choices = Counter()
        for p in plans:
            choices.update(p["format_encoding_groups"])
        result["format_encoding_groups"] = dict(sorted(choices.items()))
        result["operations"] = [{"first_element": i * 4096, "n": len(chunk),
                                 "packet_plan": p["packet_plan"]}
                                for i, (chunk, p) in enumerate(zip(chunks, plans))]
        result["optimizer_seconds"] = round(time.perf_counter() - started, 3)
        output["methods"][regime] = result
        print(label, regime, result["frame_bytes"], "bytes;", result["groups"], "groups;",
              result["optimizer_seconds"], "s", flush=True)
    m = output["methods"]
    assert m["numbergroups_all_compressed"]["frame_bytes"] <= m["numbergroups_kulisch_compressed"]["frame_bytes"]
    assert m["numbergroups_kulisch_compressed"]["frame_bytes"] <= min(
        m["numbergroups_only"]["frame_bytes"], m["kulisch_compressed"]["frame_bytes"])
    fixed = [compress_fixed_groups(chunk, plan, prep)
             for chunk, plan, prep in zip(chunks, raw_plans, prepared)]
    output["raw_optimal_grouping_then_compression"] = {
        key: sum(p[key] for p in fixed) for key in ("frame_bytes", "packets", "groups")}
    assert m["numbergroups_all_compressed"]["frame_bytes"] <= output["raw_optimal_grouping_then_compression"]["frame_bytes"]
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=study.REPOSITORY / "build/cache/exact-accumulator-sources")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("joint_results.json"))
    args = parser.parse_args()
    paths = study.checked_sources(args.cache, False)
    workloads = [study.cavity_kernel(paths["cavity01.tar.gz"]), study.structural_kernel(paths["bcsstk16"])]
    workloads += study.pythia_kernels(paths["pythia-14m-model.safetensors"])
    cases = [evaluate(*workload) for workload in workloads]
    legacy = json.loads(Path(__file__).with_name("results.json").read_text(encoding="utf-8"))
    assert len(cases) == len(legacy["cases"]) - 1
    for result, old in zip(cases, legacy["cases"][1:]):
        assert result["label"] == old["label"] and result["n"] == old["n"]
        for new, previous in (("numbergroups_only", "auto"), ("kulisch_compressed", "compressed_uniform_kulisch"),
                              ("numbergroups_kulisch_compressed", "compressed_exact")):
            assert result["methods"][new]["frame_bytes"] <= old[previous]["frame_bytes"]
        result["current_baselines"] = {k: old[k] for k in ("auto", "compressed_uniform_kulisch", "compressed_exact")}
    report = {"scope": "exact software minimum, ordered finite values, specified byte codecs; not RTL or measured speed",
              "objective": "RESULT Ethernet frame bytes, including headers/descriptors/padding, excluding FCS/preamble/IFG",
              "constraints": {"mtu": study.MTU, "frame_header_bytes": study.FRAME_OVERHEAD,
                              "body_budget_bytes": study.BODY_BUDGET, "operation_max_values": 4096,
                              "preserve_element_order": True, "reordering": False,
                              "global_across_operations": False},
              "algorithm": "exact Pareto-pruned shortest path over prefix and current packet occupancy",
              "native_compression": "lossless native bit-pattern RAW/RANGE/INDEX/MASK; no separate sign",
              "sources": {name: {"url": url, "sha256": digest} for name, (url, digest) in study.SOURCES.items()},
              "cases": cases,
              "constructed_case": {
                  "label": "Constructed / 1 + 2^-24", "n": 726,
                  "uniform_kulisch": legacy["cases"][0]["uniform_kulisch"],
                  "fixed_fp32": legacy["cases"][0]["fixed_fp32"],
                  "optimized": optimize([(1 << 149) + (1 << 125)] * 726,
                                        "numbergroups_all_compressed")}}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
