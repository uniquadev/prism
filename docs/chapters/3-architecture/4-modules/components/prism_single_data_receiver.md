# `prism_single_data_receiver`

`prism_single_data_receiver` validates a complete NumberGroup DATA frame before
it advances interval ownership or emits arithmetic work.

## Contracts

- **Ingress AXI stream:** accepts rank frames with explicit `tkeep` and `tlast`.
- **Installed context:** binds logical endpoints, contributor IDs, packet
  limits, formats and the current operation generation.
- **Tile output:** carries consecutive values with their global first position;
  tile boundaries do not change the arithmetic identity.

## Contract behavior

- Checks descriptor counts, payload length, padding, frame bounds and binding
  before the validated reader can issue values.
- Tracks interval coverage and LAST per contributor; overlapping intervals do
  not apply a second contribution.
- Derives the active element window from the configured MTU. Duplicate or
  overlapping element intervals cannot issue arithmetic twice. DATA
  retransmission and PROGRESS acknowledgment are outside the SINGLE contract.

## Related modules and concepts

- [Datapath contracts](../datapath-contracts.md)
