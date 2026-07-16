# `prism_packet_arbiter`

**Module class:** `COMPONENT / STREAM`  

`prism_packet_arbiter` chooses a conflict-free packet-level matching between
the five source rows and two physical egresses. It records ownership on packet
start and does not reconsider that grant until the accepted `tlast`.

## Contracts

- **Eligibility matrix — input, 10 bits:** one bit for every
  `source × egress` VOQ indicates that its head packet is safe to start.

- **Head attributes — input, 80 bits:** ten 8-bit records identify complete,
  cut-through-safe, management, result, pressure, and age classes used by the
  scheduling policy.

- **Egress availability — input, 2 bits:** indicates that each output buffer can
  accept a first beat. It cannot revoke an already locked grant.

- **Transfer feedback — input, 10 accepted bits + 10 `tlast` bits:** identifies
  the exact granted edge whose beat transferred and whether packet ownership
  ends in the current cycle.

- **Grant matrix — output, 10 bits:** one-hot-or-zero for each egress and each
  source. Registered lock state drives the same edge for every packet beat.

- **Arbitration event — output, 64 bits + valid/ready:** reports source, egress,
  wait-age class, packet start/end, lock state, and policy reason.

## Contract behavior

- A source row wins at most one egress and an egress grants at most one source
  in a cycle.
- V1 uses work-conserving round robin among data sources with bounded service
  for management and result packets. Priority cannot interrupt an open packet.
- Round-robin pointers change on accepted packet start, not on an unaccepted
  combinational selection.
- With continuous TX readiness, blocking by one already started packet is
  bounded by the 24-beat v1 maximum frame.

## Related modules and concepts

The scheduler consumes [`prism_voq_bank`](prism_voq_bank.md) state and controls
[`prism_stream_crossbar`](prism_stream_crossbar.md). The matching invariants are
listed in [Switch allocation](../../../2.pipeline.md#325-forwarding-arbitration-and-gap-free-transmission).
