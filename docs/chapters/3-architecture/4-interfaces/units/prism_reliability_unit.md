# `prism_reliability_unit`

**Module class:** `MAIN UNIT`  

`prism_reliability_unit` implements Protocol 1.0 hop-by-hop reliability. It
generates PROGRESS feedback after safe DATA/RES acceptance, consumes validated
PROGRESS packets, retains transmitted packets for replay, schedules retries,
and releases state after acknowledgment.

## Contracts

- **Safe-receive event — input, 256-bit `prism_rx_accept_event_t` +
  valid/ready:** reports a newly accepted or duplicate DATA/RES transfer only
  after packet closure, validation, duplicate resolution, and storage admission.

- **Validated PROGRESS descriptor — input, 512-bit payload + valid/ready:**
  carries the complete fixed PROGRESS header and packet-store handle for an
  optional selective-ACK bitmap.

- **Reliable-send registration — input, 256-bit replay command + valid/ready:**
  retains one generated DATA or RES packet under its operation, peer, and
  direct-stream Chunk Index before transmission.

- **Retry-policy lookup — output/input, 32-bit operation-slot request and
  128-bit policy + 8-bit status:** obtains the committed acknowledgment timeout,
  retry limit, advertised window, and feature flags.

- **PROGRESS serialization — output, 512-bit packet-serialization command +
  optional bitmap payload stream:** creates acknowledgments, duplicate feedback,
  window updates, retry advice, and fatal errors for the immediately previous
  sender.

- **Replay packet injection — output, one `prism_axis` + 8-bit egress:** returns
  a retained immutable packet through the progress/reliability injection row.

- **Acknowledgment/retry update — internal, 256-bit progress event +
  valid/ready:** applies feedback to replay state and the retry timer exactly
  once.

- **Reliability status — output, 128 bits:** reports retained packets, armed
  timers, acknowledged releases, duplicates, retry attempts, window stalls, and
  fatal transfers.

## Contract behavior

- An acknowledgment terminates at the direct sender and is never transparently
  forwarded as the same ACK.
- Duplicate DATA/RES never re-enters arithmetic or result delivery, but produces
  valid duplicate feedback when the installed profile requires it.
- If acknowledgment and timeout target the same transfer in one cycle, the ACK
  wins and cancels the stale retry.
- Retry never reconstructs a packet from mutable operation or accumulator state;
  it replays the retained original image with the `RETRANSMIT` flag policy
  applied consistently.

## Related modules and concepts

This unit composes the [reliability components](../index.md#reliability-components)
and injects packets through [`prism_egress_unit`](prism_egress_unit.md).
Normative feedback and bitmap semantics are in
[`PM_OP_COL_PROGRESS`](../../1.protocol.md#pm_op_col_progress).
