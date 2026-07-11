# PRISM host protocol library

This package provides the canonical PRISM Protocol 1.0 numeric assignments,
network-byte-order serializers/parsers, pure resource and reliability models,
and transport-neutral multi-switch Aggregation Manager helpers.

The host/runtime layer also provides a SHARP-like `PrismHostCoordinator`. Ranks
arrive through a deployment-specific host channel; the final arrival asks the AM
to prepare and commit the complete switch tree. Per-rank start grants are made
visible atomically only after every switch reports `ACTIVE`. A grant contains the
wire identity, leaf destination, contributor binding, chunk geometry, formats,
and the leaf's actual receive-window admission. The coordinator and AM may be
objects in one process or separated by an RPC proxy without changing Protocol
1.0.

After activation, `wait_operation()` observes tree-wide `COMPLETE` and retires
the grants; `release_operation()` waits for acknowledged cleanup on every
switch. The embedding runtime can then resolve every rank call as DONE, or
deliver the shared terminal error on failure.

The package models rank rendezvous, result membership, grants, completion, and
release, but deliberately contains no coordinator RPC, coordinator-to-rank
transport, raw-socket adapter, or other deployment-specific network I/O.

Run the tests with:

```powershell
uv run python -m unittest discover -s tests -v
```
