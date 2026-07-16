# `prism_egress_unit`

**Module class:** `MAIN UNIT`  

`prism_egress_unit` is the only path to the two core TX streams. It owns the
source-by-egress packet queues, selects a packet-level matching, locks each
grant through `tlast`, and provides a gap-free output buffer per physical port.

## Contracts

- **Forwarded packet inputs — input, 2 × `prism_axis` + 2 × 64-bit route
  decision:** each physical ingress contributes one source row. Admission has
  already reserved the complete maximum-frame capacity in the selected VOQ.

- **Internal injection inputs — input, 3 × `prism_axis` + 3 × 8-bit egress:**
  result, management, and progress/reliability sources occupy stable row IDs
  and are scheduled independently for each egress.

- **Queue reservation — input/output, 5 × 32-bit requests and responses:** one
  reservation channel exists per source row. Reservations are resolved per
  egress so simultaneous traffic to different egresses can proceed.

- **VOQ candidate matrix — internal, 5 × 2 `prism_axis` heads:** ten packet FIFO
  outputs expose only complete or explicitly cut-through-safe packets to the
  arbiter.

- **Grant matrix — internal, 10 bits:** `grant[source][egress]` is one-hot per
  source and per egress. A grant remains registered until the accepted final
  beat.

- **Core TX streams — output, 2 × `prism_axis`:** one gap-free, non-interleaved
  packet stream per physical egress.

- **Scheduler event — output, 64 bits + valid/ready:** reports egress, source,
  queue occupancy class, packet start/end, stall, and bounded-blocking counter.

## Contract behavior

- The v1 matrix has five source rows and two egress columns. Array dimensions
  remain parameters so adding ports or injection classes does not change a
  child module's scalar interface.
- Enqueue is row-parallel: both ingress rows and every enabled internal row may
  each accept one beat in the same cycle. Contention is deferred to packet
  selection at the VOQ heads, not serialized at the VOQ write side.
- Round-robin state advances only when the first beat of a new packet is
  accepted. Backpressure cannot cause a grant to move to another source.
- A queue may advertise an open packet only if the buffered-beat guarantee can
  maintain gap-free output; otherwise it waits for packet closure.
- Mandatory management, result, acknowledgment, or replay traffic must have
  reserved queue capacity before the state transition that requires the packet.

## Related modules and concepts

This unit composes [`prism_voq_bank`](../components/stream/prism_voq_bank.md),
[`prism_packet_arbiter`](../components/stream/prism_packet_arbiter.md),
[`prism_stream_crossbar`](../components/stream/prism_stream_crossbar.md), and
[`prism_egress_buffer`](../components/stream/prism_egress_buffer.md). The
matching equations are in [Forwarding, arbitration, and gap-free transmission](../../2.pipeline.md#325-forwarding-arbitration-and-gap-free-transmission).
