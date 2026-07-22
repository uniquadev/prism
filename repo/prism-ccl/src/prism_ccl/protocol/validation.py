"""Cross-field validation for serialized PRISM payloads."""

from __future__ import annotations

from .constants import (
    CONTROL_WORD_BYTES,
    DATA_HEADER_BYTES,
    PartialWireFormat,
    WireFormat,
)
from .errors import ProtocolDecodeError
from .geometry import expected_payload_bytes


def validate_payload_length(
    actual_bytes: int,
    element_count: int,
    elements_per_chunk: int,
    chunk_index: int,
    wire_format: WireFormat | PartialWireFormat,
) -> int:
    """Validate logical payload length while accepting Ethernet padding."""

    expected = expected_payload_bytes(element_count, elements_per_chunk, chunk_index, wire_format)
    prism_bytes = CONTROL_WORD_BYTES + DATA_HEADER_BYTES + expected
    padding = max(0, 46 - prism_bytes)
    if actual_bytes not in (expected, expected + padding):
        raise ProtocolDecodeError(
            f"logical payload length {actual_bytes} does not match expected {expected}"
        )
    return expected
