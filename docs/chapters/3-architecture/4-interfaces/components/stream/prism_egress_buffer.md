# `prism_egress_buffer`

**Module class:** `COMPONENT / STREAM`  

`prism_egress_buffer` is the last elastic stage before a core TX port. It keeps
the current beat stable under shell backpressure and prevents PRISM from
introducing a `tvalid` bubble inside a packet when downstream remains ready.

## Contracts

- **Crossbar stream — input, one `prism_axis`:** accepts the granted packet from
  the registered switch traversal stage.

- **TX stream — output, one `prism_axis`:** drives one physical egress with a
  stable beat under stall and a contiguous valid sequence from first beat to
  `tlast` when `tready` is continuously asserted.

- **Start authorization — input, 16 bits:** contains buffered-beat count, packet
  closed bit, cut-through-safe bit, and scheduler lock bit. An unauthorized head
  cannot appear on TX.

- **Buffer state — output, 32 bits:** 16-bit occupancy, 8-bit packet count, and
  8 flags for full, empty, open packet, stalled, underflow attempt, and error.

- **Packet completion — output, 16 bits + valid/ready:** reports egress, source
  ID, error bit, and accepted final-beat status to the arbiter and counters.

## Contract behavior

- The elastic depth is at least two beats and is parameterized for timing and
  cut-through proof. Output registers have no combinational dependency on TX
  `tready` for data selection.
- If downstream deasserts `tready`, `tvalid`, `tdata`, `tkeep`, `tlast`, and
  `tuser_err` remain unchanged until accepted.
- Underflow during an open packet is a fatal design error, not a legal `tvalid`
  bubble. Eligibility logic must prevent the packet from starting.
- Reset suppresses `tvalid` and discards no externally visible half-packet;
  system integration must hold the link in reset during a datapath reset.

## Related modules and concepts

This component terminates [`prism_stream_crossbar`](prism_stream_crossbar.md)
and drives the TX side of [`prism_switch_core`](../../top/prism_switch_core.md).
The definition of gap-free service is in
[Forwarding, arbitration, and gap-free transmission](../../../2.pipeline.md#325-forwarding-arbitration-and-gap-free-transmission).
