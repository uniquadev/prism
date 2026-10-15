"""A NumberGroup frame may use the full Ethernet payload MTU."""

from __future__ import annotations

from typing import Any

import cocotb
from prism_ccl.domain.model import ConcreteFormat
from prism_ccl.wire.data import (
    DataPacket,
    NumberGroup,
    PacketClass,
    decode_data_frame,
    encode_data_frame,
)

from .numbergroup_frame_fixture import DESTINATION, OPERATION, SOURCE
from .test_numbergroup_mixed_tile_cocotb import initialize, receive, send_tile


@cocotb.test()
async def full_mtu_int8_group_is_not_capped_by_ethernet_header(dut: Any) -> None:
    await initialize(dut)
    dut.s_mtu.value = 1500
    total = 1452
    receiver = cocotb.start_soon(receive(dut, 1, stall=False))
    for first in range(0, total, 16):
        count = min(16, total - first)
        await send_tile(dut, ((ConcreteFormat.INT8, 7),) * count, first, total)

    frames = await receiver
    assert len(frames) == 1
    # Ethernet header (14) + configured payload MTU (1500), with two
    # unused bytes because the NumberGroup body is aligned to four.
    assert len(frames[0]) == 1512
    expected = encode_data_frame(
        DataPacket(
            PacketClass.DATA,
            OPERATION,
            1,
            2,
            3,
            90,
            0,
            (NumberGroup(ConcreteFormat.INT8, (7,) * total),),
            last=True,
        ),
        destination_mac=DESTINATION,
        source_mac=SOURCE,
        mtu=1500,
        kulisch_bits=320,
    )
    assert frames[0] == expected
    packet = decode_data_frame(frames[0], mtu=1500, kulisch_bits=320)
    assert packet.first_element == 0 and packet.element_count == total
    assert packet.last and len(packet.groups) == 1
    assert packet.groups[0].format == ConcreteFormat.INT8
    assert packet.groups[0].values == (7,) * total
