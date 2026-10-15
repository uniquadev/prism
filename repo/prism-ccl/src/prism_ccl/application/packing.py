"""Bounded-window Auto selection and whole-element packet construction."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence

from ..domain.model import FORMAT_BYTES, ConcreteFormat, OperationKey
from ..domain.numbers import (
    ExactValue,
    encode_kulisch,
    encode_native_lossless,
    is_lossless,
    kulisch_element_bytes,
)
from ..wire.data import CONTROL_WORD_BYTES, DATA_HEADER_BYTES, DataPacket, NumberGroup, PacketClass

AUTO_LOOKAHEAD = 8
AUTO_ORDER = (
    ConcreteFormat.INT8,
    ConcreteFormat.FP16,
    ConcreteFormat.BF16,
    ConcreteFormat.FP32,
    ConcreteFormat.KULISCH,
)


def element_width(fmt: ConcreteFormat, kulisch_bits: int) -> int:
    return (
        kulisch_element_bytes(kulisch_bits) if fmt == ConcreteFormat.KULISCH else FORMAT_BYTES[fmt]
    )


def group_cost(fmt: ConcreteFormat, count: int, kulisch_bits: int) -> int:
    payload = count * element_width(fmt, kulisch_bits)
    return 4 + payload + (-payload) % 4


def _encode(value: ExactValue, fmt: ConcreteFormat, kulisch_bits: int) -> int | bytes:
    if fmt == ConcreteFormat.KULISCH:
        return encode_kulisch(value, kulisch_bits)
    return encode_native_lossless(value, fmt)


def _candidate(value: ExactValue, fmt: ConcreteFormat, kulisch_bits: int) -> bool:
    if fmt == ConcreteFormat.KULISCH:
        try:
            encode_kulisch(value, kulisch_bits)
        except ValueError:
            return False
        return True
    return is_lossless(value, fmt)


def optimize_reference(values: Sequence[ExactValue], kulisch_bits: int) -> tuple[NumberGroup, ...]:
    """Unbounded software DP oracle for small inputs; not the datapath strategy."""
    if not values:
        raise ValueError("zero-length payload is invalid")
    n = len(values)
    cost = [0] + [10**18] * n
    choice: list[tuple[int, ConcreteFormat] | None] = [None] * (n + 1)
    for end in range(1, n + 1):
        for start in range(end - 1, -1, -1):
            for fmt in AUTO_ORDER:
                if not all(_candidate(value, fmt, kulisch_bits) for value in values[start:end]):
                    continue
                proposed = cost[start] + group_cost(fmt, end - start, kulisch_bits)
                if proposed < cost[end]:
                    cost[end] = proposed
                    choice[end] = (start, fmt)
    groups: list[NumberGroup] = []
    end = n
    while end:
        selected = choice[end]
        if selected is None:
            raise ValueError("no lossless wire representation for value")
        start, fmt = selected
        groups.append(
            NumberGroup(
                fmt, tuple(_encode(value, fmt, kulisch_bits) for value in values[start:end])
            )
        )
        end = start
    groups.reverse()
    return tuple(groups)


def optimize_reference_packets(
    values: Sequence[ExactValue], kulisch_bits: int, mtu: int
) -> tuple[tuple[NumberGroup, ...], ...]:
    """Full packet/header/group optimum; only eight values on the live path."""
    if not values:
        raise ValueError("zero-length payload is invalid")
    budget = mtu - CONTROL_WORD_BYTES - DATA_HEADER_BYTES
    best = [0] + [10**18] * len(values)
    choice: list[tuple[int, tuple[NumberGroup, ...]] | None] = [None] * (len(values) + 1)
    for end in range(1, len(values) + 1):
        for start in range(end):
            groups = optimize_reference(values[start:end], kulisch_bits)
            body = sum(
                group_cost(group.format, len(group.values), kulisch_bits) for group in groups
            )
            if body <= budget and len(groups) <= 255:
                # Ethernet header + FCS + preamble/SFD + IFG = 38 bytes;
                # PRISM control word and DATA header = 42 bytes.
                proposed = best[start] + 80 + body
                if proposed < best[end]:
                    best[end] = proposed
                    choice[end] = (start, groups)
    if best[-1] == 10**18:
        raise ValueError("MTU cannot carry one concrete element")
    packets: list[tuple[NumberGroup, ...]] = []
    end = len(values)
    while end:
        selected = choice[end]
        assert selected is not None
        start, groups = selected
        packets.append(groups)
        end = start
    packets.reverse()
    return tuple(packets)


def optimize_reference_line_bytes(values: Sequence[ExactValue], kulisch_bits: int, mtu: int) -> int:
    """Global small-case line cost used as a test oracle."""
    return sum(
        80 + sum(group_cost(group.format, len(group.values), kulisch_bits) for group in packet)
        for packet in optimize_reference_packets(values, kulisch_bits, mtu)
    )


def select_auto_groups(
    values: Sequence[ExactValue], kulisch_bits: int, mtu: int = 1500
) -> Iterator[NumberGroup]:
    """Eight-value receding-horizon DP over line headers, groups and padding."""
    if not values:
        raise ValueError("zero-length payload is invalid")
    offset = 0
    while offset < len(values):
        window = values[offset : offset + AUTO_LOOKAHEAD]
        first = optimize_reference_packets(window, kulisch_bits, mtu)[0][0]
        yield first
        offset += len(first.values)


def fixed_groups(
    values: Sequence[ExactValue], fmt: ConcreteFormat, kulisch_bits: int
) -> Iterator[NumberGroup]:
    if not values:
        raise ValueError("zero-length payload is invalid")
    for offset in range(0, len(values), AUTO_LOOKAHEAD):
        yield NumberGroup(
            fmt,
            tuple(
                _encode(value, fmt, kulisch_bits)
                for value in values[offset : offset + AUTO_LOOKAHEAD]
            ),
        )


def packetize(
    groups: Iterable[NumberGroup],
    *,
    packet_class: PacketClass,
    operation: OperationKey,
    source_endpoint: int,
    destination_endpoint: int,
    stream_id: int,
    first_element: int,
    mtu: int,
    kulisch_bits: int,
) -> Iterator[DataPacket]:
    """Split logical groups at packet boundaries, never an element.

    The sender's packet geometry is independent of received chunk geometry.
    """
    body_budget = mtu - CONTROL_WORD_BYTES - DATA_HEADER_BYTES
    if body_budget < group_cost(ConcreteFormat.KULISCH, 1, kulisch_bits):
        raise ValueError("MTU cannot carry one widest concrete element")
    if not 0 <= first_element < 1 << 32:
        raise ValueError("first element exceeds vector space")
    pending: list[NumberGroup] = []
    pending_bytes = 0
    pending_count = 0
    packet_id = 0
    position = first_element

    def flush(*, last: bool) -> DataPacket:
        nonlocal pending, pending_bytes, pending_count, packet_id, position
        if not pending:
            raise ValueError("zero-length DATA/RES packet is invalid")
        packet = DataPacket(
            packet_class,
            operation,
            source_endpoint,
            destination_endpoint,
            stream_id,
            packet_id,
            position,
            tuple(pending),
            last=last,
        )
        packet_id += 1
        if packet_id >= 1 << 32:
            raise OverflowError("packet ID namespace exhausted")
        position += pending_count
        pending, pending_bytes, pending_count = [], 0, 0
        return packet

    for group in groups:
        cursor = 0
        while cursor < len(group.values):
            if pending_count == 65535 or len(pending) == 255:
                yield flush(last=False)
            # Adjacent equal formats share one descriptor even if selected by
            # different bounded lookahead windows.
            merge = bool(pending and pending[-1].format == group.format)
            old_count = len(pending[-1].values) if merge else 0
            old_cost = group_cost(group.format, old_count, kulisch_bits) if merge else 0
            room = min(65535 - pending_count, 65535 - old_count, len(group.values) - cursor)
            take = 0
            for candidate in range(1, room + 1):
                delta = group_cost(group.format, old_count + candidate, kulisch_bits) - old_cost
                if pending_bytes + delta > body_budget:
                    break
                take = candidate
            if take == 0:
                if not pending:
                    raise ValueError("MTU cannot carry one NumberGroup element")
                yield flush(last=False)
                continue
            chunk = group.values[cursor : cursor + take]
            new_cost = group_cost(group.format, old_count + take, kulisch_bits)
            pending_bytes += new_cost - old_cost
            pending_count += take
            if merge:
                previous = pending[-1]
                pending[-1] = NumberGroup(group.format, previous.values + chunk)
            else:
                pending.append(NumberGroup(group.format, chunk))
            cursor += take
    if pending:
        yield flush(last=True)
    elif packet_id == 0:
        raise ValueError("zero-length DATA/RES stream is invalid")
