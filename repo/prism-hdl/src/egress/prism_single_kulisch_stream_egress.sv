//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_kulisch_stream_egress.sv
// Module: prism_single_kulisch_stream_egress
// Description: Streams exact SINGLE results to the configured recipients.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_kulisch_stream_egress #(
    parameter int unsigned MAX_ELEMENTS = 4096,
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_KULISCH_BITS = 4096,
    parameter int unsigned LANES = 16,
    // Result tiles requested and not yet sent. At least the number of cycles
    // from a request to the read of the tile's last segment is needed to
    // request a tile every cycle.
    parameter int unsigned RESULT_SLOTS = 32
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic                            s_start_valid,
    output logic                            s_start_ready,
    input  logic                            s_clear,
    input  prism_pkg::prism_operation_key_t s_operation,
    input  logic [31:0]                     s_element_count,
    input  logic [15:0]                     s_mtu,
    input  logic [15:0]                     s_kulisch_bits,
    input  logic                            s_auto_output,
    input  logic                            s_native_input,
    input  logic                            s_native_wide,
    input  logic                            s_error_only,
    input  logic [7:0]                      s_child_count,
    input  logic [7:0]                      s_result_enabled,
    input  logic [127:0]                    s_local_endpoints,
    input  logic [127:0]                    s_peer_endpoints,
    input  logic [127:0]                    s_local_ports,
    input  logic [383:0]                    s_peer_macs,
    input  logic [47:0]                     s_local_mac,
    output logic [7:0]                      m_store_read_slot,
    output logic                            m_store_read_valid,
    input  logic                            m_store_read_ready,
    input  logic [31:0]                     s_tile_first_element,
    input  logic [LANES-1:0]                s_tile_keep,
    input  logic [LANES*8-1:0]              s_tile_tags,
    input  logic [LANES*KULISCH_W-1:0]      s_tile_integers,
    input  logic [LANES*32-1:0]             s_tile_native_bits,
    input  logic                            s_tile_error,
    input  logic                            s_tile_valid,
    output logic                            s_tile_ready,
    output logic [15:0]                     m_egress_port,
    output logic [511:0]                    m_axis_tdata,
    output logic [63:0]                     m_axis_tkeep,
    output logic                            m_axis_tlast,
    output logic [15:0]                     m_axis_frame_bytes,
    output logic                            m_axis_tvalid,
    input  logic                            m_axis_tready,
    output logic [7:0]                      m_sent_mask,
    output logic                            m_all_sent,
    output logic                            m_fault
);

  import prism_pkg::*;

  typedef enum logic [2:0] {IDLE, PICK, PREPARE, FEED, ERROR_SEND, DONE, FAULT} state_t;
  (* dont_touch = "true" *) state_t output_state;
  (* dont_touch = "true" *) logic stream_clear;
  state_t state;
  prism_operation_key_t operation_reg;
  logic [31:0] total_reg;
  logic [15:0] mtu_reg, kulisch_bits_reg;
  logic [7:0] child_count_reg, enabled_reg, sent_reg;
  logic [127:0] local_endpoints_reg, peer_endpoints_reg, local_ports_reg;
  logic [383:0] peer_macs_reg;
  logic [47:0] local_mac_reg;
  logic error_reg;
  logic [3:0] scan_slot;
  logic [2:0] selected_slot, candidate_slot;
  logic candidate_found;
  logic [8:0] tile_total, read_issued, tile_loaded;
  logic [31:0] tile_stride;
  logic [LANES-1:0] expected_keep;
  logic [31:0] expected_first;
  // Elements behind the tile that is expected next.
  logic signed [32:0] expected_behind;
  logic auto_reg, native_input_reg, native_wide_reg;
  logic unused_auto_ready, auto_valid, auto_error;
  logic [LANES-1:0] auto_lane_valid, split_lane_valid;
  logic reserve_ready, unused_split_ready;
  // Result tiles enter through one register and the sub-blocks are cleared
  // from a register, so neither the result store nor the lifecycle drives
  // the wide enables and resets of the egress directly.
  logic block_clear, tile_valid, tile_error;
  (* dont_touch = "true" *) logic [LANES-1:0] tile_lane_valid, tile_class_valid;
  logic [31:0] tile_first;
  logic [LANES-1:0] tile_keep;
  logic [LANES*8-1:0] tile_tags;
  logic [LANES*KULISCH_W-1:0] tile_integers;
  logic [LANES*32-1:0] tile_native_bits;
  // A tile is checked where it arrives and reaches the lanes one register
  // step later: the lanes of the classifier and of the reader lie far from
  // the result store, and the check stays with the control of this block.
  logic lane_tile_valid, lane_tile_error;
  (* shreg_extract = "no" *) logic [31:0] lane_first;
  (* shreg_extract = "no" *) logic [LANES-1:0] lane_keep;
  (* shreg_extract = "no" *) logic [LANES*8-1:0] lane_tags;
  (* shreg_extract = "no" *) logic [LANES*KULISCH_W-1:0] lane_integers;
  (* shreg_extract = "no" *) logic [LANES*32-1:0] lane_native_bits;
  logic auto_tile_error;
  logic [31:0] auto_first;
  logic [LANES-1:0] auto_keep;
  logic [LANES*8-1:0] auto_formats, auto_tags;
  logic [LANES*32-1:0] auto_native_bits, auto_fp32_bits;
  logic auto_fp32_eligible;
  logic [LANES*KULISCH_W-1:0] auto_integers;
  logic splitter_fault, streamer_fault;
  logic [31:0] segment_first;
  logic [$clog2(LANES+1)-1:0] segment_count;
  logic [LANES*8-1:0] segment_formats, segment_tags;
  logic [LANES*32-1:0] segment_native_bits;
  logic [LANES*KULISCH_W-1:0] segment_integers;
  logic segment_valid, segment_ready, last_frame_done;
  logic [31:0] unused_packet_id;
  logic [7:0] first_frame_tile_budget;
  prism_numbergroup_header_t packet_header;
  // The streamer lies apart from the control of this block and takes the
  // context from registers of its own. They follow the context by one
  // cycle: the context is fixed from the start and the recipient from PICK,
  // and the streamer leaves its reset only after both.
  prism_numbergroup_header_t stream_header;
  logic [31:0] stream_total;
  logic [15:0] stream_mtu, stream_kulisch_bits;
  logic [7:0] stream_first_frame_tiles;
  logic [447:0] error_header_bytes;
  logic [511:0] error_frame;
  logic [511:0] stream_data;
  logic [63:0] stream_keep;
  logic stream_last, stream_valid;
  logic [15:0] stream_frame_bytes;
  wire unused_packet = ^unused_packet_id;

  initial begin
    if (MAX_ELEMENTS < 1 || MAX_ELEMENTS > 4096 || (KULISCH_W < 278 || KULISCH_W > 320)
        || LANES < 16 || LANES > 128 || (LANES & (LANES-1)) != 0)
      $fatal(1, "SINGLE exact egress requires supported exact tiles and bounded vectors");
  end

  assign s_start_ready = state == IDLE;
  assign m_fault = state == FAULT || splitter_fault || streamer_fault;
  assign m_sent_mask = sent_reg;
  assign m_all_sent = state == DONE;
  assign m_egress_port = local_ports_reg[selected_slot*16 +: 16];

  assign tile_stride = native_input_reg && !native_wide_reg
      ? 32'd16 : 32'(LANES);
  // Let the first frame transmit while the next, near-MTU frame is built.
  assign first_frame_tile_budget = LANES == 128
      && (!native_input_reg || native_wide_reg)
      ? 8'((((int'(mtu_reg)-PRISM_CONTROL_WORD_BYTES
          -PRISM_DATA_HEADER_BYTES+LANES-1)/LANES)/2)) : 8'd0;
  // A result tile is requested only when the reader has a free slot for it,
  // so the tile is always taken when it arrives and nothing stalls the
  // result store.
  // The request leaves through a skid buffer: the ready of the result store
  // ends at its few flags instead of the counters and slot copies here.
  logic request_valid, request_ready, request_fire;
  assign request_valid = state == FEED && read_issued < tile_total && reserve_ready;
  assign request_fire = request_valid && request_ready;
  prism_elastic_skid_buffer #(.WIDTH(8)) u_read_request (
      .clk(clk), .rst_n(rst_n && !s_clear),
      .s_data(read_issued[7:0]), .s_valid(request_valid), .s_ready(request_ready),
      .m_data(m_store_read_slot), .m_valid(m_store_read_valid), .m_ready(m_store_read_ready)
  );
  // What the next tile must look like is kept in registers: its first
  // element, its keep mask, and the elements that remain behind it. The
  // check of a tile is then two comparisons, and the mask of the tile after
  // it is derived from the remainder when the tile is taken.
  function automatic logic [LANES-1:0] keep_of(input logic signed [32:0] elements);
    if (elements <= 0) return '0;
    if (elements >= 33'(tile_stride)) return {LANES{1'b1}} >> (LANES - int'(tile_stride));
    return {LANES{1'b1}} >> (LANES - int'(elements[$clog2(LANES+1)-1:0]));
  endfunction
  assign s_tile_ready = 1'b1;
  // The output is chosen with a second copy of the state: the streamer and
  // the buffer behind the output lie apart from the rest of this block, and
  // the copy can be placed with them.
  assign m_axis_tdata = output_state == ERROR_SEND ? error_frame : stream_data;
  assign m_axis_tkeep = output_state == ERROR_SEND
      ? 64'h0fff_ffff_ffff_ffff : stream_keep;
  assign m_axis_tlast = output_state == ERROR_SEND ? 1'b1 : stream_last;
  assign m_axis_frame_bytes = output_state == ERROR_SEND ? 16'd60 : stream_frame_bytes;
  assign m_axis_tvalid = output_state == ERROR_SEND
      || (output_state == FEED && stream_valid);

  always_comb begin
    candidate_found = 1'b0;
    candidate_slot = '0;
    for (integer slot = 0; slot < 8; slot++) begin
      if (slot >= int'(scan_slot) && slot < int'(child_count_reg)
          && enabled_reg[slot] && !candidate_found) begin
        candidate_found = 1'b1;
        candidate_slot = 3'(slot);
      end
    end
    packet_header = '0;
    packet_header.destination_mac = peer_macs_reg[selected_slot*48 +: 48];
    packet_header.source_mac = local_mac_reg;
    packet_header.key = operation_reg;
    packet_header.source_endpoint = local_endpoints_reg[selected_slot*16 +: 16];
    packet_header.destination_endpoint = peer_endpoints_reg[selected_slot*16 +: 16];
    packet_header.stream_id = peer_endpoints_reg[selected_slot*16 +: 16];
    packet_header.packet_id = 32'(selected_slot) + 32'd1;
    packet_header.ethertype = PRISM_ETHERTYPE;
    packet_header.version = 8'h20;
    packet_header.packet_class = PRISM_OP_COL_RES;
    packet_header.flags = PRISM_DATA_FLAG_LAST
        | PRISM_DATA_FLAG_ACCUMULATION_INEXACT;
    error_header_bytes = {
        packet_header.destination_mac, packet_header.source_mac,
        packet_header.ethertype, packet_header.version,
        packet_header.packet_class, packet_header.key.job_id,
        packet_header.key.group_id, packet_header.key.group_generation,
        packet_header.key.operation_id, packet_header.key.operation_generation,
        packet_header.source_endpoint, packet_header.destination_endpoint,
        packet_header.packet_id, packet_header.first_element,
        packet_header.element_count, packet_header.group_count,
        packet_header.flags, packet_header.body_bytes,
        packet_header.stream_id, packet_header.reserved
    };
    error_frame = '0;
    for (integer byte_index = 0; byte_index < 56; byte_index++)
      error_frame[byte_index*8 +: 8]
          = error_header_bytes[(55-byte_index)*8 +: 8];
  end

  prism_auto_wire_tile16 #(
      .KULISCH_W(KULISCH_W), .LANES(LANES), .LANE_VALID_INPUT(1'b1)
  ) u_auto_classify (
      .clk(clk), .rst_n(rst_n && !block_clear),
      .s_first_element(lane_first), .s_keep(lane_keep),
      .s_mode_wide(!native_input_reg), .s_fp32_bits(lane_native_bits),
      .s_tags(lane_tags), .s_integers(lane_integers),
      .s_valid(lane_tile_valid && auto_reg), .s_lane_valid(tile_class_valid),
      .s_ready(unused_auto_ready), .m_first_element(auto_first),
      .m_keep(auto_keep), .m_formats(auto_formats),
      .m_native_bits(auto_native_bits), .m_fp32_bits(auto_fp32_bits),
      .m_fp32_eligible(auto_fp32_eligible), .m_tags(auto_tags),
      .m_integers(auto_integers), .m_valid(auto_valid), .m_lane_valid(auto_lane_valid),
      .m_ready(1'b1), .m_error(auto_error)
  );

  // The output mode is fixed for an operation. Each lane selects its payload
  // source with its own copy of the mode bit, so the select stays in the lane.
  (* dont_touch = "true" *) logic [LANES-1:0] auto_lane;
  logic [LANES-1:0] split_keep;
  logic [LANES*8-1:0] split_formats, split_tags;
  logic [LANES*32-1:0] split_native_bits, split_fp32_bits;
  logic [LANES*KULISCH_W-1:0] split_integers;
  for (genvar lane = 0; lane < LANES; lane++) begin : gen_mode_select
    assign split_keep[lane] = auto_lane[lane] ? auto_keep[lane] : lane_keep[lane];
    assign split_lane_valid[lane] = auto_lane[lane]
        ? auto_lane_valid[lane] : tile_lane_valid[lane];

    assign split_formats[lane*8 +: 8] = auto_lane[lane]
        ? auto_formats[lane*8 +: 8] : PRISM_FORMAT_KULISCH;
    assign split_native_bits[lane*32 +: 32] = auto_lane[lane]
        ? auto_native_bits[lane*32 +: 32] : 32'd0;
    assign split_fp32_bits[lane*32 +: 32] = auto_lane[lane]
        ? auto_fp32_bits[lane*32 +: 32] : 32'd0;
    assign split_tags[lane*8 +: 8] = auto_lane[lane]
        ? auto_tags[lane*8 +: 8] : lane_tags[lane*8 +: 8];
    assign split_integers[lane*KULISCH_W +: KULISCH_W] = auto_lane[lane]
        ? auto_integers[lane*KULISCH_W +: KULISCH_W]
        : lane_integers[lane*KULISCH_W +: KULISCH_W];
  end

  // The reader stores the values and cuts each tile into segments that fit
  // the MTU.
  prism_numbergroup_banked_segment_reader #(
      .KULISCH_W(KULISCH_W), .LANES(LANES), .SLOTS(RESULT_SLOTS), .RESERVED_INPUT(1'b1)
  ) u_splitter (
      .clk(clk), .rst_n(rst_n), .s_clear(block_clear),
      .s_reserve(request_fire), .s_reserve_ready(reserve_ready),
      .s_lane_valid(split_lane_valid),
      .s_mtu(mtu_reg), .s_kulisch_bits(kulisch_bits_reg),
      .s_first_element(auto_reg ? auto_first : lane_first),
      .s_keep(split_keep),
      .s_formats(split_formats),
      .s_native_bits(split_native_bits),
      .s_fp32_bits(split_fp32_bits),
      .s_fp32_eligible(auto_reg && auto_fp32_eligible),
      .s_tags(split_tags),
      .s_integers(split_integers),
      .s_error(auto_reg ? auto_error || auto_tile_error : lane_tile_error),
      .s_valid(auto_reg ? auto_valid : lane_tile_valid),
      .s_ready(unused_split_ready),
      .m_first_element(segment_first), .m_count(segment_count),
      .m_formats(segment_formats), .m_native_bits(segment_native_bits),
      .m_tags(segment_tags), .m_integers(segment_integers),
      .m_valid(segment_valid), .m_ready(segment_ready),
      .m_fault(splitter_fault)
  );

  logic [31:0] buffered_segment_first;
  logic [$clog2(LANES+1)-1:0] buffered_segment_count;
  logic [LANES*8-1:0] buffered_segment_formats, buffered_segment_tags;
  logic [LANES*32-1:0] buffered_segment_native_bits;
  logic [LANES*KULISCH_W-1:0] buffered_segment_integers;
  logic buffered_segment_valid, buffered_segment_ready;

  // The banked reader already registers payload after the descriptor FIFO.
  assign buffered_segment_first = segment_first;
  assign buffered_segment_count = segment_count;
  assign buffered_segment_formats = segment_formats;
  assign buffered_segment_native_bits = segment_native_bits;
  assign buffered_segment_tags = segment_tags;
  assign buffered_segment_integers = segment_integers;
  assign buffered_segment_valid = segment_valid;
  assign segment_ready = buffered_segment_ready;

  prism_numbergroup_mixed_tile_streamer #(
      .KULISCH_W(KULISCH_W), .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .PACKET_CLASS(PRISM_OP_COL_RES), .LANES(LANES)
  ) u_streamer (
      // The streamer starts every recipient from its reset state. A clear
      // that ends an operation early finds frames in it that will never be
      // completed, and its own reset waits for its frames. The reset comes
      // one register after that of the reader, which feeds the streamer only
      // many cycles after its own reset.
      .clk(clk), .rst_n(!stream_clear), .s_reset(1'b0),
      .s_header(stream_header), .s_total_elements(stream_total), .s_mtu(stream_mtu),
      .s_kulisch_bits(stream_kulisch_bits),
      .s_first_frame_tiles(stream_first_frame_tiles),
      .s_tile_first_element(buffered_segment_first), .s_tile_count(buffered_segment_count),
      .s_formats(buffered_segment_formats), .s_native_bits(buffered_segment_native_bits),
      .s_tags(buffered_segment_tags), .s_integers(buffered_segment_integers),
      .s_tile_valid(buffered_segment_valid && output_state == FEED),
      .s_tile_ready(buffered_segment_ready),
      .m_axis_tdata(stream_data), .m_axis_tkeep(stream_keep),
      .m_axis_tlast(stream_last), .m_frame_bytes(stream_frame_bytes),
      .m_packet_id(unused_packet_id), .m_last_frame_done(last_frame_done),
      .m_axis_tvalid(stream_valid),
      .m_axis_tready(m_axis_tready && output_state != ERROR_SEND),
      .m_fault(streamer_fault)
  );

  always_ff @(posedge clk) begin
    block_clear <= !rst_n || s_clear || state == PREPARE;
    stream_clear <= block_clear;
    // Only tiles that arrive while a recipient is being fed are kept; the
    // registered flags then need no further qualification.
    tile_valid <= rst_n && !s_clear && s_tile_valid && state == FEED;
    lane_tile_valid <= tile_valid;
    tile_lane_valid <= {LANES{tile_valid}};
    tile_class_valid <= {LANES{tile_valid && auto_reg}};
    lane_tile_error <= tile_error;
    lane_first <= tile_first;
    lane_keep <= tile_keep;
    lane_tags <= tile_tags;
    lane_integers <= tile_integers;
    lane_native_bits <= tile_native_bits;
    tile_first <= s_tile_first_element;
    tile_keep <= s_tile_keep;
    tile_tags <= s_tile_tags;
    tile_integers <= s_tile_integers;
    tile_native_bits <= s_tile_native_bits;
    tile_error <= s_tile_error;
    stream_header <= packet_header;
    stream_total <= total_reg;
    stream_mtu <= mtu_reg;
    stream_kulisch_bits <= kulisch_bits_reg;
    stream_first_frame_tiles <= first_frame_tile_budget;
    // The mode of the lanes follows the mode of the operation in the same
    // way, so the start of an operation enables no register in the lanes.
    auto_lane <= {LANES{auto_reg}};
  end

  // The operation context carries data only: it is captured at every start,
  // before any use, so it takes no reset and does not wait for validation.
  always_ff @(posedge clk) begin
    if (state == IDLE && s_start_valid) begin
      operation_reg <= s_operation;
      total_reg <= s_element_count;
      mtu_reg <= s_mtu;
      kulisch_bits_reg <= s_kulisch_bits;
      auto_reg <= s_auto_output;
      native_input_reg <= s_native_input;
      native_wide_reg <= s_native_wide;
      error_reg <= s_error_only;
      child_count_reg <= s_child_count;
      enabled_reg <= s_result_enabled;
      local_endpoints_reg <= s_local_endpoints;
      peer_endpoints_reg <= s_peer_endpoints;
      local_ports_reg <= s_local_ports;
      peer_macs_reg <= s_peer_macs;
      local_mac_reg <= s_local_mac;
      tile_total <= s_native_input && !s_native_wide
          ? 9'((s_element_count + 32'd15) >> 4)
          : 9'((s_element_count + LANES-1) / LANES);
    end
  end

  // The next state, so that both copies of the state take the same value.
  state_t state_next;
  logic start_refused, tile_refused, feed_incomplete;
  assign start_refused = s_element_count == 0 || s_element_count > MAX_ELEMENTS
      || s_mtu < 16'd576 || s_mtu > 16'd1500
      || s_child_count == 0 || s_child_count > 8
      || s_result_enabled == 0
      || (s_native_input && !s_auto_output)
      || (s_native_wide && (!s_native_input || LANES != 128))
      || (s_result_enabled >> s_child_count) != 0;
  assign tile_refused = tile_loaded >= tile_total
      || tile_first != expected_first
      || tile_keep != expected_keep || tile_error;
  assign feed_incomplete = read_issued != tile_total || tile_loaded != tile_total;
  always_comb begin
    state_next = state;
    case (state)
      IDLE: if (s_start_valid) state_next = start_refused ? FAULT : PICK;
      PICK: state_next = candidate_found ? PREPARE : DONE;
      PREPARE: state_next = error_reg ? ERROR_SEND : FEED;
      ERROR_SEND: if (m_axis_tready) state_next = PICK;
      FEED: begin
        if (splitter_fault || streamer_fault) state_next = FAULT;
        if (tile_valid && tile_refused) state_next = FAULT;
        if (last_frame_done) state_next = feed_incomplete ? FAULT : PICK;
      end
      DONE, FAULT: ;
      default: state_next = IDLE;
    endcase
  end

  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      state <= IDLE;
      output_state <= IDLE;
      sent_reg <= '0;
      scan_slot <= '0;
      selected_slot <= '0;
      read_issued <= '0;
      tile_loaded <= '0;
      auto_tile_error <= 1'b0;
    end else begin
      if (lane_tile_valid && auto_reg) auto_tile_error <= lane_tile_error;
      state <= state_next;
      output_state <= state_next;
      case (state)
        IDLE: if (s_start_valid && !start_refused) begin
          sent_reg <= '0;
          scan_slot <= '0;
        end
        PICK: begin
          if (candidate_found) begin
            selected_slot <= candidate_slot;
            read_issued <= '0;
            tile_loaded <= '0;
            expected_first <= '0;
            expected_keep <= keep_of({1'b0, total_reg});
            expected_behind <= $signed({1'b0, total_reg}) - $signed({1'b0, tile_stride});
          end
        end
        ERROR_SEND: if (m_axis_tready) begin
          sent_reg[selected_slot] <= 1'b1;
          scan_slot <= {1'b0, selected_slot} + 4'd1;
        end
        FEED: begin
          if (request_fire) read_issued <= read_issued + 9'd1;
          if (tile_valid && !tile_refused) begin
            tile_loaded <= tile_loaded + 9'd1;
            expected_first <= expected_first + tile_stride;
            expected_keep <= keep_of(expected_behind);
            expected_behind <= expected_behind - $signed({1'b0, tile_stride});
          end
          if (last_frame_done && !feed_incomplete) begin
            sent_reg[selected_slot] <= 1'b1;
            scan_slot <= {1'b0, selected_slot} + 4'd1;
          end
        end
        default: begin end
      endcase
    end
  end

endmodule
