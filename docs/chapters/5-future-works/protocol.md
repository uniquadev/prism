# 5.1 Protocol

The following points are intentionally outside the first MiniSharp thesis
protocol.

## Reliable completion and aborts

MiniSharp v0.1 does not define `COL_ABORT`, acknowledgments, negative
acknowledgments, retransmission, or timeout-driven recovery packets. Malformed
packets, duplicate contributions, missing routes, unsupported opcodes, and other
invalid conditions are reported through debug-visible or register-visible
counters.

A production protocol could add:

- setup acknowledgments or status responses;
- explicit collective abort messages;
- timeout policy and AM-driven cleanup;
- retry or replay semantics for non-lossless fabrics;
- per-context completion notifications.

## Reduce-scatter

The result route table is already chunk-range based, so `REDUCE_SCATTER` can be
added without replacing the result-dissemination model. The AM would install
different result routes for different chunk ranges, sending each range only to
the branch that owns it.

The first thesis protocol keeps `REDUCE_SCATTER` out of scope to focus on
`REDUCE` and `ALLREDUCE`.

## Dynamic vector length

The baseline protocol obtains vector length from the installed collective
context. A future revision could carry vector size or element count in the first
data packet of an operation, but this requires additional rules for out-of-order
chunks, context activation, and operation-instance lifetime.

## Control-plane transport

The logical Aggregation Manager interface is independent from its transport.
Future implementations may map the same setup records to:

- AXI-Lite;
- PCIe BAR registers;
- firmware calls;
- a software control-plane API;
- a secure management network.

## Security and admission control

In-band setup is useful for simulation and FPGA bring-up, but it is not a secure
production control plane. A production deployment would need authentication,
authorization, filtering, and replay protection for setup records.

## Packet-size profiles

The current protocol assumes standard non-jumbo Ethernet payloads. Jumbo-frame
profiles and MTU negotiation are future work.

## Topology discovery

The first prototype assumes that the AM is given topology and rank-placement
information. A future topology explorer could discover switch identities, local
ports, reachable ranks, and parent/child relationships before installing
collective contexts.
