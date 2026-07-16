# `prism_output_packetizer`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_output_packetizer` converts ready accumulator ranges into upstream DATA
partials or final RES chunks. It owns output-format packing and Chunk Index
generation; the packet serializer only emits completed payloads.

## Contracts

- **Ready range — input, 256-bit `prism_ready_range_t` + valid/ready:** names a
  global element interval, profile, outgoing format, role, and state handle.

- **Backend read/finalize — output/input, 96-bit accumulator address, 192-bit
  metadata, and profile-specific numeric data with valid/ready:** selects the
  compatible finalizer, including `prism_fp32_output_converter` in V1.

- **Payload storage — output/input, 32-bit reservation/response and one
  512-bit write stream:** creates an immutable complete output payload.

- **Partial DATA command — output, 512-bit `prism_packet_serialize_cmd_t` +
  valid/ready:** supplies the parent-directed header and payload handle for
  `LEAF` or `INTERNAL` roles.

- **Local RES chunk — output, 288-bit `prism_res_chunk_desc_t` +
  valid/ready:** supplies derived geometry and payload ownership to result
  delivery for `ROOT` or `SINGLE` roles.

- **Range retirement — output, 96 bits + valid/ready:** releases accumulator
  state only after immutable payload ownership or abort.

- **Status — output, 128 bits:** next output index, packing occupancy, pending
  ranges, conversion error, and storage pressure.

## Contract behavior

- Packing follows `floor(1474 / bytes_per_element)` and never splits an element
  across packets.
- Adjacent ranges may fill one output packet; one input range may produce
  several output packets. Gaps hold only the affected output stream.
- Backpressure freezes partial payload and metadata until accepted.

## Related modules and concepts

Ranges come from
[`prism_output_range_tracker`](prism_output_range_tracker.md). RES chunks enter
[`prism_result_delivery_unit`](../../units/prism_result_delivery_unit.md);
partial DATA enters
[`prism_packet_serializer`](../stream/prism_packet_serializer.md).
