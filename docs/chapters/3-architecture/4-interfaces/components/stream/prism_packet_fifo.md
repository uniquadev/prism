# `prism_packet_fifo`

**Module class:** `COMPONENT / STREAM`  

`prism_packet_fifo` is a packet-aware sequential beat queue used for VOQs and
internal injection. It separates capacity reservation from
beat transfer so an admitted packet can never run out of storage halfway
through enqueue.

## Contracts

- **Enqueue stream — input, one `prism_axis`:** accepts 512-bit beats only under
  a live reservation ID. The reservation ID is 15 bits and remains constant for
  the packet.

- **Dequeue stream — output, one `prism_axis`:** exposes beats in packet order.
  `tdata`, `tkeep`, `tlast`, and `tuser_err` remain stable while stalled.

- **Capacity reservation — input/output, 32-bit request and 32-bit response:**
  reserves up to 16-bit beat count before enqueue and returns a unique 15-bit
  token with the granted count.

- **Reservation completion — input, 32 bits:** contains reservation ID 15,
  consumed beats 16, and one abort bit. Completion returns unused credits or
  discards the tentative packet.

- **Queue state — output, 48 bits:** 16-bit free beats, 16-bit committed beats,
  8-bit complete-packet count, and 8 status flags.

- **Flush command/status — input/output, 16/16 bits:** flushes only when the
  owner has quiesced enqueue and dequeue. It reports completion and any
  outstanding-reservation violation.

## Contract behavior

- Read and write pointers advance only on their corresponding ready/valid
  transfer. Simultaneous enqueue and dequeue are legal.
- Beats belonging to an aborted or malformed tentative packet never become
  visible at dequeue.
- `show-ahead` output may be implemented, but no combinational path may run from
  downstream `tready` across a registered module boundary.
- Depth, memory style, and cut-through threshold are parameters; counters are
  sized to the configured depth and asserted against overflow at elaboration.

## Related modules and concepts

Matrix instances are composed by [`prism_voq_bank`](prism_voq_bank.md). Random
packet retention uses [`prism_packet_store`](prism_packet_store.md) instead of
this FIFO.
