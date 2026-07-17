# `prism_voq_bank`

**Module class:** `COMPONENT / STREAM`  

`prism_voq_bank` instantiates one packet FIFO for every source/egress pair. It
keeps a blocked output from delaying packets for the other output and gives
forwarded and internally generated traffic the same reservation semantics.

## Contracts

- **Source enqueue streams — input, 5 × `prism_axis`:** two physical-ingress
  rows and three internal-injection rows can each transfer one beat in the same
  cycle. Enqueue readiness is independent per row; there is no shared global
  write port.

- **Per-packet route — input, 5 × 8-bit egress + valid/ready:** selects one of
  the two egress columns on the first beat and remains associated with the
  packet through `tlast`.

- **Reservation channels — input/output, 10 × 32-bit request and response:**
  independently reserves each `source × egress` queue. Requests for distinct
  queues can succeed in the same cycle, including requests from both physical
  ingress rows and the collective-result row.

- **Candidate streams — output, 10 × `prism_axis`:** exposes one head stream for
  each matrix edge. Only complete or cut-through-safe packet heads assert
  eligibility.

- **Queue state — output, 160 bits occupancy + 20 flags:** ten 16-bit used-beat
  counts plus per-queue complete-packet and pressure indicators.

## Contract behavior

- V1 elaborates `NUM_SOURCES=5` and `NUM_EGRESS=2`; both dimensions are
  parameters and determine array sizes and the grant matrix.
- Each `VOQ[source][egress]` is a logical packet queue with independent
  ordering, reservation, and backpressure state. The first implementation
  profile realizes each queue as a physically separate packet FIFO.
- The architecture must resolve simultaneous reservation/enqueue requests
  before asserting readiness and must sustain the enabled profile's admitted
  source concurrency. A later shared-cell organization may replace the FIFO
  matrix if it preserves the same observable contracts; it would add cell
  allocation/reclamation, descriptor queues, and shared-memory arbitration.
- One source row selects at most one egress column for its current packet, so a
  matrix cell never has multiple enqueue writers. Enqueue and dequeue of the
  same cell in one cycle remain legal under the packet-FIFO contract.
- A packet cannot change egress after its first enqueue transfer. Route changes
  affect only later packets.
- Source ordering is preserved within each egress queue. There is no ordering
  promise between packets sent to different egresses.
- A disabled injection source has valid permanently low and consumes no queue
  reservation, while retaining its source index for later feature enablement.

## Related modules and concepts

Each matrix entry is a [`prism_packet_fifo`](prism_packet_fifo.md). Candidate
streams are selected by [`prism_packet_arbiter`](prism_packet_arbiter.md) and
transferred through [`prism_stream_crossbar`](prism_stream_crossbar.md).
