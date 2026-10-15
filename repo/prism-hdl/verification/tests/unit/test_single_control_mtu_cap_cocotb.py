"""The context MTU cannot exceed the receiver's compiled frame capacity."""

from __future__ import annotations

from typing import Any

import cocotb
from prism_ccl.wire.control import ControlCommand

from tests.integration.test_single_control_plane_cocotb import (
    CONTEXT,
    ack,
    frame,
    initialize,
    send,
)


@cocotb.test()
async def compiled_mtu_caps_a_larger_link(dut: Any) -> None:
    await initialize(dut)
    request = frame(ControlCommand.STAGE, 41, body=CONTEXT)
    await send(dut, request)
    await ack(dut, 41, 3)
    assert int(dut.m_context_installed.value) == 0
