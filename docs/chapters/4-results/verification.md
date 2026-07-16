# 4.1 Verification Evidence

This chapter records evidence after RTL exists. Before implementation, the
following interface-level obligations define the Cocotb and assertion plan.

## Protocol and geometry obligations

- Derive Input, Partial, and Output Wire Format geometry independently from
  Element Count and 1474 payload bytes; reject overflow of the 24-bit index.
- Verify maximum whole-element packing and exact `LAST_CHUNK`/payload length for
  every enabled format, including Element Count values around 368 and 737.
- For BF16 input and FP32 output, verify 737 elements become RES packets of
  368, 368, and 1 when the operation ends there. Test both range merging and
  splitting without an element crossing a packet boundary.
- Verify accumulator addresses use global First Element and cannot alias merely
  because Input, Partial, and Output streams have equal numeric Chunk Indices.
- Verify RES Chunk Index is preserved across result hops while Result Path ID
  and MAC addresses are rewritten per hop.

## Arithmetic and concurrency obligations

- Check EAGER and CONTRIBUTOR_ORDERED against independent bit-accurate FP32
  references, including NaNs, infinities, signed zero, subnormals, overflow,
  and round-to-nearest ties-to-even.
- Sustain two simultaneous FP16/BF16 ingress beats after pipeline fill with up
  to four 16-lane FP32 backend issues per cycle when dependencies are independent.
- Interleave eight active operation contexts and sixteen live ranges; ensure a
  stalled range/backend cannot corrupt or permanently starve another operation.
- Prove RAW forwarding/stall, WAW serialization, tag uniqueness, profile match,
  and stale-generation rejection. Backend commit metadata must contain no
  assumed FP32 state bits.

## Flow-control and packet obligations

- Randomize `ready` on every internal contract and TX. A stalled producer must
  hold payload stable and transfer exactly once.
- Simultaneously enqueue both ingress rows and every internal injection row,
  including all targeting one egress, and prove that distinct VOQ cells accept
  without write collision.
- Exhaust packet store, range slots, packetizer storage, VOQ, and replay
  capacity separately. Admission must roll back partial reservations and
  completed ranges must remain safely `OUTPUT_PENDING`.
- Prove packet-granular arbitration: no beat interleaving, no internal valid gap
  after start, stable TX under backpressure, and correct final `tkeep`.
- Race duplicate DATA, arithmetic commit, ACK, retry timeout, abort, and slot
  reuse; each state transition must remain idempotent and generation-safe.

## Discovery obligations

- `CAPS_QUERY` must return exactly the compiled semantic/operator masks,
  five-field arithmetic tuples, accumulator profile widths, and reliability
  features. A compiled-out backend or converter must never be advertised.
- `RESOURCE_QUERY` must reflect current free operation, range, packet, bitmap,
  and replay resources without reserving them.
- `OP_PREPARE` must reject unsupported tuples and atomically reserve only after
  deriving all three geometries and role-dependent output obligations.

Waveforms, seeds, assertion reports, synthesis utilization, timing, and achieved
initiation intervals will be linked here as implementation milestones complete.
