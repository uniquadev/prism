# 5.1 Protocol

## Authentication profiles

Version 1.0 negotiates authenticated external channels or in-protocol
authentication without selecting a cryptographic primitive that the RTL does
not implement. Future work may freeze a concrete tag, key derivation,
anti-replay sequence, rekey procedure and data-packet authentication profile.
Formal analysis should cover forged contributor identities, stale generations,
management replay, lease takeover and reset recovery.

## Additional collectives and routing

`REDUCE_SCATTER` has assigned semantic codes, but a switch may
advertise only implemented semantics. Future profiles can define scatter
ownership, segmented tensors, non-contiguous result placement, topology changes,
and additional associative operators. Each extension still needs invariant
element/chunk geometry, explicit per-path acknowledgment and atomic admission.
