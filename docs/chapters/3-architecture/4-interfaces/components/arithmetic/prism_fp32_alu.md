# `prism_fp32_alu`

**Module class:** `COMPONENT / ARITHMETIC`

`prism_fp32_alu` is one scalar, pipelined FP32 arithmetic lane. The request
carries an operator opcode; V1 implements only `SUM`, while the interface can
accept later FP32 operators without renaming the module.

## Contracts

- **Operation request — input, 72 bits + valid/ready:** two 32-bit operands and
  one 8-bit Reduction Operator.

- **Result — output, 45 bits + valid/ready:** FP32 result, 8-bit operation
  status, and five IEEE-style exception flags.

- **Global flush — input, 1 bit:** invalidates the pipeline only during reset or
  a whole-backend fatal drain.

## Contract behavior

- `SUM` uses binary32 round-to-nearest, ties-to-even, gradual underflow,
  canonical NaN, and the signed-zero rules defined by Protocol 1.0.
- An unsupported opcode returns `UNSUPPORTED_OPERATOR` with defined-zero result;
  normal datapath operation rejects it earlier through capability checking.
- The planned implementation must declare fixed latency and targets `II=1`.
  Output backpressure cannot overwrite an unconsumed result.
- An operation abort does not flush this shared pipeline; generation checks
  discard its returning work without affecting other operations.

## Related modules and concepts

Sixteen lanes form [`prism_fp32_alu_array`](prism_fp32_alu_array.md). Normative
numeric behavior is in the
[Arithmetic support boundary](../../../1.protocol.md#arithmetic-support-boundary).
