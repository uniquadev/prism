# `prism_output_range_tracker`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_output_range_tracker` converts committed accumulator tiles into exactly
one ready event for each globally addressed output range. It is independent of
input packet boundaries: contributor coverage is recorded by global element
position, and the outgoing wire format later determines packet boundaries.

## Contracts

- **Arithmetic commit — input, up to 4 × 192-bit `prism_arith_commit_t` + valid/ready:**
  records one backend tile that committed for an operation, range, and
  contributor.

- **Operation geometry — input, 544-bit `prism_operation_ctx_t`:** supplies
  local contributor count, accumulator profile, role, Element Count, and the
  derived Partial and Output Wire Format geometries.

- **Coverage-state access — output/input, 96-bit range address and
  parameterized contributor bitmap/state:** atomically marks committed element
  tiles. The implementation may use dense bitmaps or tagged counters, but a
  duplicate commit cannot advance readiness twice.

- **Ready range — output, 256-bit `prism_ready_range_t` + valid/ready:** names a
  contiguous global element interval, backend handle, outgoing format, and
  whether the node must emit upstream DATA or final RES.

- **Output-retirement acknowledgment — input, 96 bits + valid/ready:** names
  operation slot, range slot, global First Element, and outcome. Successful
  enqueue/replay ownership or explicit abort releases the tracked state.

- **Tracker state — output, 128 bits:** reports free/active/output-pending range
  slots, coverage conflicts, duplicate commits, and retirement faults.

## Contract behavior

- Readiness requires every configured local contributor to have committed every
  valid element in the interval. It never relies on one DATA Chunk Index being
  numerically equal to an output Chunk Index.
- `OUTPUT_PENDING` is set before the ready-range transfer. It remains set while
  finalization, packetization, injection, or replay registration is
  backpressured.
- Independent ranges may complete concurrently; packetization may combine or
  split them according to outgoing geometry.

## Related modules and concepts

Commits originate in
[`prism_accumulation_scheduler`](prism_accumulation_scheduler.md), and ready
ranges feed [`prism_output_packetizer`](prism_output_packetizer.md). See
[Range completion and output re-packetization](../../../2.pipeline.md#range-completion-and-output-re-packetization).
