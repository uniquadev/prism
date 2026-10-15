from __future__ import annotations

from dataclasses import replace

import pytest

from prism_ccl.application.window import Admission, ReceiveWindow
from prism_ccl.domain.model import ConcreteFormat, OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

KEY = OperationKey(1, 2, 3, 4, 5)
DST = bytes.fromhex("001122334455")
SRC = bytes.fromhex("66778899aabb")


def _frame(packet_id: int, first: int, values: tuple[int, ...], *, last: bool = False) -> bytes:
    packet = DataPacket(
        PacketClass.DATA,
        KEY,
        1,
        2,
        3,
        packet_id,
        first,
        (NumberGroup(ConcreteFormat.INT8, values),),
        last,
    )
    return encode_data_frame(
        packet, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
    )


def _window(*, byte_credit: int = 1500, interval_credit: int = 2) -> ReceiveWindow:
    return ReceiveWindow(
        operation=KEY,
        packet_class=PacketClass.DATA,
        source_endpoint=1,
        destination_endpoint=2,
        stream_id=3,
        element_count=4,
        allowed_formats=frozenset({ConcreteFormat.INT8}),
        mtu=1500,
        kulisch_bits=279,
        maximum_intervals=interval_credit,
        maximum_bytes=byte_credit,
        element_span=4,
    )


def test_reorder_duplicate_hole_and_completion_without_packet_count() -> None:
    window = _window()
    first = _frame(0, 0, (1, 2))
    second = _frame(1, 2, (3, 4), last=True)
    with pytest.raises(ValueError, match="not committed"):
        window.accept(first)
    window.activate()
    assert window.accept(second) == Admission.ACCEPTED
    assert window.holes == ((0, 2),)
    assert window.peek_contiguous() is None
    assert window.accept(second) == Admission.DUPLICATE
    assert window.accept(first) == Admission.ACCEPTED
    assert window.credit_intervals == 0
    chunk = window.peek_contiguous()
    assert chunk is not None and [value.value for value in chunk.values] == [1, 2]
    window.release_contiguous(chunk)
    assert window.accept(first) == Admission.DUPLICATE
    with pytest.raises(ValueError, match="changed its bytes"):
        window.accept(_frame(0, 0, (8, 2)))
    chunk = window.peek_contiguous()
    assert chunk is not None and [value.value for value in chunk.values] == [3, 4]
    window.release_contiguous(chunk)
    assert window.complete
    assert window.credit_intervals == 2
    assert window.credit_bytes == 1500


def test_overlap_under_new_packet_id_is_not_applied_twice() -> None:
    window = _window()
    window.activate()
    assert window.accept(_frame(0, 0, (1, 2))) == Admission.ACCEPTED
    assert window.accept(_frame(7, 1, (9, 9))) == Admission.OVERLAP
    assert window.credit_intervals == 1
    chunk = window.peek_contiguous()
    assert chunk is not None
    window.release_contiguous(chunk)
    assert window.accept(_frame(7, 1, (9, 9))) == Admission.OUT_OF_WINDOW


def test_byte_credit_invalid_frame_and_replay_mutation() -> None:
    first = _frame(0, 0, (1, 2))
    second = _frame(1, 2, (3, 4), last=True)
    window = _window(byte_credit=len(first))
    window.activate()
    malformed = bytearray(first)
    malformed[-1] = 1
    with pytest.raises(ValueError, match="padding"):
        window.accept(bytes(malformed))
    assert window.credit_bytes == len(first)
    assert window.accept(first) == Admission.ACCEPTED
    assert window.accept(second) == Admission.NO_CREDIT
    changed = _frame(0, 0, (8, 2))
    with pytest.raises(ValueError, match="changed its bytes"):
        window.accept(changed)


def test_last_generation_and_malformed_state_are_rejected() -> None:
    window = _window()
    window.activate()
    with pytest.raises(ValueError, match="LAST"):
        window.accept(_frame(0, 0, (1, 2), last=True))
    stale = DataPacket(
        PacketClass.DATA,
        replace(KEY, operation_generation=4),
        1,
        2,
        3,
        0,
        0,
        (NumberGroup(ConcreteFormat.INT8, (1, 2)),),
    )
    with pytest.raises(ValueError, match="identity"):
        window.accept(
            encode_data_frame(
                stale, destination_mac=DST, source_mac=SRC, mtu=1500, kulisch_bits=279
            )
        )
    assert window.base == 0 and window.credit_intervals == 2
