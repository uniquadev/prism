# `prism_ingress_port`

**Module class:** per-port ingress boundary

`prism_ingress_port` turns one external AXI frame stream into a validated PRISM
frame stream. Parsing, state lookup, and validation remain separate operations
inside the module.

## Contracts

- **Ingress AXI stream:** accepts 512-bit Ethernet beats with `tkeep`, `tlast`, `tuser`, and ready/valid flow control.
- **Operation lookup:** requests the operation descriptor and selected accumulator width for a parsed operation key.
- **Contributor lookup:** resolves the contributor binding associated with the accepted frame.
- **Validated descriptor:** publishes `prism_frame_desc_t`, packet class, status, and `prism_ingress_context_t` together.
- **Buffered frame stream:** replays the exact accepted frame alongside the validated descriptor.

## Contract behavior

- Buffers complete frames before exposing them downstream.
- Parses the fixed prefix before requesting control-table state.
- Validates frame length, `tkeep`, addressing, operation state, contributor binding, and payload geometry.
- Holds descriptor and stream state until both downstream contracts accept the frame.
- Uses `PORT_INDEX` and the local MAC vector to enforce the per-port destination contract.

## Related modules and concepts

- [`prism_collective_core`](../core/prism_collective_core.md)
- [`prism_data_depacketizer`](../collective/prism_data_depacketizer.md)
- [`prism_control_executor`](../control/prism_control_executor.md)
- [Current shared contracts](../common-contracts.md)
