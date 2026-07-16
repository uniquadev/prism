# `prism_ingress_unit`

**Module class:** `MAIN UNIT`  

`prism_ingress_unit` owns one packet from its first received beat until that
packet has been committed to a forwarding queue, committed to local packet
storage, or completely drained as a drop. It couples first-beat parsing with a
packet-order context FIFO so body beats never need to be classified again.

## Contracts

- **Ingress stream — input, one `prism_axis`:** accepts a 512-bit packet stream
  from the shell-facing staging FIFO. Once the first beat is accepted, the unit
  must consume or deliberately drain the packet through `tlast`.

- **Parsed-header event — output, 352-bit payload + valid/ready:** sends the
  320-bit fixed header image and ingress metadata to
  [`prism_forwarding_unit`](prism_forwarding_unit.md) as soon as the first beat
  contains the required header bytes.

- **Classification/route decision — input, 64-bit payload + valid/ready:**
  receives the packet class, selected egress, and any classification drop
  reason from the forwarding unit. Its reservation field is zero; the ingress's
  admission controller fills that field only after capacity is granted.

- **Forwarding stream — output, one `prism_axis` + 64-bit decision per packet:**
  drains an admitted transparent packet to its reserved VOQ without modifying
  any beat.

- **Local-store write — output, one `prism_axis` + 16-bit store handle:** writes
  every beat of a locally owned PRISM packet into its preallocated packet-store
  slot.

- **Closed local descriptor — output, 384-bit payload + valid/ready:** emits
  exactly one descriptor after `tlast`, observed length, `tkeep`, shell error,
  and store completion are known. DATA, CONTROL, RESULT, and PROGRESS candidates
  all pass closed-packet validation; supported DATA proceeds to the collective
  unit, RES to result delivery, PROGRESS to reliability, and CONTROL to
  management.

- **Reservation channels — output/input, 32-bit request and 32-bit response:**
  requests maximum-frame capacity from the selected VOQ or local packet store
  before the packet leaves staging.

- **Drop event — output, 64 bits + valid/ready:** reports ingress port, 8-bit
  drop reason, packet class, observed length, and a truncated operation-key
  hash for counters and debug; it carries no state-changing command.

## Contract behavior

- Header decision latency is bounded and the context FIFO is at least as deep
  as the number of packets whose first beat can be accepted before a decision
  returns.
- A reservation is spent once. Unused beat credits are returned only after the
  accepted `tlast`; a failed reservation selects the drain/drop path before any
  partial enqueue.
- A locally owned packet is never exposed downstream before closure. A bad or
  truncated local packet releases its store slot and emits no valid descriptor.
- The packet-order context acts as the diagram's DEMUX control. For every body
  beat, exactly one of forwarding enqueue, local-store write, or drain/drop is
  selected; unselected outputs keep `valid=0`. Backpressure from the selected
  branch stops the core-side staging dequeue without changing that selection.
- Each ingress data path has `II=1` at beat granularity and can drain one beat
  per cycle. The two instances are independent, so both physical ports can be
  active concurrently.

## Related modules and concepts

The unit composes [`prism_header_parser`](../components/stream/prism_header_parser.md),
[`prism_admission_controller`](../components/stream/prism_admission_controller.md),
and [`prism_packet_store`](../components/stream/prism_packet_store.md). Its
ownership rules come from [Frame ownership and forwarding](../../1.protocol.md#frame-ownership-and-forwarding).
