# `prism_packet_serializer`

**Module class:** `COMPONENT / STREAM`

`prism_packet_serializer` emits DATA, RES, PROGRESS, and CONTROL packets from an
already prepared header and immutable payload. It does not choose collective
geometry or perform numeric conversion.

## Contracts

- **Command — input, 512-bit `prism_packet_serialize_cmd_t` + valid/ready:**
  supplies header, egress, exact payload length, payload handle, class, and flags.

- **Payload read — output/input, 32-bit request and one 512-bit stream with
  64-bit byte mask:** reads numeric, bitmap, or TLV bytes.

- **Injection reservation — output/input, 32-bit request/response:** reserves
  the complete target VOQ packet before serialization commits.

- **Packet output — output, one `prism_axis` plus 8-bit egress:** emits the
  complete frame and remains stable under backpressure.

- **Replay capture — output, one `prism_axis` plus 256-bit replay command:**
  retains reliable DATA/RES before first transmission.

- **Completion — output, 96 bits + valid/ready:** reports class, operation,
  direct-stream Chunk Index, egress, payload handle, beat count, and status.

## Contract behavior

- Headers use network order; numeric payload is already little endian.
- Final `tkeep` is contiguous and packets never interleave.
- Payload retires only after injection and required replay ownership succeed.

## Related modules and concepts

Commands come from
[`prism_output_packetizer`](../collective/prism_output_packetizer.md),
[`prism_result_replicator`](../collective/prism_result_replicator.md),
management, and reliability.
