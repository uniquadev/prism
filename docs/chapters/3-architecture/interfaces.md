# 3.3 Interfaces

!!! note "Work in progress"

    This page is intentionally only an architectural placeholder. The software
    and hardware interfaces have not yet been selected or frozen.

PRISM will eventually need to define these integration boundaries:

- **rank runtime ↔ Host Coordinator** — arrival at a collective and delivery of
  `START`, `DONE`, or a shared terminal error;
- **Host Coordinator ↔ Aggregation Manager** — request, completion observation,
  and release of a collective operation;
- **Aggregation Manager ↔ switches** — delivery of the in-band management
  transactions defined by the [protocol](protocol.md);
- **switch datapath ↔ PRISM RTL** — packet streams, backpressure, and metadata;
- **test environment ↔ traffic generator** — frames, AXI4-Stream beats, and
  captures used for verification.

The protocol chapter defines the required behavior at these boundaries without
choosing a concrete API, RPC mechanism, host transport, register interface, or
RTL port layout. Those choices will be documented here when their design begins.
