# `prism_single_control_plane`

`prism_single_control_plane` owns the one-context in-band CONTROL lifecycle for
the current SINGLE core. It is not a general tree-management engine.

## Contracts

- **CONTROL AXI stream:** receives complete frames from the frame-class router.
- **Context output:** publishes an installed, validated context only after
  `STAGE` and activates it on `COMMIT`.
- **Response AXI stream:** returns setup command status.

## Contract behavior

- Validates frame length, context fields, arithmetic tuple, endpoint bindings,
  MTU and resource limits before state changes.
- Returns status for the validated setup command. CONTROL retry and
  retransmission are outside the SINGLE experiment flow.
- Completes and releases one operation; a higher generation may reuse its slot.
  The current interface does not provide lease expiry from `millisecond_tick`.

## Related modules and concepts

- [`prism_collective_core`](prism_collective_core.md)
- [Protocol lifecycle](../../1.protocol.md)
