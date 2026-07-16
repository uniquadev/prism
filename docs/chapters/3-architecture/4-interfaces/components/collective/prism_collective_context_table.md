# `prism_collective_context_table`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_collective_context_table` stores committed group topology and operation
state. The unified table avoids duplicating long-lived contributor bindings
while keeping group and operation validity independently atomic.

## Contracts

- **Context update — input, 608-bit payload + valid/ready:** stages, commits,
  invalidates, or releases one 544-bit operation context.

- **Group updates — input, 128-bit records + valid/ready:** installs
  Contributor bindings, upstream action, and replication entries under a group
  generation.

- **Operation updates — input, 128-bit records + valid/ready:** installs result
  routes and retry policy under an operation generation.

- **Lookups — input/output, 5 × 176-bit request and 5 × (544-bit context +
  8-bit status) with valid/ready:** serves ingress validation, collective,
  result delivery, and reliability.

- **Route lookup — input/output, 32-bit slot/index and 128-bit route + 8-bit
  status:** iterates committed output routes.

- **Reference update — input, 64 bits + valid/ready:** prevents reuse while
  packets, accumulator ranges, or output payloads still reference a context.

- **Status — output, 128 bits:** free/active counts, references, commit epoch,
  and consistency faults.

## Contract behavior

- Full handles and generations are compared; stale packets never hit reused
  entries.
- Staged writes become visible atomically. Group state may be reused by several
  operations without copying its contributor table.
- `OP_PREPARE` derives all three stream geometries and accepts only advertised
  arithmetic tuples.

## Related modules and concepts

[`prism_management_unit`](../../units/prism_management_unit.md) is the only
writer. Datapath clients include
[`prism_packet_validator`](../stream/prism_packet_validator.md) and
[`prism_collective_unit`](../../units/prism_collective_unit.md).
