# `prism_replay_cache`

**Module class:** `COMPONENT / RELIABILITY`  

`prism_replay_cache` retains the canonical first-transmission image of every
reliable DATA or RES packet until acknowledgment or terminal failure. It is
indexed by the direct-transfer identity, not merely by Chunk Index.

## Contracts

- **Retention command — input, 256-bit replay command + valid/ready:** reserves
  a slot for the 192-bit replay key, packet handle, egress, retry limit, and
  flags before first transmission.

- **Packet capture — input, one `prism_axis` + 16-bit replay slot:** stores every
  generated beat, including `tkeep`, `tlast`, and the exact direct-link header.

- **Replay request — input, 192-bit replay key + valid/ready:** selects one
  acknowledged-missing or expired transfer without rebuilding its payload.

- **Replay output — output, one `prism_axis` + 8-bit egress:** emits the retained
  packet through the reliability injection queue. A small header patch stage
  sets only the Protocol 1.0 `RETRANSMIT` flag on retry.

- **Acknowledge/release — input, 192-bit replay key + 8-bit status with
  valid/ready:** releases a slot only after positive acknowledgment or a
  terminal policy decision.

- **Cache state — output, 96 bits:** reports free/used slots, retained beats,
  capture/replay activity, key conflicts, retry exhaustion, and storage faults.

## Contract behavior

- A replay key is unique across Job, Group, Operation, Peer Kind, Peer ID, and
  that peer's DATA or RES stream-local Chunk Index. A generation mismatch cannot
  hit an older slot; no equality with another format's Chunk Index is implied.
- A slot becomes replayable only after the complete original packet has been
  captured and its first transmission admitted.
- Except for the retry-time `RETRANSMIT` bit, header identities, payload bytes,
  `tkeep`, and packet length are identical to the first transmission.
- ACK and release are idempotent. A late duplicate ACK cannot free a slot that
  has been reassigned to a newer generation.
- Cache exhaustion propagates to admission before a reliable transfer changes
  protocol or arithmetic state.

## Related modules and concepts

The cache is registered by result/data generation, requested by
[`prism_retry_timer`](prism_retry_timer.md), and released by
[`prism_progress_engine`](prism_progress_engine.md).
