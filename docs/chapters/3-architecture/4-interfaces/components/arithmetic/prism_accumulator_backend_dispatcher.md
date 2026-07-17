# `prism_accumulator_backend_dispatcher`

**Module class:** `COMPONENT / ARITHMETIC`

`prism_accumulator_backend_dispatcher` routes scheduled work to the accumulator
profile selected by each operation. Backends coexist and are shared by active
operations.

## Contracts

- **Scheduled work — input, up to 4 × (192-bit metadata + 528-bit V1 payload)
  with valid/ready:** carries profile, operator, range, contributor, and
  normalized values.

- **FP32 backend — output/input, up to 4 × 1064/544-bit numeric payload plus
  192-bit metadata with valid/ready:** connects V1 state and FP32 ALU arrays.

- **Extension backends — output/input, generated per enabled profile:** reuse
  the fixed metadata and expose profile-specific numeric widths.

- **Commit — output, up to 4 × 192-bit `prism_arith_commit_t` + valid/ready:**
  reports committed updates without carrying numeric accumulator state.

- **Status — output, 64 bits:** enabled/ready profiles, outstanding tags, and
  unsupported-profile or response-routing faults.

## Contract behavior

- Profile, operator, operation generation, and range must match on response.
- A stalled backend blocks only its candidates unless a shared bank or commit
  port is the actual conflict.
- Compiled-out profiles and unsupported operators are rejected by
  `OP_PREPARE`, before datapath issue.

## Related modules and concepts

Work comes from
[`prism_accumulation_scheduler`](../collective/prism_accumulation_scheduler.md).
V1 uses [`prism_fp32_alu_array`](prism_fp32_alu_array.md) and
[`prism_accumulator_store`](../collective/prism_accumulator_store.md).
