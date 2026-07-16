# `prism_management_unit`

**Module class:** `MAIN UNIT`

`prism_management_unit` is the sole writer of session, group, contributor, and
operation configuration. It also implements the mandatory discovery path:
`CAPS_QUERY` and `RESOURCE_QUERY` report what this synthesized bitstream can
execute and what it can currently admit.

## Contracts

- **Configuration request/response — input/output, 104/72-bit payload +
  valid/ready:** exposes capabilities, resources, status, counters, staging,
  commit, abort, and release through the shell register adapter.

- **Closed CONTROL/read/release — input, 384-bit descriptor; output/input,
  2 × 32-bit read, 2 × `prism_axis`, and 2 × 16-bit release:** reassembles and
  validates transactions from either ingress before any active-state change.

- **Operation-context update — output, 608-bit `prism_context_update_t` +
  valid/ready:** commits one complete 544-bit context with internally derived
  input, partial, and output geometries.

- **Contributor, result-route, retry updates — output, 128 bits each +
  valid/ready:** atomically installs peer bindings, RES route ranges, and direct
  reliability policy with the operation.

- **Capability source — input, 256 bits plus repeated 64-bit tuple/profile
  entries:** receives elaborated limits, enabled collective/operator masks,
  supported five-field arithmetic tuples, accumulator-profile widths, and
  reliability features directly from `prism_pkg.sv`/backend presence.

- **Dynamic resource snapshot — input, 256 bits:** reports free active
  operation contexts, live accumulator ranges, packet/replay storage, phase
  bitmap state, route entries, and management staging.

- **Response serialization — output, 512-bit command plus payload stream with
  valid/ready:** sends CONTROL responses/events to `prism_packet_serializer`.

- **Lifecycle event — input, 128 bits + valid/ready:** consumes operation,
  output-range, result-ACK, retry-failure, and abort transitions and is the only
  writer of operation lifecycle state.

## Contract behavior

- `CAPS_RESPONSE` is built from compiled constants and enabled backend ports;
  it cannot advertise unimplemented tuples or profiles.
- `RESOURCE_RESPONSE` is observational and reserves nothing. `OP_PREPARE`
  validates a tuple, derives all three geometries, and reserves atomically.
- The default implementation supports eight simultaneously active operations
  sharing sixteen live ranges and the arithmetic backends.
- CONTROL fragments are all validated before commit. Partial, conflicting,
  timed-out, or over-capacity transactions expose no active state.

## Related modules and concepts

Active state resides in
[`prism_collective_context_table`](../components/collective/prism_collective_context_table.md).
See [Capability, resource, and allocation vectors](../../1.protocol.md#normative-registries-and-setup-records)
and [PRISM Parameters](../../4.parameters.md).
