# `prism_progress_engine`

**Module class:** `COMPONENT / RELIABILITY`  

`prism_progress_engine` decodes validated `PM_OP_COL_PROGRESS` feedback and
constructs feedback for safely received DATA/RES packets. It owns selective-ACK
bitmap interpretation and advertised receive-window state, but not packet
retention or timeout counting.

## Contracts

- **Validated PROGRESS packet — input, 512-bit descriptor + valid/ready:**
  supplies the complete fixed header, operation identity, peer identity, flags,
  window fields, status, reason, retry delay, and bitmap handle.

- **Bitmap read — output/input, 32-bit packet-store command and one
  `prism_axis`:** reads exactly `ceil(Bitmap Bits / 8)` bytes when the selective
  ACK flag is present.

- **Safe-receive event — input, 256-bit `prism_rx_accept_event_t` + valid/ready:**
  requests an ACCEPTED, DUPLICATE, window, retry, or fatal response for one
  direct peer.

- **Replay/timer update — output, 256-bit progress event + valid/ready:** applies
  acknowledgments, advertised windows, retry delay, and fatal status to the
  named reliable transfer.

- **Generated feedback — output, 512-bit packet-serialization command + bitmap
  payload stream:** builds a hop-local PROGRESS packet addressed to the direct
  sender.

- **Progress status — output, 64 bits:** reports parsed feedback, generated ACKs,
  bitmap errors, stale generations, and window updates.

## Contract behavior

- The full operation generation and Peer Kind namespace are checked before any
  replay or window state changes.
- Bitmap bit `j` acknowledges `Selective ACK Base + j` in the named peer's
  direct DATA or RES stream, most-significant bit first; unused final-byte bits
  must be zero.
- A single-chunk ACK is encoded as a one-bit bitmap. A pure window update may
  carry zero bitmap bits.
- Malformed feedback changes no replay or timer state and produces one explicit
  validation/status event.

## Related modules and concepts

The component is orchestrated by
[`prism_reliability_unit`](../../units/prism_reliability_unit.md) and updates
[`prism_replay_cache`](prism_replay_cache.md) and
[`prism_retry_timer`](prism_retry_timer.md).
