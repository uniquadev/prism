# `prism_input_conversion_stage`

**Module class:** arithmetic representation boundary

`prism_input_conversion_stage` converts one typed input tile into the
representation selected for its operation. The scheduler therefore consumes a
uniform tile contract instead of implementing wire-format conversion.

## Contracts

- **Wire tile:** accepts `prism_tile_meta_t`, 32-bit lane containers, lane keep bits, and the selected Kulisch width index.
- **FP32 representation:** publishes canonical binary32 lanes for the ordered floating-point path.
- **Kulisch representation:** publishes signed fixed-point deposits at the maximum compiled width.
- **Classification:** publishes finite, zero, zero-sign, NaN, infinity, and deposit-overflow masks with the same tile.
- **Status:** reports an unsupported format through `m_format_error`.

## Contract behavior

- Selects the binary32 path or one compiled Kulisch converter from the accumulator profile.
- Registers metadata and width selection at the conversion boundary.
- Preserves inactive lanes through the element-keep mask.
- Keeps readiness independent of unregistered input metadata to avoid a combinational selection loop.
- Publishes metadata, numeric representation, classifications, and status atomically.

## Related modules and concepts

- [`prism_data_depacketizer`](../collective/prism_data_depacketizer.md)
- [`prism_range_scheduler`](../collective/prism_range_scheduler.md)
- [Parameters](../../4.parameters.md)
- [Current shared contracts](../common-contracts.md)

