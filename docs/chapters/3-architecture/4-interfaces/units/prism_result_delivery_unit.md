# `prism_result_delivery_unit`

**Module class:** `MAIN UNIT`

`prism_result_delivery_unit` turns one immutable, output-format RES chunk into
one or more reliable direct transfers. REDUCE selects its configured result
route; ALLREDUCE enumerates all installed destinations. It also accepts a
validated incoming RES and originates the next hop on a result-delivery node.

## Contracts

- **Locally packetized RES — input, 288-bit `prism_res_chunk_desc_t` +
  valid/ready:** accepts an Output Wire Format payload with derived RES Chunk
  Index and immutable payload handle from the collective packetizer.

- **Validated incoming RES — input, 384-bit packet descriptor + valid/ready:**
  accepts one closed, generation-checked output-format packet from ingress.

- **Operation and route lookup — output/input, 32-bit slot request, 544-bit
  operation context, and repeated 128-bit routes + 8-bit status:** obtains the
  semantic and disjoint RES Chunk Index route mapping atomically.

- **Replication command — output, 256-bit `prism_replica_cmd_t` +
  valid/ready:** names output Chunk Index, immutable payload, route range, and
  RES flags.

- **Incoming-result access — output/input, 32-bit read command, one
  `prism_axis`, and 16-bit release handle:** retains received bytes while
  creating downstream ownership.

- **Reliability registration/accept event — output, 256-bit replay command per
  replica and 256-bit safe-receive event with valid/ready:** establishes each
  direct transfer and acknowledges safe incoming ownership independently.

- **Delivery event — output, 96 bits + valid/ready:** reports operation slot,
  RES Chunk Index, requested/admitted/acknowledged replica counts, semantic,
  and terminal status.

## Contract behavior

- REDUCE requires the operation's configured destination set; ALLREDUCE covers
  every participant. Arithmetic is identical and does not special-case the
  semantic.
- Each replica preserves the RES Chunk Index because Output Wire Format is the
  same on every result hop, while Result Path ID, egress, and MAC addresses are
  hop-local.
- Deduplication occurs before fan-out. A duplicate may regenerate PROGRESS but
  never creates another downstream transfer.
- One immutable payload remains owned until every mandatory replica has queue
  and replay ownership. Slow paths cannot modify or retire another replica.

## Related modules and concepts

Payloads originate in
[`prism_output_packetizer`](../components/collective/prism_output_packetizer.md),
copies in [`prism_result_replicator`](../components/collective/prism_result_replicator.md),
and ACK/retry state in [`prism_reliability_unit`](prism_reliability_unit.md).
