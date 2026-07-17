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

Protocol wire widths are normative. The internal types below are stable
semantic boundaries, but their packed widths remain derived/provisional until
`prism_pkg.sv` is implemented.

| Type | Required content and ownership |
|---|---|
| `prism_axis` | AXI stream data, byte-valid mask, last, error, valid, and reverse ready; `DATA_W=512` in the first target. |
| `prism_cfg_req_t` / `prism_cfg_rsp_t` | One 32-bit register access: command, byte address, four byte enables, access flags, write data; response status and 32-bit read data. A 64-bit value uses two addressed words plus an explicit snapshot rule when atomicity is required. |
| `prism_parsed_header_t` | Raw Ethernet/control/class-header prefix, ingress, parse status, and required-header length. |
| `prism_packet_desc_t` | Parsed prefix, ingress, observed length, packet-store handle, class, and validation status for one closed packet. |
| `prism_op_key_t` | Job ID, Group ID/Generation, and Operation ID/Generation. |
| `prism_stream_geometry_t` | Derived elements per chunk, chunk count, and final-chunk elements for one wire format; never a control-protocol input. |
| `prism_operation_ctx_t` | Operation key and semantics, five-field arithmetic tuple, Element Count, Maximum Reduction Terms, three derived geometries, contributor count, operation slot, result-range table span, and admitted direct-stream window. |
| Lookup/update types | Full operation key, peer/contributor and ingress/class qualifiers; committed context plus action, slot, generation, and field mask. |

## Contribution and arithmetic contracts

| Type | Required content and ownership |
|---|---|
| `prism_contribution_desc_t` | Operation/slot, Contributor ID, input-stream Chunk Index, derived global First Element and element count, source format, packet handle, ingress, DATA flags, and status. |
| `prism_arith_work_meta_t` | Operation/range identity, global element tile, Contributor ID, profile, policy, source format, dependency tag, generation, and operator. |
| Backend work payload | Profile-specific numeric values and element-valid mask. The FP32 target uses 16 FP32 values per 512-bit tile; a future profile declares its own payload type. |
| `prism_arith_commit_t` | Scheduling identity, profile/operator, commit status, and initialization/final-tile flags; no numeric accumulator state. |
| `prism_accum_addr_t` | Operation slot, range slot, global First Element, tile, bank, and profile. Packet Chunk Index is not an accumulator address. |
| Profile state port | Backend-specific numeric state plus validity/order metadata; FP32 and future Kulisch state never share an artificially widened universal type. |

The scheduler and store size port arrays from compiled backend capacity. Same
range read-after-write dependencies forward or stall; independent operations
remain eligible.

## Completion, routing, and packetization

| Type | Required content and ownership |
|---|---|
| `prism_ready_range_t` | Operation/slot, global First Element, element count, profile, outgoing format, role, and accumulator handle. |
| `prism_res_chunk_desc_t` | Operation/slot, derived output Chunk Index and global range, output format, immutable payload handle, and flags. |
| `prism_result_range_route_t` | First/last output Chunk Index and Replication Group ID; internal image of one `RESULT_ROUTE_RANGE`. |
| `prism_result_destination_t` | One direct next hop: egress, Result Path ID, next-hop type, source/destination MACs, and derived flags. |
| `prism_replica_cmd_t` | Operation, output Chunk Index, immutable payload, selected Replication Group ID, and result flags. Destination count comes from the group. |
| `prism_packet_serialize_cmd_t` | Prepared fixed header, egress, payload format/length/handle, and flags. It emits an already packetized payload and does not choose collective geometry. |

Result-range lookup, destination-set enumeration, and serialization are three
separate transfers. This prevents a range mapping from being mistaken for a
direct egress record.

## Reliability and reservation contracts

| Type | Required content and ownership |
|---|---|
| `prism_replay_key_t` | Full operation key, Peer Kind, Peer ID, and that peer's direct DATA/RES Chunk Index. |
| `prism_replay_cmd_t` | Replay key, retained packet handle, egress, retry limit, and flags. |
| Reservation request/response | Maximum beats, resource/queue owner, grant, reservation ID, and granted beats. Width derives from capacity. |
| `prism_rx_accept_event_t` | Replay key, retained handle, status, reason, and flags after safe receive/duplicate resolution. |
| `prism_progress_event_t` | Replay key, status/reason, admitted window, and retry delay; selective-ACK bits remain packet payload. |

## Pipelining and hazard invariants

- Registered elastic boundaries break combinational `ready` paths. Latency may
  exceed one cycle; selected line-rate stages target initiation interval one.
- Whole-packet admission reserves promised storage before enqueue. A granted
  packet cannot become partially visible or interleaved.
- Concurrent queue, memory-bank, backend, and egress requests are resolved
  before acceptance; losing requests remain stable and pending.
- Accumulator RAW dependencies forward or stall, WAW conflicts serialize, and
  generation mismatch prevents stale commit.
- `OUTPUT_PENDING` state survives packetizer, queue, replay, or destination
  backpressure while independent ranges remain schedulable.
- A crossbar grant is locked through accepted `tlast`; TX signals remain stable
  while stalled.
- Reset invalidates tentative state and emits no partial packet, ACK, or
  completion event. Datapath integration uses the 250 MHz domain and a
  synchronized active-low reset.
