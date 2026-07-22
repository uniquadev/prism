# `prism_control_reassembler`

**Module class:** CONTROL message boundary

`prism_control_reassembler` collects bounded, potentially out-of-order CONTROL
fragments that share a session cookie and transaction identifier. It emits one
ordered payload only after the message is complete.

## Contracts

- **Fragment start:** accepts a `prism_control_header_t` and the payload length for one fragment.
- **Fragment byte stream:** accepts exactly the bytes belonging to the admitted fragment.
- **Reassembled message:** publishes the canonical header, total payload length, and ordered byte stream.
- **Error result:** reports a `prism_status_e` value through an independent ready/valid channel.

## Contract behavior

- Bounds concurrent messages, fragment size, total capacity, and fragment count through elaboration parameters.
- Matches fragments by session cookie and transaction identifier while checking invariant header fields.
- Accepts duplicate fragments only when their stored content is consistent.
- Releases a message in fragment-index order after all expected fragments arrive.
- Reports malformed, conflicting, oversized, or timed-out transactions without publishing a partial request.

## Related modules and concepts

- [`prism_control_executor`](prism_control_executor.md)
- [`prism_collective_core`](../core/prism_collective_core.md)
- [Protocol](../../1.protocol.md)
- [Current shared contracts](../common-contracts.md)

