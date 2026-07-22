# `prism_range_scheduler`

**Module class:** collective reduction boundary

`prism_range_scheduler` owns the in-flight state for global element ranges. It
combines each expected contributor exactly once and publishes a range only
after its lane coverage is complete.

## Contracts

- **Converted tile:** accepts metadata, FP32 lanes, Kulisch deposits, classification masks, width selection, and conversion status.
- **Reduced tile:** publishes `prism_tile_meta_t`, reduced binary32 lanes, lane keep bits, and the sticky accumulation-warning flag.
- **Capacity:** bounds simultaneous range contexts and contributors through `RANGES` and `CONTRIBUTORS`.

## Contract behavior

- Matches a tile to its operation slot and global range index or allocates a free range context.
- Tracks the received lane mask separately for every contributor.
- Applies FP32_ARRIVAL contributions as accepted, preserves Contributor ID
  order for FP32_ORDERED, and uses fixed-point accumulation for the Kulisch path.
- For a complete two-contributor FP32_ORDERED range, submits the ordered pair
  directly to all 16 FP32 lanes instead of serializing a separate fold step.
- Handles zero, NaN, positive infinity, and negative infinity consistently across contributors.
- Saturates a selected Kulisch width on overflow and keeps `m_accumulation_inexact` sticky.
- Backpressures new tiles when the required range context is busy or unavailable.

## Related modules and concepts

- [`prism_input_conversion_stage`](../conversion/prism_input_conversion_stage.md)
- [`prism_result_chunk_store`](prism_result_chunk_store.md)
- [Pipeline](../../2.pipeline.md)
- [Current shared contracts](../common-contracts.md)
