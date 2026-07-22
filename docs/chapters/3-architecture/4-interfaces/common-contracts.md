# Current shared contracts

`repo/prism-hdl/src/prism_pkg.sv` is the authority for internal packed types and
wire constants. This page records the contracts used by the current RTL.

| Contract | Producer -> consumer | Required invariant |
|---|---|---|
| AXI frame | ingress adapter -> frame FIFO; packetizer -> egress FIFO | Transfer on `tvalid && tready`; stable under stall; contiguous final `tkeep`; accepted `tlast` ends one frame. |
| `prism_parsed_header_t` | header parser -> ingress port/validator | Big-endian fixed-prefix fields plus ingress port; parsing is not validation. |
| `prism_frame_desc_t` | frame FIFO/ingress -> validator/demux | Describes one closed frame, byte length, parsed header, and adapter/keep errors. |
| `prism_ingress_context_t` | operation/contributor lookup -> DATA path | Operation slot/descriptor, expected contributor count, selected width and warning remain aligned with the frame. |
| CONTROL byte stream | control depacketizer -> fragment arbiter/reassembler/decoder | Header/start precedes exactly the declared payload bytes; owner cannot interleave fragments. |
| `prism_tlv_event_t` | TLV decoder -> stager | Message/record boundaries, type/flags/length, value bytes, and padding are bounded and backpressurable. |
| `prism_control_request_t` | stager -> executor/tables | Represents one completely staged request; malformed input does not partially update tables. |
| `prism_tile_meta_t` + lane data/keep | DATA depacketizer -> converter -> scheduler | Metadata, numeric lanes, lane mask and selected width transfer atomically. |
| Converted FP32/Kulisch tile | input conversion -> range scheduler | Exactly one representation is selected by accumulator profile; format/deposit errors accompany the same tile. |
| Reduced tile | range scheduler -> result conversion/store | Published only after all expected contributors for the range; warning is sticky. |
| `prism_result_chunk_meta_t` | chunk store -> router | Payload slot is immutable while armed and remains valid until all references release. |
| `prism_result_packet_job_t` | router -> per-port packetizer | Contains resolved egress/destination/result-path; packetizer serializes but does not choose routes. |
