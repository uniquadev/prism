# `prism_control_executor`

**Module class:** control-plane state boundary

`prism_control_executor` dispatches one fully staged typed request to the owner
of session, group, or operation state. It also exposes the read-only lookup
ports used by ingress validation and result routing.

## Contracts

- **Typed request:** accepts `prism_control_request_t` plus its contributor, replication, and result-route records.
- **Control result:** publishes one `prism_control_result_t` for response encoding.
- **Ingress lookups:** resolves operation state and contributor bindings without transferring table ownership.
- **Result lookups:** resolves result routes and replication entries for the router.
- **Completion event:** accepts an operation-slot completion notification from result storage.
- **Timebase:** consumes `millisecond_tick` for session lease state.

## Contract behavior

- Directs each command to exactly one state owner or to the immediate-query path.
- Makes staged group and operation changes visible only through their defined commit operations.
- Preserves one result per accepted request under downstream backpressure.
- Centralizes table access so datapath modules do not mutate control state directly.
- Applies the configured session, group, operation, contributor, route, and compiled-width bounds.

## Related modules and concepts

- [`prism_control_reassembler`](prism_control_reassembler.md)
- [`prism_ingress_port`](../ingress/prism_ingress_port.md)
- [`prism_result_router`](../collective/prism_result_router.md)
- [Protocol](../../1.protocol.md)
- [Current shared contracts](../common-contracts.md)
