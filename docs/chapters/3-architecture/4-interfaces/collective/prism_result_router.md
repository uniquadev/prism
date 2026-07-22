# `prism_result_router`

**Module class:** result fan-out boundary

`prism_result_router` converts one completed result chunk into a bounded stream
of destination-specific packet jobs. Route selection is separate from packet
serialization.

## Contracts

- **Completed chunk:** accepts `prism_result_chunk_meta_t` and the corresponding storage slot.
- **Route lookup:** reads the operation's chunk-range route entries.
- **Replication lookup:** reads the selected group's egress port, destination MAC, and result-path entries.
- **Packet job:** publishes one `prism_result_packet_job_t` per matching destination.
- **Reference arm:** returns the number of emitted jobs to result storage.

## Contract behavior

- Walks the bounded route table until it finds a range containing the chunk index.
- Expands the selected replication group into one job per valid entry.
- Holds each packet job stable while the downstream queue applies backpressure.
- Arms the chunk slot with the exact number of emitted jobs, including zero when no route matches.
- Does not read or modify result payload bytes.

## Related modules and concepts

- [`prism_control_executor`](../control/prism_control_executor.md)
- [`prism_result_chunk_store`](prism_result_chunk_store.md)
- [`prism_result_packetizer`](../egress/prism_result_packetizer.md)
- [Current shared contracts](../common-contracts.md)

