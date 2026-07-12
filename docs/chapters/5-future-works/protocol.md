# 5.1 Protocol

Protocol 1.0 freezes object identity, management transactions, two-phase
admission, phase bitmaps, and reliable direct-link delivery. Future revisions
should extend those contracts without weakening generation safety or treating
Ethernet loss as silent success.

## Exact and Kulisch partial formats

Protocol 1.0 assigns only FP32 partials. A future exact-FP32 or Kulisch format
must define its byte layout, merge rules, special values, overflow, and payload
geometry before receiving a numeric Partial Wire Format value. Support will be
advertised through the four-field arithmetic tuple, not a separate feature bit.

## Scalable completion memory

The full phase bitmap deliberately makes duplicate suppression independent of
the active aggregation-slot window. Implementations can study banked BRAM/URAM,
external memory, compressed sparse maps, hierarchical summaries, or page-on-
demand allocation. Any optimization must preserve exact per-chunk tombstones,
constant-time completion counters, and atomic resource accounting visible during
`OP_PREPARE`.

## Congestion-aware reliability

The required `PM_OP_COL_PROGRESS` profile provides ACK, selective ACK, receive
window, and retry information. A later congestion profile could add explicit
rate hints, ECN coupling, adaptive retransmission timers, and fairness between
concurrent operations. Such policy remains separate from result payload
distribution and retains each result until every Result Path acknowledges.

Protocol 1.0 relies on endpoint/runtime deduplication of final results until
release. A future result-side receive-window profile could standardize endpoint
tombstones and acknowledgments before claiming exactly-once application
delivery.

## Authentication profiles

Version 1.0 negotiates authenticated external channels or in-protocol
authentication without selecting a cryptographic primitive that the RTL does
not implement. Future work may freeze a concrete tag, key derivation,
anti-replay sequence, rekey procedure, and data-packet authentication profile.
Formal analysis should cover forged contributor identities, stale generations,
management replay, lease takeover, and reset recovery.

## Additional collectives and routing

`REDUCE_SCATTER` has an assigned semantic code, but a switch advertises only
implemented semantics. Future profiles can define scatter ownership, segmented
tensors, non-contiguous result placement, topology changes, and additional
associative operators. Each extension still needs invariant element/chunk
geometry, explicit per-path acknowledgment, and atomic admission.

## Distributed recovery and observability

A production AM will need durable operation journals, takeover between AM
replicas, event-gap detection, telemetry for replay pressure, and coordinated
reinstallation after Device Boot ID changes. `OP_STATUS` remains authoritative;
events are an optimization. A future diagnostic schema may standardize counters
and traces without exposing implementation-private table addresses.

If Host Coordinator and AM run as separate services, their RPC also needs stable
request identity, reconnect semantics, and replay of ACTIVE, COMPLETE, RELEASED,
and terminal-error outcomes. Recovery must never synthesize a rank start grant
until the AM has re-established every target as `ACTIVE`, and must wake every
waiting rank with one consistent outcome.

## Relationship to prior systems

SHARP motivates the separation between host-side collective integration and an
aggregation manager, as well as the distinction between a reusable group, one
collective request, and bounded aggregation resources. PRISM uses those ideas as
architectural lessons only. It does not claim protocol, wire, API, management,
or transport compatibility with NVIDIA SHARP or NVLink SHARP.
