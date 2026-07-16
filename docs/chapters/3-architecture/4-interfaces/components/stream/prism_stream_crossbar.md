# `prism_stream_crossbar`

**Module class:** `COMPONENT / STREAM`  

`prism_stream_crossbar` is the registered data mux between VOQ heads and output
buffers. It contains no route or fairness policy; it obeys the arbiter's locked
grant and returns ready only to the selected queue edge.

## Contracts

- **Candidate matrix — input, 10 × `prism_axis`:** five source candidates for
  each of two egress columns. Non-granted candidates observe `tready=0`.

- **Grant matrix — input, 10 bits:** selects at most one candidate for each
  output and at most one egress for each source row.

- **Egress streams — output, 2 × `prism_axis`:** registered 512-bit streams to
  the two output buffers.

- **Accepted-edge feedback — output, 10 bits:** pulses only for the granted
  matrix edge whose input and output handshake completed.

- **Protocol-fault output — output, 16 bits:** reports multi-hot grants, grant
  changes during an open packet, selected-invalid input, and unmatched `tlast`.

## Contract behavior

- Data, byte mask, last, and error are selected as one bundle; no qualifier may
  come from a different source than `tdata`.
- The registered boundary must break timing between deep VOQ state and the
  OpenNIC TX pins while retaining one-beat-per-cycle throughput.
- A downstream stall holds the selected output beat stable and propagates
  `tready=0` to every candidate except the selected edge's held handshake.
- Any illegal grant asserts a sticky fault and prevents a new packet start; it
  must not combine or leak beats from two queues.

## Related modules and concepts

[`prism_packet_arbiter`](prism_packet_arbiter.md) owns the grant, and
[`prism_egress_buffer`](prism_egress_buffer.md) enforces the final TX-facing
stability contract.
