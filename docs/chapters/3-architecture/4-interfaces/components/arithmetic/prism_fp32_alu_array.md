# `prism_fp32_alu_array`

**Module class:** `COMPONENT / ARITHMETIC`

`prism_fp32_alu_array` applies one operator to sixteen FP32 element pairs in
parallel. V1 instantiates four arrays so dual-port FP16/BF16 input expansion can
issue four normalized FP32 tiles per cycle.

## Contracts

- **Array request — input, 1064 bits + valid/ready:** operand A 512, operand B
  512, active-element mask 16, scheduler tag 16, and Reduction Operator 8.

- **Array response — output, 544 bits + valid/ready:** result lanes 512,
  unchanged tag 16, and per-lane status summary 16.

- **Global flush — input, 1 bit:** invalidates every in-flight request only for
  reset or whole-backend fatal drain.

## Contract behavior

- The opcode is broadcast to all active lanes. Inactive lanes have no
  architectural effect.
- Every lane transfers atomically with the same latency; each array has `II=1`.
- Tags and results remain stable under backpressure and are never reconstructed
  from numeric data.
- Operation abort relies on tagged response suppression and does not flush work
  belonging to other operations.

## Related modules and concepts

The array instantiates sixteen [`prism_fp32_alu`](prism_fp32_alu.md) lanes and
connects to
[`prism_accumulator_backend_dispatcher`](prism_accumulator_backend_dispatcher.md).
