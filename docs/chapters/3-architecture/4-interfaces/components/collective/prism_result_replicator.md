# `prism_result_replicator`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_result_replicator` expands one immutable RES chunk into independent
direct-transfer descriptors. It copies metadata, not numeric data, and keeps
the shared payload alive until every required route owns queue and replay state.

## Contracts

- **Replication command — input, 256-bit `prism_replica_cmd_t` +
  valid/ready:** supplies operation identity, output-stream Chunk Index,
  immutable payload handle, route base/count, and flags.

- **Route lookup — output/input, 32-bit index and 128-bit route + 8-bit
  status:** reads egress, Result Path ID, source/destination MACs, and flags.

- **Replica reservations — output/input, up to 2 × 32-bit request/response in
  the default build:** reserves queue and replay resources separately per
  destination. Larger builds derive the requester count from port resources,
  not collective semantics.

- **Packet command — output, 512-bit `prism_packet_serialize_cmd_t` + valid/ready:**
  emits one RES serialization command per admitted route.

- **Replay registration — output, 256-bit `prism_replay_cmd_t` +
  valid/ready:** binds the retained packet to its direct Result Path and retry
  policy.

- **Completion — output, 96 bits + valid/ready:** reports operation slot,
  output Chunk Index, requested/admitted routes, failed route, payload handle,
  and status.

## Contract behavior

- Route ranges use the output-stream Chunk Index namespace derived during
  `OP_PREPARE`; input and partial DATA indices never enter this lookup.
- Admission is transactional for mandatory replicas. Backpressure holds the
  current route state and immutable handle stable without duplicating earlier
  commands.
- Route count is two for default two-rank ALLREDUCE but remains a 16-bit
  installed-operation value.

## Related modules and concepts

The parent is [`prism_result_delivery_unit`](../../units/prism_result_delivery_unit.md).
Serialization uses [`prism_packet_serializer`](../stream/prism_packet_serializer.md), and
retention uses [`prism_replay_cache`](../reliability/prism_replay_cache.md).
