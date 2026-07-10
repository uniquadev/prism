# 3.3 Interfaces

Protocol 1.0 includes a transport-neutral Python host library in
`repo/traffic-gen/src/prism_protocol`. It freezes serialization, validation and
AM-side lifecycle behavior without choosing raw sockets, PCIe, AXI-Lite or a
deployment-specific control channel.

## Public AM interface

| Function | Result |
|---|---|
| `prism_query_capabilities(...)` | Static limits, feature masks, arithmetic tuples and Device Boot IDs |
| `prism_open_session(...)` | Leased Job session with one opaque cookie per switch |
| `prism_query_resources(...)` | Advisory dynamic resource snapshots |
| `prism_renew_session(...)` / `prism_close_session(...)` | Lease renewal or acknowledged teardown |
| `prism_create_group(...)` | Tree-wide staged and committed reusable group |
| `prism_group_status(...)` / `prism_destroy_group(...)` | Authoritative state or acknowledged destruction |
| `prism_prepare_operation(...)` | Tree-wide atomic resource admission with rollback on partial failure |
| `prism_commit_operation(...)` / `prism_abort_operation(...)` | Idempotent operation transition |
| `prism_operation_status(...)` / `prism_wait_operation(...)` | Polling and completion recovery |
| `prism_release_operation(...)` | Acknowledged resource release and generation eligibility |

`PrismManager` compares tree geometry and per-edge formats, validates each local
descriptor against its switch capability, tracks boot IDs, persists generation
counters when given a `GenerationStore` path, and rejects ID reuse while a
handle remains owned. Errors are `PrismError` values carrying protocol status,
message, switch and transaction identity; invalid local handles use
`InvalidHandleError`.

## Transport boundary

`ControlTransport.exchange(frames, timeout_seconds)` is the only required
deployment hook. It receives already serialized Ethernet-payload fragments and
returns response fragments. `WireSwitchClient` provides transaction allocation,
fragmentation, reassembly, exact schema validation and bounded identical retries.
The transport must preserve the target switch identity and provide frame
delivery; it must not reinterpret TLVs.

This boundary permits a later raw-Ethernet, sideband, PCIe or simulation adapter
without duplicating protocol logic. No such adapter is claimed by the current
repository.

## RTL-facing stream

For an untagged Ethernet frame on a 512-bit AXI4-Stream interface, the first beat
contains 14 Ethernet bytes, the 2-byte PRISM control word, a complete 24-byte
data/result header and 24 bytes of vector payload. `TKEEP` identifies physical
bytes and `TLAST` closes the frame; neither changes the operation-derived logical
payload length. Backpressure must retain header, payload and peer association
until the full packet is accepted.

Management and progress headers are 24 and 40 bytes respectively after the
control word. Their parser outputs must carry complete Job, group and operation
generations to every lookup, replay and response stage.

