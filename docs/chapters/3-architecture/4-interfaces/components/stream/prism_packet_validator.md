# `prism_packet_validator`

**Module class:** `COMPONENT / STREAM`

`prism_packet_validator` proves that one closed local packet matches its direct
stream geometry and installed operation before any stateful engine sees it.

## Contracts

- **Closed packet — input, 384-bit descriptor + valid/ready:** supplies frame
  length, class, ingress, packet handle, and first-header image.

- **Packet read — output/input, 32-bit command and one `prism_axis`:** reads
  bytes needed for exact header, bitmap, TLV, payload, and reserved-field checks.

- **Operation lookup — output/input, 176-bit request and 544-bit context +
  8-bit status:** validates full generation and peer binding and obtains all
  three derived stream geometries.

- **Validated DATA — output, 320-bit `prism_contribution_desc_t` +
  valid/ready:** includes source-format-local Chunk Index plus derived global
  First Element and Elements in Packet.

- **Validated RES/CONTROL/PROGRESS — output, 384/384/512-bit descriptor +
  valid/ready:** routes each completely checked non-DATA class to its owner.

- **Validation result — output, 96 bits + valid/ready:** reports handle, class,
  status/reason, selected geometry, checked bytes, and release action.

## Contract behavior

- DATA received by `LEAF` or `SINGLE` roles comes from bound endpoint ranks and
  selects Input Wire Format geometry. DATA received by `INTERNAL` or `ROOT`
  roles comes from bound child switches and selects Partial Wire Format
  geometry. RES always selects Output Wire Format geometry.
- Validation derives expected Chunk Index range, `LAST_CHUNK`, First Element,
  whole-element payload length, and final packet length. Ethernet padding is
  never numeric data.
- Unadvertised arithmetic tuples, wrong roles, stale generations, or derived
  ranges beyond Element Count are rejected before a duplicate, accumulator, or
  replay update.
- A rejection emits one status and releases ownership exactly once.

## Related modules and concepts

Valid DATA proceeds to
[`prism_contribution_tracker`](../collective/prism_contribution_tracker.md), RES
to [`prism_result_delivery_unit`](../../units/prism_result_delivery_unit.md),
and other classes to their protocol units.
