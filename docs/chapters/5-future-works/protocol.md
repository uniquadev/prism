# 5.1 Protocol work not implemented in RTL

## Lossless partial representation

Protocol 1.0 assigns FP32 to switch-to-switch partial DATA. This rounds a local
Kulisch result at every switch boundary. A future exact tree profile needs a
frozen representation, byte order, chunk geometry, exceptional-value policy,
capability record, parser, packetizer, CCL codec, PCAP decoder, and Wireshark
fields before receiving a numeric registry value.

## Hop reliability

PROGRESS, selective acknowledgements, replay identities, retry timing, and
window semantics are documented and modeled in software but have no current RTL
engine. An implementation must bound bitmap/replay storage, define acceptance
and release events, handle duplicates idempotently, and prove forward progress
under backpressure and packet loss.

## Arithmetic status

The laboratory `ACCUMULATION_INEXACT` bit reports insufficient accumulator
capacity. Further exception bits must not be assigned without defining sticky
scope, partial/result propagation, rechunking, old-receiver behavior, and
endpoint observability.

## Additional collectives and operators

An enum value alone is not a specification. Every new operator requires exact
input/output semantics, ordering, rounding, exceptional values, state bound,
capability compatibility, and bit-exact reference tests. A dot product, for
example, requires the product-width Kulisch bound rather than the scalar SUM
bound used by the current implementation.

## Authentication and distributed recovery

Authentication profiles, key ownership, topology-wide rollback, observability,
and fault containment remain outside the current implementation. They should
be designed together with their trust boundary and resource-exhaustion policy,
not added as isolated flags.
