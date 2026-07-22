from __future__ import annotations

import unittest

from ccl.axi_stream import AxiStreamFrame
from ccl.transport import CocotbCollectiveTransport, DutFrameTransport
from prism_ccl.protocol.constants import (
    AccumulatorProfile,
    CollectiveSemantic,
    ReductionOperator,
    WireFormat,
)
from prism_ccl.transport import (
    CollectiveTransport,
    Endpoint,
    TransportClosedError,
    TransportRequest,
    TransportResponse,
)


class FakeSource:
    async def send(self, frame: AxiStreamFrame) -> None:
        del frame


class FakeSession:
    def __init__(self) -> None:
        self.cancelled = False

    async def exchange(
        self,
        endpoint: Endpoint,
        request: TransportRequest,
        frames: DutFrameTransport,
    ) -> TransportResponse:
        del endpoint, frames
        return TransportResponse(request.values)

    async def cancel(self, endpoint: Endpoint, request: TransportRequest) -> None:
        del endpoint, request
        self.cancelled = True


def request(rank: int = 0) -> TransportRequest:
    return TransportRequest(
        communicator_id="adapter-test",
        sequence=0,
        rank=rank,
        ranks=(0, 1),
        semantic=CollectiveSemantic.ALLREDUCE,
        root=None,
        operator=ReductionOperator.SUM,
        datatype=WireFormat.FP32,
        output_datatype=WireFormat.FP32,
        accumulator=AccumulatorProfile.FP32_ARRIVAL,
        maximum_terms=2,
        compiled_widths=(64, 288, 320),
        values=(0x3F800000,),
    )


class CocotbCollectiveTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_structurally_implements_public_contract(self) -> None:
        session = FakeSession()
        transport = CocotbCollectiveTransport(
            Endpoint(port=0, rank=0), DutFrameTransport(FakeSource()), session
        )
        self.assertIsInstance(transport, CollectiveTransport)
        with self.assertRaises(TransportClosedError):
            await transport.exchange(request())

        await transport.start()
        self.assertEqual((await transport.exchange(request())).values, (0x3F800000,))
        await transport.cancel(request())
        self.assertTrue(session.cancelled)
        await transport.close()
