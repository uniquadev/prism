# `prism_fp32_output_converter`

**Module class:** `COMPONENT / ARITHMETIC`

`prism_fp32_output_converter` finalizes FP32 accumulator values as FP16, BF16,
or FP32 wire elements. Other accumulator profiles provide their own finalizer.

## Contracts

- **Conversion request — input, 536 bits + valid/ready:** sixteen FP32 lanes,
  16-bit lane mask, and 8-bit output format.

- **Encoded response — output, 589 bits + valid/ready:** encoded bytes 512,
  byte mask 64, element count 5, and status 8.

- **Conversion event — output, 32 bits + valid/ready:** format/count and
  canonicalization, overflow, underflow, inexact, or mask-error observations.

## Contract behavior

- Narrowing uses round-to-nearest, ties-to-even and canonical NaNs. FP32 output
  preserves the accumulator bit pattern.
- Values are emitted little endian; unsupported formats or invalid masks
  produce no accepted payload.

## Related modules and concepts

[`prism_output_packetizer`](../collective/prism_output_packetizer.md) packs the
encoded values using operation geometry from
[`prism_collective_context_table`](../collective/prism_collective_context_table.md).
