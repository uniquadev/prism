# `prism_fp32_input_converter`

**Module class:** `COMPONENT / ARITHMETIC`

`prism_fp32_input_converter` converts aligned FP16, BF16, or FP32 wire values
to the FP32 accumulator profile. Other accumulator profiles use separate
converters.

## Contracts

- **Aligned input — input, 590 bits + valid/ready:** element bytes 512, byte
  mask 64, wire format 8, and element count 6.

- **Normalized output — output, 1088-bit `prism_normalized_pair_t` +
  valid/ready:** up to two 16-element FP32 tiles, masks, tile count, and status.

- **Conversion event — output, 32 bits + valid/ready:** format/count and
  NaN/subnormal/error observations for coverage.

## Contract behavior

- FP16 converts exactly; BF16 extends its fraction with zeros; FP32 is
  bit-preserving except for the protocol's canonical NaN rule.
- FP32 produces one tile, while FP16/BF16 may produce two. A future pipeline
  must declare fixed latency and targets `II=1` when that converter is compiled.

## Related modules and concepts

[`prism_data_depacketizer`](../collective/prism_data_depacketizer.md) supplies
aligned values. Formats are defined in
[Wire formats, accumulator profiles, and policies](../../../1.protocol.md#wire-formats-accumulator-profiles-and-policies).
