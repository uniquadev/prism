# `prism_result_chunk_store`

**Module class:** result lifetime boundary

`prism_result_chunk_store` assembles converted result tiles into protocol-sized
chunks and owns their payload memory until every routed packet job releases its
reference.

## Contracts

- **Converted result tile:** accepts tile metadata, result element bits, lane keep bits, and accumulation status.
- **Completed chunk:** publishes `prism_result_chunk_meta_t` and its storage slot to the result router.
- **Reference arm:** accepts the number of packet jobs that will read a completed slot.
- **Read ports:** serve payload data and report whether the selected slot is armed.
- **Release ports:** decrement the slot reference count after packet transmission.
- **Operation completion:** reports the operation slot after all of its result chunks complete their lifetime.

## Contract behavior

- Maps global element indices to protocol chunk indices and byte offsets.
- Publishes a chunk only after every expected element has been written.
- Keeps an armed chunk immutable while packetizers read it.
- Frees a slot only after all armed references have been released.
- Supports a tile crossing at most two adjacent result chunks.

## Related modules and concepts

- [`prism_range_scheduler`](prism_range_scheduler.md)
- [`prism_result_router`](prism_result_router.md)
- [`prism_result_packetizer`](../egress/prism_result_packetizer.md)
- [Current shared contracts](../common-contracts.md)

