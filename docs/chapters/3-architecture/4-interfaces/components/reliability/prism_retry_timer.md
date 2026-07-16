# `prism_retry_timer`

**Module class:** `COMPONENT / RELIABILITY`  

`prism_retry_timer` tracks bounded retransmission deadlines for reliable direct
transfers. It schedules replay work but never reads or reconstructs packets.

## Contracts

- **Arm/update command — input, 256-bit payload + valid/ready:** contains the
  192-bit replay key, 32-bit deadline delta, 16-bit retry limit, 8-bit action,
  and 8 flags.

- **Cancel command — input, 192-bit replay key + valid/ready:** removes the
  timer after acknowledgment, abort, release, or fatal feedback.

- **Timebase — input, 64 bits:** free-running datapath-domain counter derived
  from the configured 322.265625 MHz frequency.

- **Expiry/replay request — output, 192-bit replay key + 16-bit attempt count +
  8-bit status with valid/ready:** requests one retained replay or reports retry
  exhaustion.

- **Timer state — output, 64 bits:** reports armed entries, next-expiry class,
  canceled timers, emitted retries, exhausted transfers, and command conflicts.

## Contract behavior

- Deadlines use wrap-safe unsigned counter comparison and are never shortened
  below a validated peer-provided retry delay.
- Acknowledgment wins over same-cycle expiry for the same replay key.
- Attempt count advances only when the replay request is accepted, not merely
  when a deadline is observed.
- Timer slots are generation-qualified and cannot fire for a released/reused
  operation ID.

## Related modules and concepts

The timer is updated by [`prism_progress_engine`](prism_progress_engine.md) and
requests packets from [`prism_replay_cache`](prism_replay_cache.md). The parent
unit resolves ACK/timeout races.
