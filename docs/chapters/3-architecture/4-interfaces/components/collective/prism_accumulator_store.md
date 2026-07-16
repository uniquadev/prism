# `prism_accumulator_store`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_accumulator_store` allocates global element ranges and owns their
profile-specific numeric state plus common dependency metadata. It is a banked
storage subsystem, not one fixed 512-bit FP32 RAM.

## Contracts

- **Range allocation — input/output, 96-bit request and 64-bit response with
  valid/ready:** reserves a global First Element, element count, operation slot,
  profile, and returns a 16-bit range slot before arithmetic acceptance.

- **Common metadata access — input/output, up to 4 × 96-bit
  `prism_accum_addr_t` and 64-bit state:** returns valid, initialized,
  output-pending, next contributor, pending dependency, and bank status.

- **FP32 state ports — input/output, generated read/write ports carrying a
  96-bit address and 544-bit FP32 state:** serve the V1 backend with same-bank
  conflicts backpressured before acceptance.

- **Extension state ports — input/output, generated per enabled accumulator
  profile:** carry that profile's declared state width and element mask. A
  future Kulisch store can use wider BRAM/URAM words without widening FP32 or
  common metadata ports.

- **Packetizer read — input/output, one 96-bit address, fixed response metadata,
  and profile-specific numeric data:** gives finalization read-only access to
  output-pending ranges.

- **Release — input, 96 bits + valid/ready:** names operation, range, First
  Element, generation, and reason. Release waits for prior writes and
  packetizer reads.

- **Store state — output, 192 bits:** free range slots, per-profile allocation,
  bank pressure, outstanding accesses, and stale/uninitialized/ECC faults.

## Contract behavior

- Global First Element and tile index form the address; source packet Chunk
  Index is retained only by reliability and duplicate tracking.
- Common ordering metadata and numeric state commit atomically for an update.
- Abort or generation mismatch invalidates the allocation without exposing old
  numeric state to a reused slot.

## Related modules and concepts

The [`prism_accumulation_scheduler`](prism_accumulation_scheduler.md) owns
updates, and [`prism_output_packetizer`](prism_output_packetizer.md) reads final
state.
