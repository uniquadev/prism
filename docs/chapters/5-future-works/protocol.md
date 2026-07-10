# 5.1 Protocol

Protocol 1.0 freezes object identity, management transactions, two-phase
admission, phase bitmaps and reliable hop-by-hop delivery. Future revisions
should extend those contracts without weakening generation safety or treating
Ethernet loss as silent success.

## Exact partials across a hierarchy

The most important arithmetic extension is a lossless partial-accumulator wire
format. A local exact accumulator serialized as FP32 rounds at every tree level;
it cannot produce a globally exact, tree-independent reduction. A future
`EXACT_PARTIAL_WIRE` profile must specify representation width, normalization,
special-value flags, overflow, merge rules, payload geometry and capability
negotiation before a multi-level exact tuple can be advertised.

## Scalable completion memory

The full phase bitmap deliberately makes duplicate suppression independent of
the active aggregation-slot window. Implementations can study banked BRAM/URAM,
external memory, compressed sparse maps, hierarchical summaries or page-on-
demand allocation. Any optimization must preserve exact per-chunk tombstones,
constant-time completion counters and atomic resource accounting visible during
`OP_PREPARE`.

## Congestion-aware reliability

The required `PM_OP_COL_PROGRESS` profile provides ACK, selective ACK, receive
window and retry information. A later congestion profile could add explicit
rate hints, ECN coupling, adaptive retransmission timers and fairness between
concurrent operations. Such policy must remain separate from result payload
distribution and must retain each result until every Result Path acknowledges.

## Authentication profiles

Version 1.0 negotiates authenticated external channels or in-protocol
authentication without selecting a cryptographic primitive that the RTL does
not implement. Future work may freeze a concrete tag, key derivation,
anti-replay sequence, rekey procedure and data-packet authentication profile.
Formal analysis should cover forged contributor identities, stale generations,
management replay, lease takeover and reset recovery.

## Additional collectives and routing

`ALLREDUCE` and `REDUCE_SCATTER` have assigned semantic codes, but a switch may
advertise only implemented semantics. Future profiles can define scatter
ownership, segmented tensors, non-contiguous result placement, topology changes,
and additional associative operators. Each extension still needs invariant
element/chunk geometry, explicit per-path acknowledgment and atomic admission.

## Distributed recovery and observability

A production AM will need durable operation journals, takeover between manager
replicas, event-gap detection, telemetry for replay pressure and coordinated
reinstallation after Device Boot ID changes. The authoritative recovery path
remains `OP_STATUS`; events are an optimization. A future diagnostic schema may
standardize counters and traces without exposing implementation-private table
addresses.

## Relationship to prior systems

SHARP motivates the conceptual separation between a job, a reusable collective
group, one collective request and bounded aggregation resources. PRISM uses
that separation as an architectural lesson only. It does not claim protocol,
wire, API, management or transport compatibility with NVIDIA SHARP or NVLink
SHARP.
