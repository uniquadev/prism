# `prism_collective_unit`

**Module class:** `MAIN UNIT`

`prism_collective_unit` accepts validated DATA, maps each packet to global
element ranges, applies it exactly once through the selected accumulator
backend and policy, and emits packetized upstream partials or locally completed
results. REDUCE and ALLREDUCE share this unit; result routes distinguish them.

## Contracts

- **Validated DATA — input, 2 × 320-bit `prism_contribution_desc_t` +
  valid/ready:** accepts independent candidates from both ingress paths with
  stream-local Chunk Index and validator-derived global First Element.

- **Packet-store access — output/input, 2 × 32-bit read command, 2 ×
  `prism_axis`, and 2 × 16-bit release handle:** reads both ingress stores in
  parallel and releases a packet only after all work is transferred or rejected.

- **Operation lookup — output/input, 2 × 176-bit request and 2 × (544-bit
  context + 8-bit status):** verifies operation generation, contributor,
  arithmetic tuple, role, and derived input/partial geometry.

- **Accumulator work/commit — internal, up to 4 × (192-bit metadata + 528-bit
  V1 work payload) and up to 4 × 192-bit commit:** normalization can expose two
  FP32 tiles per ingress cycle; scheduling and backend capacity determine issue.

- **Ready range — internal, 256-bit payload + valid/ready:** transfers a
  globally addressed completed range to finalization and packetization.

- **Packetized output — output, 512-bit partial-DATA serialization command and
  288-bit RES descriptor with valid/ready:** selects the channel required by
  the node role.

- **Collective event — output, 128 bits + valid/ready:** reports operation slot,
  global First Element, element count, accepted/duplicate/applied/output-pending
  transition, backend profile, and status.

## Contract behavior

- EAGER issues any ready dependency-free tile. CONTRIBUTOR_ORDERED issues each
  global element tile in ascending Contributor-ID order; neither policy imposes
  a whole-operation barrier.
- Up to eight active operations may interleave in the default build. They share
  backend bandwidth and sixteen live ranges.
- Input DATA Chunk Index is never copied to generated partial or RES. The
  output packetizer derives outgoing indices and may merge or split input ranges.

## Related modules and concepts

The unit composes the [collective components](../index.md#collective-and-result-components)
and [arithmetic components](../index.md#arithmetic-components). Its state
transitions are defined in [Collective processing](../../2.pipeline.md#326-collective-processing).
