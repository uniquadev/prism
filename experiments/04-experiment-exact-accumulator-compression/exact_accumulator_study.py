"""Reproducible, offline accounting for a *proposed* exact RESULT codec.

The kernels run locally and produce FP32 rank partials.  No PRISM hardware or
MPI run is claimed.  Sources are pinned and verified before any calculation.
Only finite results are included; the existing 41-byte Kulisch wire value is
the fallback for exceptional values in a future protocol design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import tarfile
import urllib.request
from enum import IntEnum
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "repo/prism-ccl/src"))
from prism_ccl.application.packing import fixed_groups, packetize, select_auto_groups  # noqa: E402
from prism_ccl.domain.model import ConcreteFormat, OperationKey  # noqa: E402
from prism_ccl.domain.numbers import ExactValue  # noqa: E402
from prism_ccl.wire.data import PacketClass, encode_data_frame  # noqa: E402


SOURCES = {
    "cavity01.tar.gz": (
        "https://sparse.tamu.edu/MM/DRIVCAV/cavity01.tar.gz",
        "B1481371E07E7997910216F3C395BB7898F96243DF8F16A5A46174410B19F41D",
    ),
    "bcsstk16": (
        "https://raw.githubusercontent.com/DrTimothyAldenDavis/SuiteSparse/"
        "e202a5bcef55f5a780c26830ebd6ff13af193baf/CXSparse/Matrix/bcsstk16",
        "44FF2C8750B6134A6A22874B0DDE9F37463FAAD954A662E047B9E6ED0F21EDB5",
    ),
    "pythia-14m-model.safetensors": (
        "https://huggingface.co/EleutherAI/pythia-14m/resolve/"
        "cf967c0a9a04383db6f7b1108d86b2962634b4ac/model.safetensors",
        "116A02532DB461F91386A5B20F942FF2C8D4DE7341E21B55CAAFC3D7B25F49A1",
    ),
}

RANKS = 4
MTU = 1500
FRAME_OVERHEAD = 14 + 2 + 40  # Ethernet + PRISM control + RESULT header
BODY_BUDGET = MTU - 2 - 40
KULISCH_BITS = 320
KULISCH_SCALE = 149
WIDTH = {"INT8": 1, "FP16": 2, "BF16": 2, "FP32": 4, "KULISCH": 41}


class KulischEncoding(IntEnum):
    """Proposed descriptor-byte values; only RAW exists on the current wire."""

    RAW = 0
    RANGE = 1
    INDEX = 2
    MASK = 3


class ProposedNumberGroup(NamedTuple):
    """Accounting model, not a packet accepted by today's CCL or RTL."""

    format: ConcreteFormat
    encoding: KulischEncoding | None
    count: int
    payload_bytes: int


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def checked_sources(cache: Path, download: bool) -> dict[str, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, (url, expected) in SOURCES.items():
        path = cache / name
        if not path.exists():
            if not download:
                raise FileNotFoundError(f"{path} missing; rerun with --download")
            with urllib.request.urlopen(url, timeout=60) as response, path.open("wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest().upper()
        if digest != expected:
            raise ValueError(f"source hash mismatch: {name}: {digest}")
        paths[name] = path
    return paths


def matrix_market_lines(content: bytes) -> tuple[list[str], list[str]]:
    lines = content.decode("ascii").splitlines()
    header = lines[0].split()
    if header[:2] != ["%%MatrixMarket", "matrix"] or header[4] != "general":
        raise ValueError("unsupported Matrix Market type")
    data = [line for line in lines[1:] if line and not line.startswith("%")]
    return header, data


def cavity_kernel(archive_path: Path) -> tuple[str, list[list[float]], dict]:
    with tarfile.open(archive_path, "r:gz") as archive:
        def member(name: str) -> bytes:
            entry = archive.extractfile(f"cavity01/{name}")
            if entry is None:
                raise ValueError(f"missing {name}")
            return entry.read()

        header, lines = matrix_market_lines(member("cavity01.mtx"))
        x_header, x_lines = matrix_market_lines(member("cavity01_x.mtx"))
    if header[2:4] != ["coordinate", "real"] or x_header[2:4] != ["array", "real"]:
        raise ValueError("unexpected cavity01 array formats")
    nrow, ncol, stored = map(int, lines[0].split())
    nx, one = map(int, x_lines[0].split())
    if (nrow, ncol, stored, nx, one) != (317, 317, 7327, 317, 1):
        raise ValueError("cavity01 dimensions or entry count changed")
    x = [f32(float(v)) for v in x_lines[1:]]
    if len(x) != nx or len(lines) - 1 != stored:
        raise ValueError("cavity01 data length mismatch")
    rows: list[list[tuple[int, float]]] = [[] for _ in range(nrow)]
    nonzero = 0
    for line in lines[1:]:
        i, j, a = line.split()
        coefficient = f32(float(a))
        rows[int(i) - 1].append((int(j) - 1, coefficient))
        nonzero += coefficient != 0
    if nonzero != 7280:
        raise ValueError("cavity01 nonzero count changed")
    return "CFD / cavity01", spmv_partials(rows, x), {
        "matrix": "DRIVCAV/cavity01", "outputs": nrow, "stored_entries": stored,
        "nonzeros": nonzero, "vector": "official cavity01_x.mtx", "kernel": "FP32 SpMV",
    }


def structural_kernel(path: Path) -> tuple[str, list[list[float]], dict]:
    rows: list[list[tuple[int, float]]] = [[] for _ in range(4884)]
    stored = 0
    diagonal = 0
    for line in path.read_text(encoding="ascii").splitlines():
        i_str, j_str, v_str = line.split()
        i, j, value = int(i_str), int(j_str), f32(float(v_str))
        if not (0 <= i < 4884 and 0 <= j < 4884):
            raise ValueError("bcsstk16 index out of range")
        rows[i].append((j, value))
        if i != j:
            rows[j].append((i, value))
        else:
            diagonal += 1
        stored += 1
    if (stored, diagonal) != (147631, 4884):
        raise ValueError("bcsstk16 shape or triangular entry count changed")
    x = [1.0] * 4884
    return "HPC / bcsstk16", spmv_partials(rows, x), {
        "matrix": "HB/bcsstk16", "outputs": 4884, "stored_entries": stored,
        "full_entries": 2 * stored - diagonal, "vector": "benchmark x[j] = 1 (synthetic)",
        "kernel": "FP32 symmetric SpMV",
    }


def spmv_partials(rows: list[list[tuple[int, float]]], x: list[float]) -> list[list[float]]:
    ncol = len(x)
    output = []
    for row in rows:
        rank_values = [0.0] * RANKS
        for j, a in sorted(row):
            rank = min(RANKS - 1, j * RANKS // ncol)
            rank_values[rank] = f32(rank_values[rank] + f32(a * x[j]))
        output.append(rank_values)
    return output


def pythia_kernels(path: Path) -> list[tuple[str, list[list[float]], dict]]:
    with path.open("rb") as stream:
        header_size = struct.unpack("<Q", stream.read(8))[0]
        header = json.loads(stream.read(header_size))
        data_start = 8 + header_size

        def tensor(name: str) -> list[list[float]]:
            record = header[name]
            shape = record["shape"]
            begin, end = record["data_offsets"]
            if record["dtype"] != "F16" or len(shape) != 2 or end - begin != math.prod(shape) * 2:
                raise ValueError(f"unexpected tensor layout: {name}")
            stream.seek(data_start + begin)
            raw = stream.read(end - begin)
            if len(raw) != end - begin:
                raise ValueError(f"truncated tensor: {name}")
            return [list(struct.unpack_from(f"<{shape[1]}e", raw, row * shape[1] * 2))
                    for row in range(shape[0])]

        embedding = tensor("gpt_neox.embed_in.weight")
        if len(embedding) != 50304 or len(embedding[0]) != 128:
            raise ValueError("Pythia embedding shape changed")
        x = embedding[42]  # pinned token ID; one actual model-weight row
        results = []
        for label, name, output_size in (
            ("LLM / QKV", "gpt_neox.layers.0.attention.query_key_value.weight", 384),
            ("LLM / MLP", "gpt_neox.layers.0.mlp.dense_h_to_4h.weight", 512),
        ):
            weight = tensor(name)
            if len(weight) != output_size or any(len(row) != 128 for row in weight):
                raise ValueError(f"Pythia projection shape changed: {name}")
            partials = []
            for row in weight:
                rank_values = [0.0] * RANKS
                for rank in range(RANKS):
                    for j in range(rank * 32, (rank + 1) * 32):
                        rank_values[rank] = f32(rank_values[rank] + f32(row[j] * x[j]))
                partials.append(rank_values)
            results.append((label, partials, {
                "model": "EleutherAI/pythia-14m", "outputs": output_size,
                "input": "embedding row for token ID 42", "layer": name,
                "kernel": "FP32 matrix-vector projection of FP16 weights",
            }))
        return results


def scaled_exact(partials: list[list[float]]) -> list[int]:
    values = []
    for rank_values in partials:
        if len(rank_values) != RANKS or not all(math.isfinite(v) for v in rank_values):
            raise ValueError("expected four finite FP32 rank partials")
        scaled = 0
        for value in rank_values:
            numerator, denominator = value.as_integer_ratio()
            term, remainder = divmod(numerator << KULISCH_SCALE, denominator)
            if remainder:
                raise AssertionError("FP32 partial did not align with Kulisch scale")
            scaled += term
        if not -(1 << 319) <= scaled < (1 << 319):
            raise OverflowError("result exceeds 320-bit Kulisch range")
        values.append(scaled)
    return values


def exact_fraction(scaled: int) -> Fraction:
    return Fraction(scaled, 1 << KULISCH_SCALE)


def auto_format(scaled: int) -> str:
    value = exact_fraction(scaled)
    if value.denominator == 1 and -128 <= value.numerator <= 127:
        return "INT8"
    approximate = float(value)
    try:
        half = struct.unpack("<e", struct.pack("<e", approximate))[0]
        if Fraction.from_float(half) == value:
            return "FP16"
    except (OverflowError, struct.error):
        pass
    try:
        single = f32(approximate)
    except (OverflowError, struct.error):
        return "KULISCH"
    if Fraction.from_float(single) == value:
        bits = struct.unpack("<I", struct.pack("<f", single))[0]
        if bits & 0xFFFF == 0:
            return "BF16"
        return "FP32"
    return "KULISCH"


def exact_values(values: list[int]) -> list[ExactValue]:
    return [ExactValue("zero" if v == 0 else "finite", v < 0, exact_fraction(v))
            for v in values]


def ccl_packets(values: list[ExactValue], policy: str):
    if policy == "AUTO":
        groups = tuple(select_auto_groups(values, KULISCH_BITS, MTU))
    else:
        groups = tuple(fixed_groups(values, ConcreteFormat.KULISCH, KULISCH_BITS))
    operation = OperationKey(1, 1, 0, 1, 0)
    packets = tuple(packetize(groups, packet_class=PacketClass.RESULT,
                              operation=operation, source_endpoint=1,
                              destination_endpoint=2, stream_id=0,
                              first_element=0, mtu=MTU, kulisch_bits=KULISCH_BITS))
    frames = [encode_data_frame(packet, destination_mac=b"\0" * 6,
                                source_mac=b"\0" * 6, mtu=MTU,
                                kulisch_bits=KULISCH_BITS) for packet in packets]
    return groups, (sum(map(len, frames)), len(frames)), packets


def group_size(payload_size: int) -> int:
    return 4 + payload_size + (-payload_size) % 4


def packet_bytes(groups: list[tuple[str, int]], merge_equal: bool = False) -> tuple[int, int]:
    """Pack groups without splitting; baseline elements are pre-split into singles."""
    packets = 0
    body = 0
    total_body = 0
    previous_format = None
    previous_payload = 0
    group_count = 0
    for fmt, payload in groups:
        if payload < 0:
            raise ValueError("negative payload")
        merge = merge_equal and fmt in WIDTH and fmt == previous_format
        if merge:
            delta = group_size(previous_payload + payload) - group_size(previous_payload)
        else:
            delta = group_size(payload)
        if body + delta > BODY_BUDGET or (not merge and group_count == 255):
            if not body:
                raise ValueError("group exceeds MTU body")
            packets += 1
            total_body += body
            body = 0
            previous_format = None
            previous_payload = 0
            group_count = 0
            delta = group_size(payload)
        body += delta
        if merge_equal and fmt in WIDTH and fmt == previous_format:
            previous_payload += payload
        else:
            previous_format = fmt
            previous_payload = payload
            group_count += 1
    if body:
        packets += 1
        total_body += body
    return packets * FRAME_OVERHEAD + total_body, packets


def fixed_account(values: list[int], format_name: str) -> tuple[int, int]:
    return packet_bytes([(format_name, WIDTH[format_name])] * len(values), merge_equal=True)


def auto_account(values: list[int]):
    _, reference, packets = ccl_packets(exact_values(values), "AUTO")
    counts = {name: 0 for name in WIDTH}
    packed_groups = []
    for packet in packets:
        for group in packet.groups:
            name = group.format.name
            count = len(group.values)
            counts[name] += count
            packed_groups.extend([(name, WIDTH[name])] * count)
    modeled = packet_bytes(packed_groups, merge_equal=True)
    if modeled != reference:
        raise AssertionError(f"current AUTO accounting mismatch: {modeled} vs {reference}")
    return reference, counts, packets


def active_bytes(value: int) -> list[tuple[int, int]]:
    magnitude = abs(value)
    if magnitude >= 1 << KULISCH_BITS:
        raise ValueError("magnitude too large")
    return [(i, (magnitude >> (8 * i)) & 255) for i in range(40)
            if (magnitude >> (8 * i)) & 255]


def encode_tile(values: list[int], mode: str) -> bytes:
    """Executable prototype for the four lossless candidate group payloads.

    RANGE and INDEX start each value with a shared sign/count byte:
    bit 6 carries the sign, bits 5:0 carry the size, and
    bit 7 is zero. RANGE follows it with one start position; INDEX
    follows it with a position/content pair for each nonzero byte.
    The size is rs (range size in bytes) for RANGE and ps (positions
    size, counting nonzero byte positions) for INDEX.
    """
    if mode == "raw":
        return b"".join(b"\0" + v.to_bytes(40, "little", signed=True) for v in values)
    if mode == "index":
        result = bytearray()
        for value in values:
            parts = active_bytes(value)
            result.append((0x40 if value < 0 else 0) | len(parts))
            for position, byte in parts:
                result.extend((position, byte))
        return bytes(result)
    if mode == "range":
        result = bytearray()
        for value in values:
            parts = active_bytes(value)
            first = parts[0][0] if parts else 0
            range_size = parts[-1][0] - first + 1 if parts else 0
            result.extend(((0x40 if value < 0 else 0) | range_size, first))
            for position in range(first, first + range_size):
                result.append((abs(value) >> (8 * position)) & 255)
        return bytes(result)
    if mode == "mask":
        positions = sorted({position for value in values for position, _ in active_bytes(value)})
        mask = sum(1 << position for position in positions)
        signs = bytearray((len(values) + 7) // 8)
        for i, value in enumerate(values):
            if value < 0:
                signs[i // 8] |= 1 << (i % 8)
        result = bytearray(mask.to_bytes(5, "little") + signs)
        for value in values:
            for position in positions:
                result.append((abs(value) >> (8 * position)) & 255)
        return bytes(result)
    raise ValueError(mode)


def decode_tile(payload: bytes, count: int, mode: str) -> list[int]:
    if mode == "raw":
        if len(payload) != 41 * count:
            raise ValueError("raw payload length")
        return [int.from_bytes(payload[i * 41 + 1:i * 41 + 41], "little", signed=True)
                for i in range(count)]
    if mode == "mask":
        mask = int.from_bytes(payload[:5], "little")
        positions = [i for i in range(40) if mask >> i & 1]
        sign_width = (count + 7) // 8
        signs = payload[5:5 + sign_width]
        data = payload[5 + sign_width:]
        if len(data) != count * len(positions):
            raise ValueError("mask payload length")
        values = []
        cursor = 0
        for i in range(count):
            value = 0
            for position in positions:
                value |= data[cursor] << (8 * position)
                cursor += 1
            values.append(-value if signs[i // 8] >> (i % 8) & 1 else value)
        return values
    values = []
    cursor = 0
    for _ in range(count):
        if mode == "index":
            meta = payload[cursor]
            cursor += 1
            positions_size = meta & 0x3F
            value = 0
            for _ in range(positions_size):
                position, byte = payload[cursor:cursor + 2]
                cursor += 2
                value |= byte << (8 * position)
            negative = bool(meta & 0x40)
        elif mode == "range":
            meta, first = payload[cursor:cursor + 2]
            cursor += 2
            range_size = meta & 0x3F
            value = int.from_bytes(payload[cursor:cursor + range_size], "little") << (8 * first)
            cursor += range_size
            negative = bool(meta & 0x40)
        else:
            raise ValueError(mode)
        values.append(-value if negative else value)
    if cursor != len(payload):
        raise ValueError("trailing payload")
    return values


def adaptive_account(values: list[int], source_packets,
                          allowed: tuple[KulischEncoding, ...]
                          ) -> tuple[tuple[int, int], dict[str, int]]:
    """Re-encode Kulisch groups from AUTO or uniform output, then repacketize.

    Every chosen group is no larger than the original. Retaining their order
    therefore cannot increase body bytes or the number of required packets.
    """
    groups: list[ProposedNumberGroup] = []
    modes = {encoding.name: 0 for encoding in KulischEncoding}
    position = 0
    for packet in source_packets:
        if position != packet.first_element:
            raise AssertionError("source packet interval mismatch")
        for group in packet.groups:
            count = len(group.values)
            if group.format != ConcreteFormat.KULISCH:
                groups.append(ProposedNumberGroup(
                    group.format, None, count, count * WIDTH[group.format.name]
                ))
            else:
                tile = values[position:position + count]
                candidates = []
                for encoding in allowed:
                    mode = encoding.name.lower()
                    payload = encode_tile(tile, mode)
                    candidates.append((group_size(len(payload)), mode, encoding, payload))
                _, mode, encoding, payload = min(candidates)
                if decode_tile(payload, count, mode) != tile:
                    raise AssertionError(f"{mode} round trip failed at {position}")
                groups.append(ProposedNumberGroup(
                    ConcreteFormat.KULISCH, encoding, count, len(payload)
                ))
                modes[encoding.name] += 1
            position += count
    if position != len(values):
        raise AssertionError("source packets do not cover the output vector")
    accounting_groups = [
        (group.format.name if group.encoding is None else group.encoding.name.lower(),
         group.payload_bytes)
        for group in groups
    ]
    return packet_bytes(accounting_groups, merge_equal=True), modes


def study_chunk(values: list[int]) -> dict:
    auto, auto_counts, auto_packets = auto_account(values)
    _, uniform, uniform_packets = ccl_packets(exact_values(values), "KULISCH")
    if fixed_account(values, "KULISCH") != uniform:
        raise AssertionError("uniform Kulisch accounting mismatch with CCL")
    fp32 = fixed_account(values, "FP32")
    range_only, _ = adaptive_account(
        values, auto_packets, (KulischEncoding.RAW, KulischEncoding.RANGE))
    indexed_only, _ = adaptive_account(
        values, auto_packets, (KulischEncoding.RAW, KulischEncoding.INDEX))
    mask_only, _ = adaptive_account(
        values, auto_packets, (KulischEncoding.RAW, KulischEncoding.MASK))
    adaptive, modes = adaptive_account(values, auto_packets,
                                             tuple(KulischEncoding))
    # Disable AUTO entirely: one homogeneous Kulisch group per original frame,
    # split only by the raw 41-byte value width and the same 1500-byte MTU.
    # Apply precisely the same codec selector and repacketizer as for AUTO.
    uniform_adaptive, uniform_modes = adaptive_account(
        values, uniform_packets, tuple(KulischEncoding))
    if adaptive[0] > auto[0] or adaptive[1] > auto[1]:
        raise AssertionError("compressed AUTO must not exceed current AUTO")
    if uniform_adaptive[0] > uniform[0] or uniform_adaptive[1] > uniform[1]:
        raise AssertionError("compressed uniform Kulisch must not exceed raw output")
    return {
        "n": len(values), "four_rank_fp32_partials": True,
        "exact_not_fp32": sum(auto_format(v) == "KULISCH" for v in values),
        "auto_formats": auto_counts, "selected_encoding_groups": modes,
        "uniform_selected_encoding_groups": uniform_modes,
        "source_group_counts": {"uniform_kulisch": sum(len(p.groups) for p in uniform_packets),
                                "auto": sum(len(p.groups) for p in auto_packets)},
        "uniform_kulisch": {"frame_bytes": uniform[0], "packets": uniform[1]},
        "compressed_uniform_kulisch": {"frame_bytes": uniform_adaptive[0],
                                       "packets": uniform_adaptive[1]},
        "auto": {"frame_bytes": auto[0], "packets": auto[1]},
        "compressed_exact": {"frame_bytes": adaptive[0], "packets": adaptive[1]},
        "fixed_fp32": {"frame_bytes": fp32[0], "packets": fp32[1]},
        "range_only": {"frame_bytes": range_only[0], "packets": range_only[1]},
        "indexed_only": {"frame_bytes": indexed_only[0], "packets": indexed_only[1]},
        "mask_only": {"frame_bytes": mask_only[0], "packets": mask_only[1]},
    }


def study_case(label: str, partials: list[list[float]], metadata: dict) -> dict:
    values = scaled_exact(partials)
    chunks = [study_chunk(values[start:start + 4096])
              for start in range(0, len(values), 4096)]
    result = {"label": label, "metadata": metadata, "n": len(values),
              "chunks": [chunk["n"] for chunk in chunks],
              "four_rank_fp32_partials": True,
              "exact_not_fp32": sum(chunk["exact_not_fp32"] for chunk in chunks)}
    for key in ("auto_formats", "selected_encoding_groups", "uniform_selected_encoding_groups",
                "source_group_counts"):
        result[key] = {name: sum(chunk[key][name] for chunk in chunks)
                       for name in chunks[0][key]}
    for key in ("uniform_kulisch", "compressed_uniform_kulisch", "auto", "compressed_exact", "fixed_fp32",
                "range_only", "indexed_only", "mask_only"):
        result[key] = {measure: sum(chunk[key][measure] for chunk in chunks)
                       for measure in ("frame_bytes", "packets")}
    return result


def synthetic_case() -> dict:
    # 2^-24 is the smallest positive FP16 subnormal. Both operands fit FP16,
    # but their exact sum lies halfway between adjacent FP32 values near 1.
    scaled = (1 << 149) + (1 << 125)
    partials = [[1.0, math.ldexp(1.0, -24), 0.0, 0.0] for _ in range(726)]
    result = study_case("Constructed / 1 + 2^-24", partials, {
        "outputs": 726, "kernel": "constructed exactness stress case",
        "input": "1 and smallest positive FP16 subnormal; one DATA packet per rank",
    })
    if scaled_exact(partials)[0] != scaled or auto_format(scaled) != "KULISCH":
        raise AssertionError("synthetic exactness case changed")
    if result["uniform_kulisch"]["frame_bytes"] != 31048:
        raise AssertionError("uniform packet accounting disagrees with existing figure")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--cache", type=Path, default=root / "build/cache/exact-accumulator-sources")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("results.json"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    paths = checked_sources(args.cache, args.download)
    cases = [synthetic_case()]
    cases.append(study_case(*cavity_kernel(paths["cavity01.tar.gz"])))
    cases.append(study_case(*structural_kernel(paths["bcsstk16"])))
    cases.extend(study_case(*case) for case in pythia_kernels(paths["pythia-14m-model.safetensors"]))
    report = {
        "protocol": {"mtu": MTU, "frame_overhead": FRAME_OVERHEAD,
                     "numbergroup_descriptor": 4, "padding": "4-byte group alignment",
                     "kulisch_bits": KULISCH_BITS, "kulisch_scale": -KULISCH_SCALE,
                     "candidate_scope": "each current-AUTO Kulisch group",
                     "uniform_compression_scope": "each uniform-Kulisch frame group before compression; at most 35 values",
                     "proposed_block_bits": 8, "ranks": RANKS},
        "proposed_numbergroup": {
            "status": "software-only; current CCL and RTL require descriptor byte 1 to be zero",
            "format": ConcreteFormat.KULISCH.name,
            "encoding_field": "NumberGroup descriptor byte 1 (currently reserved zero)",
            "encoding_ids": {encoding.name: int(encoding) for encoding in KulischEncoding},
            "selection_scope": "each current-AUTO Kulisch NumberGroup",
        },
        "scope": "local FP32 kernel emulation; exact Reduce of four rank partials; not hardware/MPI traffic",
        "compressed_uniform_baseline": {
            "native_format_selection": False,
            "source_grouping": "one homogeneous KULISCH group per original MTU-limited frame",
            "max_values_per_source_group": 35,
            "codecs": [encoding.name for encoding in KulischEncoding],
            "selection": "smallest padded group, identical to AUTO plus compression",
            "packetization": "repack compressed groups in order; retain descriptors and padding",
            "limitation": "no mixed native formats; not a descriptor-free protocol or globally optimized compressed packetizer",
        },
        "sources": {name: {"url": url, "sha256": digest}
                    for name, (url, digest) in SOURCES.items()},
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for case in cases:
        summary = " ".join(f"{key}={case[key]['frame_bytes']}B/{case[key]['packets']}pkt"
                           for key in ("uniform_kulisch", "compressed_uniform_kulisch", "auto", "compressed_exact", "fixed_fp32"))
        print(f"{case['label']}: N={case['n']} exact-only={case['exact_not_fp32']} {summary}")


if __name__ == "__main__":
    main()
