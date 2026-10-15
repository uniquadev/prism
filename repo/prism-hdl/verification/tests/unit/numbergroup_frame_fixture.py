"""A stable DATA frame template for NumberGroup sender tests."""

from __future__ import annotations

from prism_ccl.domain.model import OperationKey
from prism_ccl.wire.data import DataPacket, NumberGroup, PacketClass, encode_data_frame

OPERATION = OperationKey(0x0102030405060708, 0x1122, 0x3344, 0x5566, 0x778899AA)
DESTINATION = bytes.fromhex("001122334455")
SOURCE = bytes.fromhex("66778899aabb")


def frame(packet_id: int, first: int, groups: tuple[NumberGroup, ...], *, last: bool) -> bytes:
    return encode_data_frame(
        DataPacket(PacketClass.DATA, OPERATION, 1, 2, 3, packet_id, first, groups, last=last),
        destination_mac=DESTINATION,
        source_mac=SOURCE,
        mtu=576,
        kulisch_bits=320,
    )
