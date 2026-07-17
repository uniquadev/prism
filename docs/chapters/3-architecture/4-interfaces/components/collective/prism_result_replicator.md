# `prism_result_replicator`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_result_replicator` expands one immutable RES chunk into independent
direct-transfer descriptors. It copies metadata, not numeric data, and keeps
the shared payload alive until every required route owns queue and replay state.

## Contracts

- **Replication command — input, 256-bit `prism_replica_cmd_t` +
  valid/ready:** supplies operation identity, output-stream Chunk Index,
  immutable payload handle, Replication Group ID, and flags.

- **Result-destination lookup — output/input, derived index and
  `prism_result_destination_t` + status:** enumerates egress, Result Path ID,
  next-hop type, source/destination MACs, and flags for the selected group.

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

- The parent selects a result-range route using the output-stream Chunk Index;
  this component sees only the resulting destination set. Input and partial
  DATA indices never enter either lookup.
- Admission is transactional for mandatory replicas. Backpressure holds the
  current route state and immutable handle stable without duplicating earlier
  commands.
- Destination count is two for the default two-rank ALLREDUCE and is bounded by
  `PRISM_MAX_RESULT_DESTINATIONS_PER_GROUP`; it is not a result-range count.

## Related modules and concepts

The parent is [`prism_result_delivery_unit`](../../units/prism_result_delivery_unit.md).
Serialization uses [`prism_packet_serializer`](../stream/prism_packet_serializer.md), and
retention uses [`prism_replay_cache`](../reliability/prism_replay_cache.md).
