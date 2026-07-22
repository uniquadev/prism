# `prism_result_packetizer`

**Module class:** RES framing boundary

`prism_result_packetizer` serializes one destination-specific packet job and
its stored payload as an Ethernet RES frame for a single egress port.

## Contracts

- **Packet job:** accepts `prism_result_packet_job_t` after its chunk slot has been armed.
- **Payload read:** supplies the storage slot and byte offset and consumes the corresponding 512-bit read data.
- **Egress AXI stream:** publishes the complete 512-bit Ethernet frame with `tkeep`, `tlast`, and ready/valid flow control.
- **Release event:** returns the chunk slot after the final frame beat is accepted.

## Contract behavior

- Builds Ethernet, PRISM control-word, and RES headers from the packet job and local MAC address.
- Reads payload bytes without changing their numeric wire order.
- Sets the last-chunk and accumulation-inexact flags from chunk metadata.
- Pads short Ethernet frames to 60 bytes while retaining the logical payload length in protocol metadata.
- Holds output data stable under backpressure and releases the slot exactly once after transmission.

## Related modules and concepts

- [`prism_result_router`](../collective/prism_result_router.md)
- [`prism_result_chunk_store`](../collective/prism_result_chunk_store.md)
- [`prism_collective_core`](../core/prism_collective_core.md)
- [Protocol](../../1.protocol.md)
- [Current shared contracts](../common-contracts.md)
