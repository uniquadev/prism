# `prism_contribution_tracker`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_contribution_tracker` is the single writer of direct DATA receive
lifecycle state. It atomically resolves duplicates by packet-stream identity
while exposing the derived global element interval to arithmetic exactly once.

## Contracts

- **Validated contribution — input, 320-bit descriptor + valid/ready:** names
  operation, direct contributor, stream-local Chunk Index, format, global First
  Element, element count, packet handle, and flags.

- **Acceptance result — output, 320-bit descriptor + 16-bit status with
  valid/ready:** forwards one new `STORED` contribution or reports duplicate,
  conflict, out-of-window, stale-generation, or no-slot.

- **Safe-receive event — output, 256-bit `prism_rx_accept_event_t` +
  valid/ready:** permits reliability feedback only after immutable packet
  ownership or duplicate recognition.

- **Arithmetic commit — input, 96 bits + valid/ready:** marks the final tile of
  an accepted packet `APPLIED` using operation, direct Chunk Index,
  Contributor ID, and generation.

- **Lifecycle query/retirement — input/output, 192-bit replay identity,
  32-bit state, and 192-bit retirement key:** supports validation, retry, and
  release without conflating packet identity with accumulator range identity.

- **Tracker state — output, 96 bits:** free, stored, applied, duplicate,
  conflict, and consistency counts/status.

## Contract behavior

- Same-cycle candidates for one `(operation, contributor, DATA Chunk Index)`
  are serialized by one atomic compare-and-set; only one can become `STORED`.
- Conflicting immutable length, format, flags, source, or derived range is a
  protocol error and never reaches arithmetic.
- `APPLIED` is monotonic until retirement. Repeated commits do not advance
  output coverage twice.
- Packet-tracker and accumulator-range capacity are both secured before new
  acceptance, but they remain separately addressed and retired.

## Related modules and concepts

Accepted descriptors feed
[`prism_data_depacketizer`](prism_data_depacketizer.md); committed global
ranges feed [`prism_output_range_tracker`](prism_output_range_tracker.md).
