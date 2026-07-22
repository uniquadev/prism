# `prism_data_depacketizer`

**Module class:** DATA framing boundary

`prism_data_depacketizer` removes Ethernet and PRISM DATA headers from a
validated frame and presents its payload as lane-aligned arithmetic tiles.

## Contracts

- **Validated frame:** accepts `prism_frame_desc_t`, `prism_ingress_context_t`, and their buffered AXI frame.
- **Arithmetic tile:** publishes `prism_tile_meta_t`, 32-bit lane containers, and a per-lane element mask.
- **Flow control:** independently handshakes the frame descriptor and tile stream while keeping them associated.

## Contract behavior

- Uses the validated input format to determine the number of bytes per element.
- Buffers up to three AXI beats so the 40-byte prefix does not fragment every
  later 64-byte payload tile.
- Computes each tile's global first-element index from the chunk index and payload progress.
- Emits contiguous, lane-zero-aligned tiles and marks only populated lanes.
- Carries operation, group, contributor, format, width, route, and warning metadata into every tile.
- Drains the remainder of a frame when no further arithmetic tile can be emitted.

## Related modules and concepts

- [`prism_ingress_port`](../ingress/prism_ingress_port.md)
- [`prism_input_conversion_stage`](../conversion/prism_input_conversion_stage.md)
- [`prism_range_scheduler`](prism_range_scheduler.md)
- [Current shared contracts](../common-contracts.md)
