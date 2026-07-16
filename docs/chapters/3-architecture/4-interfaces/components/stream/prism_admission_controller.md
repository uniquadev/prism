# `prism_admission_controller`

**Module class:** `COMPONENT / STREAM`

`prism_admission_controller` converts a first-beat classification into an
atomic capacity decision. For local DATA it derives the future output burden
from operation role and the three wire geometries rather than trusting packet
fields to predict result size.

## Contracts

- **Admission candidate — input, 352-bit parsed header, 64-bit preliminary
  route, and optional 544-bit operation context with valid/ready:** carries the
  ordered first-beat decision and immutable role/geometry state.

- **Capacity state — input, 192 bits:** summarizes staging, selected VOQ,
  packet store, tracker, accumulator-range, output-pending, packetizer, replay,
  and mandatory-response availability.

- **Reservation fan-out — output/input, up to 5 × 32-bit request/response:**
  targets forwarding/local packet storage plus the bounded tracker,
  accumulator-range, and response resources selected for the packet class.

- **Output-obligation estimate — output, 96 bits:** reports derived outgoing
  class, format, First Element, maximum affected output chunks, route fan-out,
  and reservation policy for later packetization.

- **Final decision — output, 96 bits + valid/ready:** returns reservation IDs,
  selected local/forward path, operation slot, and precise drop reason.

- **Credit return — input/output, 64-bit completion and 64-bit updated state:**
  returns unused maximum-frame and tentative local-resource credits at `tlast`
  or validation failure.

## Contract behavior

- All resources promised at admission are granted together or rolled back.
  Concurrent updates to one pool serialize before any grant is visible.
- A leaf/internal DATA packet accounts for future Partial Wire Format output; a
  root/single result producer accounts for Output Wire Format and route fan-out.
  Format expansion can therefore increase packet obligations without a control
  descriptor field.
- The affected output indices and transfer count are derived from the admitted
  global interval, output elements per chunk, and route fan-out.
- Admission reserves the ability to retain an `OUTPUT_PENDING` range, not every
  future VOQ beat. Packetizer/VOQ/replay capacity is acquired when output is ready.
- Unknown physical length reserves 24 beats. Oversize input is drained without
  committing protocol or arithmetic state.

## Related modules and concepts

The controller uses [`prism_collective_context_table`](../collective/prism_collective_context_table.md)
and implements [Ingress and resource admission](../../../2.pipeline.md#324-ingress-and-resource-admission).
