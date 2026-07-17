# `prism_switch_core`

**Module class:** `TOP LEVEL`  

`prism_switch_core` is the portable, single-clock PRISM datapath. It connects
two ingress units with forwarding, management, collective, result-delivery,
reliability, and shared egress units. It is the preferred top for Cocotb because
it does not expose OpenNIC clock-domain details.

## Contracts

- **Clock/reset — input, 322.265625 MHz + 1 bit:** one datapath clock and
  synchronized active-low reset serve every instantiated child module.

- **Ingress packet streams — input, 2 × `prism_axis`:** two 512-bit packet
  streams with independent ready/valid handshakes. A port may receive forwarded
  traffic while the other receives a collective contribution.

- **Egress packet streams — output, 2 × `prism_axis`:** two independently
  scheduled packet streams. There is no packet interleaving on either stream.

- **Configuration request — input, 72-bit `prism_cfg_req_t` + valid/ready:**
  accepts one normalized 32-bit access: command, 24-bit byte address, four byte
  enables, access flags, and 32-bit write data.

- **Configuration response — output, 40-bit `prism_cfg_rsp_t` + valid/ready:**
  returns an 8-bit status and 32-bit read data exactly once for each accepted
  request.

- **Core status — output, 128 bits:** exposes per-unit fatal flags, current
  reset epoch, queue-pressure summary, and active-operation summary. Detailed
  counters are read through configuration space.

- **Internal injection presence — internal parameter, 3 bits:** identifies the
  result, management, and progress/reliability source rows. All three are active
  in the Protocol 1.0 v1 profile.

## Contract behavior

- `NUM_PORTS=2`, `NUM_INTERNAL_SOURCES=3`, `DATA_W=512`, and `KEEP_W=64` are the
  v1 elaboration values. Child interfaces use parameter-derived array sizes,
  never hand-coded one-port aliases.
- The core never rewrites a transparently forwarded packet. Locally consumed
  packets can change state only after closed-packet validation.
- Fatal internal errors stop new local admissions but leave already granted
  forwarded packets drainable, preventing a half-packet on TX.
- The ingress parse/classify paths, VOQ rows, egress columns, and FP32 ALU
  arrays are spatially replicated to sustain their documented initiation
  rates. Control and management transactions may take multiple cycles, but
  cannot block an unrelated forwarding stream unless they contend for its
  selected egress.

## Correspondence with the overview architecture

| Overview block | Interface hierarchy |
|---|---|
| Physical link control and ingress buffer | `prism_switch_top` and its per-port `prism_packet_fifo` staging queues |
| Parser/classifier and DEMUX | `prism_ingress_unit`, `prism_header_parser`, `prism_forwarding_unit`, and the packet-class drain paths |
| `(N+K) × N` VOQ | `prism_egress_unit` containing `prism_voq_bank` |
| Routing control and arbitration | Per-packet route metadata plus `prism_packet_arbiter` |
| Crossbar and TX buffers | `prism_stream_crossbar` and one `prism_egress_buffer` per port |
| Collective engine and context | `prism_collective_unit`, `prism_collective_context_table`, range tracker, accumulator scheduler/store, and backend dispatcher |
| Result queues and format expansion | `prism_output_packetizer`, `prism_result_delivery_unit`, and `prism_result_replicator` |
| Collective traffic reinjection | Result, management, and reliability source rows in the shared VOQ matrix |

The drawing places routing control after the VOQ for conceptual clarity. PRISM
computes the destination before admission because that destination selects the
VOQ column; the stored route metadata is then consumed by arbitration. This is
a pipeline placement difference, not an architectural mismatch.

## Related modules and concepts

The core composes the [main units](../index.md#main-units). Physical shell
adaptation belongs only in [`prism_switch_top`](prism_switch_top.md), while the
packet lifecycle follows the [PRISM pipeline](../../2.pipeline.md#323-prism-pipeline).
The common backpressure and hazard rules are normative in
[Shared contracts](../common-contracts.md#pipelining-and-hazard-invariants).
