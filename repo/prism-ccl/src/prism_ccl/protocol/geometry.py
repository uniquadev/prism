"""Chunk geometry derived from protocol capacities and numeric datatypes."""

from __future__ import annotations

from .constants import (
    BYTES_PER_ELEMENT,
    CHUNK_PAYLOAD_BYTES,
    PARTIAL_BYTES_PER_ELEMENT,
    PartialWireFormat,
    WireFormat,
)


def expected_chunks(element_count: int, elements_per_chunk: int) -> int:
    """Return the number of chunks required for an operation."""

    if element_count <= 0 or elements_per_chunk <= 0:
        raise ValueError("element_count and elements_per_chunk must be positive")
    result = (element_count + elements_per_chunk - 1) // elements_per_chunk
    if result > 1 << 24:
        raise OverflowError("expected chunk count exceeds 24-bit namespace")
    return result


def elements_in_chunk(element_count: int, elements_per_chunk: int, chunk_index: int) -> int:
    """Return the logical element count for one validated chunk index."""

    count = expected_chunks(element_count, elements_per_chunk)
    if not 0 <= chunk_index < count:
        raise ValueError("chunk index is outside the operation")
    first = chunk_index * elements_per_chunk
    return min(elements_per_chunk, element_count - first)


def expected_payload_bytes(
    element_count: int,
    elements_per_chunk: int,
    chunk_index: int,
    wire_format: WireFormat | PartialWireFormat,
) -> int:
    """Return the exact logical payload bytes for one data or result chunk."""

    try:
        element_bytes = (
            PARTIAL_BYTES_PER_ELEMENT[wire_format]
            if isinstance(wire_format, PartialWireFormat)
            else BYTES_PER_ELEMENT[wire_format]
        )
    except KeyError as error:
        raise ValueError(f"unsupported wire format {wire_format!r}") from error
    result = elements_in_chunk(element_count, elements_per_chunk, chunk_index) * element_bytes
    if result > CHUNK_PAYLOAD_BYTES:
        raise OverflowError("chunk payload exceeds PM_CHUNK_PAYLOAD_BYTES")
    return result
