# `prism_accumulation_scheduler`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_accumulation_scheduler` selects eligible global-element tiles across
active operations. It enforces the accumulator profile's update semantics,
resolves bank and backend structural conflicts, and interlocks accumulator
dependencies.

## Contracts

- **Normalized work — input, 4 × (192-bit metadata + 528-bit V1 payload) with
  valid/ready:** accepts up to four tiles produced by the two ingress
  normalizers. Input queues retain profile, contributor, and global
  range identity.

- **Accumulator state lookup — output/input, up to 4 × 96-bit address and
  fixed status metadata with valid/ready:** obtains initialization, next
  Contributor ID, pending dependency, and bank ownership without assuming a
  universal numeric state width.

- **Backend dispatch — output, up to 4 × (192-bit metadata + 528-bit V1
  payload) with valid/ready:** issues selected work to
  `prism_accumulator_backend_dispatcher`. Port count is backend capacity, not an
  operation count.

- **Backend commit — input, up to 4 × 192-bit `prism_arith_commit_t` +
  valid/ready:** retires tags and advances ordering/dependency state only after
  the matching profile-specific state write commits.

- **Contribution commit — output, 96 bits + valid/ready:** marks the final tile
  of a contributor interval `APPLIED` using operation slot, range slot,
  contributor, global First Element, and flags.

- **Scheduler state — output, 192 bits:** exposes per-profile ready work,
  ordering waits, bank conflicts, dependency stalls, active operations,
  outstanding tags, and sticky ordering faults.

## Contract behavior

- `FP32_ORDERED` requires the stored next Contributor ID for each range; its
  first contributor initializes state without adding zero. Future profiles
  define their own eligibility rule.
- A tile cannot read stale data. A matching in-flight result is forwarded or
  awaited; unrelated operations and ranges remain eligible.
- Fair arbitration prevents one operation from permanently occupying a shared
  backend. A stalled profile blocks only its candidates unless the conflict is
  a shared bank or commit port.
- In-flight tags are unique and responses must match generation and profile.

## Related modules and concepts

State resides in [`prism_accumulator_store`](prism_accumulator_store.md); work
is routed by
[`prism_accumulator_backend_dispatcher`](../arithmetic/prism_accumulator_backend_dispatcher.md).
