# `prism_forwarding_unit`

**Module class:** `MAIN UNIT`  

`prism_forwarding_unit` resolves whether the destination MAC names this PRISM
node and, if not, selects a transparent egress. It makes only a first-beat
decision; packet data remains in the ingress path until admission succeeds.

## Contracts

- **Parsed headers — input, 2 × 352-bit payload + valid/ready:** accepts one
  ordered header-event stream from each physical ingress. Both ports may be
  classified in the same cycle.

- **Local-address configuration — input, 128 bits:** contains two 48-bit local
  termination MACs, 8-bit forwarding mode, 8-bit enable mask, and 16 policy
  flags. The management unit updates it atomically between packets.

- **Route decisions — output, 2 × 64-bit payload + valid/ready:** returns an
  egress port and packet class to the matching ingress. `FORWARD`,
  `LOCAL_DATA`, `LOCAL_CONTROL`, `LOCAL_RESULT`, `LOCAL_PROGRESS`, and `DROP`
  have stable 8-bit class assignments in `prism_pkg.sv`. The reservation-ID
  field is zero until the ingress admission controller grants capacity.

- **Route-table extension lookup — output/input, 64-bit key and 32-bit result:**
  reserved for a later learned or configured forwarding table. In v1 it is
  tied to the deterministic two-port policy and must not add decision latency.

- **Classification event — output, 64 bits + valid/ready:** reports port,
  EtherType, opcode, selected class, selected egress, and error reason for
  counters and coverage.

## Contract behavior

- A non-PRISM frame and a non-local PRISM frame arriving on port 0 select port
  1; the corresponding traffic on port 1 selects port 0. Loopback is disabled
  in v1.
- A local MAC is checked before the PRISM opcode. Non-local PRISM packets are
  forwarded unchanged and never reach a local protocol engine.
- Unsupported or malformed local opcodes select `DROP`; they cannot fall back
  to transparent forwarding after local ownership has been established.
- The selected architecture requires spatially independent classifier lanes
  targeting `II=1`; simultaneous
  first-beat events from the two ingress ports never arbitrate for one shared
  classifier. This is an unverified throughput requirement. Atomic configuration
  replacement occurs only between accepted header events and cannot mix old and
  new policy fields.

## Related modules and concepts

The decision feeds [`prism_admission_controller`](../components/stream/prism_admission_controller.md)
inside each ingress unit. Admitted forwarded packets enter the
[`prism_egress_unit`](prism_egress_unit.md) and follow the packet-level
[forwarding rules](../../2.pipeline.md#325-forwarding-arbitration-and-gap-free-transmission).
