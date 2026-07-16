# Shared contracts and widths

`prism_pkg.sv` owns the packed metadata types shared by RTL, Cocotb, and the
traffic model. Numeric accumulator state is deliberately **not** embedded in a
universal packed result type: each enabled backend owns its state width, while
the scheduler and completion path exchange fixed-width metadata plus an
explicit backend payload bus. This permits an FP32 backend and future Kulisch
backends of different widths to coexist without widening unrelated interfaces.

Every non-packet channel uses decoupled `valid`/`ready`. A transfer occurs only
on `valid && ready`; a stalled producer holds all payload bits stable. Reserved
bits are zero. State changes occur only on a transfer or an explicitly accepted
reservation command.

## Packet and operation contracts

- **`prism_axis` — 579 forward bits plus one reverse bit:** `tdata[511:0]`,
  `tkeep[63:0]`, `tvalid`, `tlast`, and `tuser_err`; `tready` is reverse
  backpressure.

- **`prism_parsed_header_t` — 352 bits:** a 320-bit Ethernet, control-word, and
  first 24 class-header image; ingress port 8; parse status 8; required-header
  length 16.

- **`prism_packet_desc_t` — 384 bits:** first-header image 320, ingress port 8,
  observed frame length 16, packet-store handle 16, class 8, status 8, and 8
  reserved bits.

- **`prism_op_key_t` — 144 bits:** Job ID 64, Group ID 16, Group Generation 16,
  Operation ID 16, and Operation Generation 32.

- **`prism_stream_geometry_t` — 64 bits:** elements per chunk 16, chunk count
  24, elements in final chunk 16, and 8 reserved bits. Three instances cache
  the derived Input, Partial, and Output Wire Format geometries. They are
  internal results, not redundant control-protocol inputs.

- **`prism_operation_ctx_t` — 544 bits:** operation key 144; semantic,
  operator, input format, accumulator profile, accumulation policy, partial
  format, output format, and flags at 8 bits each; Element Count 32; Maximum
  Reduction Terms 32; three 64-bit stream geometries; local contributor count
  16; operation slot 16; result-route base 16; result-route count 16; and
  admitted direct-stream window 16.

- **`prism_lookup_req_t` — 176 bits:** operation key 144, peer or contributor
  ID 16, ingress port 8, and packet class 8.

- **`prism_context_update_t` — 608 bits:** operation context 544, action 8,
  table slot 16, commit generation 16, and field mask 24.

## Contribution and arithmetic contracts

- **`prism_contribution_desc_t` — 320 bits:** operation key 144, operation slot
  16, Contributor ID 16, stream-local Chunk Index 24, derived global First
  Element 32, Elements in Packet 16, input or partial format 8, packet-store
  handle 16, ingress port 8, DATA flags 8, status 8, and 24 reserved bits.

- **`prism_arith_work_meta_t` — 192 bits:** operation slot 16, accumulator-range
  slot 16, global First Element 32, tile index 16, Contributor ID 16, element
  count 8, accumulator profile 8, accumulation policy 8, source format 8,
  flags 8, dependency tag 16, Operation Generation 32, and Reduction Operator 8.

- **Arithmetic work payload — V1 528 bits plus 192-bit metadata:** normalized
  FP32 data 512 and element-valid mask 16. The package derives this payload
  shape from enabled backends. A future backend may expose a different typed
  request payload without changing `prism_arith_work_meta_t`.

- **`prism_normalized_pair_t` — 1088 bits:** two V1 FP32 tiles at 512 bits,
  two 16-bit masks, 2-bit tile count, 8-bit conversion status, and 22 reserved
  bits. This is an FP32-backend converter type, not a universal accumulator
  representation.

- **`prism_arith_commit_t` — 192 bits:** scheduling identity, profile/operator,
  commit status, initialization/final-tile flags, and exception summary. It
  contains no FP32 or Kulisch numeric state.

- **`prism_accum_addr_t` — 96 bits:** operation slot 16, range slot 16, global
  First Element 32, tile index 16, bank 8, and accumulator profile 8. Packet
  Chunk Index is never an accumulator address.

- **FP32 backend state — 544 bits:** sixteen FP32 lanes 512, lane-valid mask 16,
  and state/order flags 16. A future Kulisch state type is instead
  `KULISCH_STATE_BITS × backend_elements_per_tile` plus its validity metadata;
  it does not enlarge the FP32 type or `prism_arith_commit_t`.

- **FP32 ALU-array request/response — 1064/544 bits:** operands A and B at 512
  bits each, lane mask 16, tag 16, operator 8; response data 512, tag 16,
  status 16.

## Completion, packetization, and result contracts

- **`prism_ready_range_t` — 256 bits:** operation key 144, operation slot 16,
  global First Element 32, element count 16, accumulator profile 8, outgoing
  wire format 8, role/terminal flags 8, accumulator handle 16, and 8 reserved
  bits.

- **`prism_res_chunk_desc_t` — 288 bits:** operation key 144, operation slot
  16, derived output Chunk Index 24, global First Element 32, elements in packet
  16, output format 8, payload handle 16, flags 8, and 24 reserved
  bits.

- **`prism_result_route_t` — 128 bits:** egress port 8, Result Path ID 16,
  destination MAC 48, local source MAC 48, and route flags 8.

- **`prism_replica_cmd_t` — 256 bits:** operation key 144, output-stream Chunk
  Index 24, immutable payload handle 16, route-table base 16, route count 16,
  result flags 8, and 32 reserved bits.

- **`prism_packet_serialize_cmd_t` — 512 bits:** a 448-bit maximum fixed-header image,
  egress port 8, payload format 8, logical payload bytes 16, payload handle 16,
  and flags 16. It serializes an already packetized payload and does not decide
  collective re-chunking.

## Reliability and reservation contracts

- **`prism_replay_key_t` — 192 bits:** operation key 144, peer kind 8, Peer ID
  16, and that direct DATA or RES stream's Chunk Index 24.

- **`prism_replay_cmd_t` — 256 bits:** replay key 192, retained packet handle
  16, egress port 8, retry limit 16, flags 8, and 16 reserved bits.

- **Reservation request/response — 32 bits each:** request maximum beats 16,
  resource/queue ID 8, owner 8; response grant 1, reservation ID 15, granted
  beats 16.

- **`prism_rx_accept_event_t` — 256 bits:** replay key 192, retained packet
  handle 16, status 8, reason 8, flags 8, and 24 reserved bits.

- **`prism_progress_event_t` — 256 bits:** replay key 192, status 8, reason 8,
  admitted window 16, retry delay 32. Selective-ACK bits remain packet payload.

## Pipelining and hazard invariants

- Registered elastic boundaries break combinational `ready` paths. Latency may
  exceed one cycle; independent line-rate stages target initiation interval one.
- Whole-packet admission reserves promised storage before the first enqueue
  beat. A granted packet cannot become partially stored or interleaved.
- Simultaneous queue, RAM-bank, backend, and egress requests are arbitrated
  before acceptance. Losing requests remain stable and pending.
- Accumulator RAW dependencies forward or stall; WAW conflicts serialize; a
  generation mismatch prevents a stale response from committing.
- The output-range tracker may retain `OUTPUT_PENDING` state under packetizer,
  VOQ, replay, or result-path backpressure. Independent ranges and operations
  remain schedulable.
- A crossbar grant is locked through accepted `tlast`; `tdata`, `tkeep`, and
  `tlast` remain stable while TX is stalled.

Datapath modules use the 322.265625 MHz clock and synchronized active-low reset.
Reset invalidates tentative state and never emits a partial packet, ACK, or
completion event.
