# `prism_data_depacketizer`

**Module class:** `COMPONENT / COLLECTIVE`

`prism_data_depacketizer` removes the DATA header, aligns packed elements across
AXI beats, and emits globally addressed arithmetic tiles. It streams the packet
and never waits for the complete operation.

## Contracts

- **Accepted packet — input, 320-bit contribution descriptor and 544-bit
  context with valid/ready:** supplies packet handle, format, profile, operator,
  First Element, and element count.

- **Packet read — output/input, 32-bit command and one `prism_axis`:** consumes
  the retained packet through `tlast` while preserving beat-to-beat carry.

- **Profile conversion — output/input, aligned element bytes plus fixed
  metadata with valid/ready:** uses `prism_fp32_input_converter` in V1.

- **Arithmetic work — output, 2 × (192-bit metadata + 528-bit V1 payload) with
  valid/ready:** emits consecutive global element tiles.

- **Release/result — output, 16-bit handle and 96-bit status with
  valid/ready:** releases storage after all tiles transfer or an error ends the
  packet.

## Contract behavior

- Elements may cross AXI beats but never DATA packet boundaries.
- FP32 emits one tile per aligned beat; FP16/BF16 may emit two.
- Chunk Index is used for packet reliability only; First Element addresses
  arithmetic state.

## Related modules and concepts

Conversion uses
[`prism_fp32_input_converter`](../arithmetic/prism_fp32_input_converter.md);
work enters [`prism_accumulation_scheduler`](prism_accumulation_scheduler.md).
