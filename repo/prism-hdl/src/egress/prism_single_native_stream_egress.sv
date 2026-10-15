//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_native_stream_egress.sv
// Module: prism_single_native_stream_egress
// Description: Native RESULT stream for bound SINGLE recipients.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_native_stream_egress #(
    parameter int unsigned MAX_ELEMENTS = 4096
) (
    input  logic                                clk,
    input  logic                                rst_n,
    input  logic                                s_start_valid,
    output logic                                s_start_ready,
    input  logic                                s_clear,
    input  prism_pkg::prism_operation_key_t     s_operation,
    input  logic [31:0]                         s_element_count,
    input  logic [15:0]                         s_mtu,
    input  logic [7:0]                          s_output_format,
    input  logic [7:0]                          s_child_count,
    input  logic [7:0]                          s_result_count,
    input  logic [7:0]                          s_result_enabled,
    input  logic [127:0]                        s_local_endpoints,
    input  logic [127:0]                        s_peer_endpoints,
    input  logic [127:0]                        s_local_ports,
    input  logic [383:0]                        s_peer_macs,
    input  logic [47:0]                         s_local_mac,
    output logic [7:0]                          m_store_read_slot,
    output logic                                m_store_read_valid,
    input  logic                                m_store_read_ready,
    input  logic [31:0]                         s_tile_first_element,
    input  logic [15:0]                         s_tile_keep,
    input  logic [511:0]                        s_tile_bits,
    input  logic                                s_tile_error,
    input  logic                                s_tile_valid,
    output logic                                s_tile_ready,
    output logic [15:0]                         m_egress_port,
    output logic [511:0]                        m_axis_tdata,
    output logic [63:0]                         m_axis_tkeep,
    output logic                                m_axis_tlast,
    output logic [15:0]                         m_axis_frame_bytes,
    output logic                                m_axis_tvalid,
    input  logic                                m_axis_tready,
    output logic [7:0]                          m_sent_mask,
    output logic                                m_all_sent,
    output logic                                m_fault
);

  import prism_pkg::*;

  typedef enum logic [2:0] {
      IDLE, CHECK, COLLECT, PICK, PREPARE, FEED, DONE, FAULT
  } state_t;
  state_t state;
  prism_operation_key_t operation_reg;
  logic [31:0] total_reg;
  logic [15:0] mtu_reg;
  logic [7:0] format_reg;
  logic [8:0] source_tile_total, packed_tile_total;
  logic [8:0] source_issued, source_loaded, read_issued, tile_loaded;
  logic [7:0] write_index, write_slot;
  logic write_valid, collect_open;
  logic [1:0] pack_subtile;
  // The output format as the packing uses it.
  logic pack_bytes, pack_halves;
  logic [511:0] pack_word, pack_next, read_word;
  // 4096 FP32 values occupy 16 KiB. A 512-bit by 256-word result RAM
  // bounds all native formats; narrower results use only 128 or 64 words.
  // A wide Vivado RAM port may consume up to eight RAMB36 primitives.
  (* ram_style = "block" *) logic [511:0] result_tiles [0:255];
  logic read_word_valid;
  logic [6:0] values_per_tile;
  logic [2:0] subtiles_per_word;
  logic [6:0] expected_output_count;
  // Running position of the frame feed; no multiply on the tile handoff.
  // The count of the tile on offer is a register, taken from the values
  // behind the tile before it.
  logic [31:0] feed_first_element, feed_behind, feed_source;
  logic [32:0] feed_less;
  logic word_complete, feed_read, feed_advance;
  logic [7:0] child_count_reg, enabled_reg;
  logic [7:0] sent_mask_reg;
  logic [127:0] local_endpoints_reg, peer_endpoints_reg, local_ports_reg;
  logic [383:0] peer_macs_reg;
  logic [47:0] local_mac_reg;
  logic [3:0] scan_slot;
  logic [2:0] selected_slot, candidate_slot;
  logic candidate_found, context_good;
  // The verdict on the context of the start, used in the cycle after it.
  logic context_checked;
  logic [4:0] expected_source_count;
  logic [15:0] expected_tile_keep;
  logic tile_good, streamer_tile_ready, streamer_fault;
  logic last_frame_done;
  logic [31:0] unused_packet_id;
  wire unused_packet = ^unused_packet_id;
  prism_numbergroup_header_t packet_header;

  initial begin
    if (MAX_ELEMENTS < 1 || MAX_ELEMENTS > 4096)
      $fatal(1, "Native stream egress requires a bounded vector");
  end

  assign s_start_ready = state == IDLE;
  assign m_fault = state == FAULT || streamer_fault;
  assign m_sent_mask = sent_mask_reg;
  assign m_all_sent = state == DONE;
  assign m_egress_port = local_ports_reg[selected_slot*16 +: 16];
  // A request for a result leaves through a skid buffer, as in the exact
  // egress: the ready of the result store ends at the flags of the buffer
  // instead of the counters here.
  logic request_valid, request_ready;
  assign request_valid = state == COLLECT && source_issued < source_tile_total;
  prism_elastic_skid_buffer #(.WIDTH(8)) u_read_request (
      .clk(clk), .rst_n(rst_n && !s_clear),
      .s_data(source_issued[7:0]), .s_valid(request_valid), .s_ready(request_ready),
      .m_data(m_store_read_slot), .m_valid(m_store_read_valid), .m_ready(m_store_read_ready)
  );
  assign expected_source_count = total_reg - (32'(source_loaded) << 4) >= 32'd16
      ? 5'd16 : 5'(total_reg - (32'(source_loaded) << 4));
  assign expected_tile_keep = expected_source_count == 5'd16
      ? 16'hffff : (16'h1 << expected_source_count) - 16'd1;
  assign tile_good = source_loaded < source_tile_total
      && s_tile_first_element == (32'(source_loaded) << 4)
      && s_tile_keep == expected_tile_keep && !s_tile_error;
  // A tile is taken whenever one is expected; a tile that does not fit ends
  // the operation with a fault. The ready therefore does not wait for the
  // checks of the tile it answers: it is a register, up from the start of
  // the operation until the last tile is taken.
  assign s_tile_ready = collect_open;
  assign feed_source = state == PREPARE ? total_reg : feed_behind;
  assign feed_less = {1'b0, feed_source} - 33'(values_per_tile);
  assign word_complete = int'(pack_subtile) + 1 == int'(subtiles_per_word)
      || source_loaded + 9'd1 == source_tile_total;
  assign feed_read = state == FEED && !streamer_fault
      && (!read_word_valid || streamer_tile_ready) && read_issued < packed_tile_total;
  assign feed_advance = state == FEED && !streamer_fault
      && read_word_valid && streamer_tile_ready;
  assign context_good = s_child_count != 0 && s_child_count <= 8
      && s_result_count != 0 && s_result_count <= s_child_count
      && s_result_enabled != 0
      && $countones(s_result_enabled) == s_result_count
      && (s_result_enabled >> s_child_count) == 0
      && s_element_count != 0 && s_element_count <= MAX_ELEMENTS
      && s_mtu inside {16'd576, 16'd1500}
      && s_output_format inside {PRISM_FORMAT_INT8, PRISM_FORMAT_FP16,
          PRISM_FORMAT_BF16, PRISM_FORMAT_FP32};

  // Every bit of the packed word has one source lane per value width: the
  // lane whose value of that width covers the bit, in the subtile that
  // places it there.
  for (genvar index = 0; index < 512; index++) begin : pack_bit
    localparam int unsigned BYTE_LANE = (index / 8) % 16;
    localparam int unsigned BYTE_SUBTILE = index / 128;
    localparam int unsigned HALF_LANE = (index / 16) % 16;
    localparam int unsigned HALF_SUBTILE = index / 256;
    localparam int unsigned WORD_LANE = index / 32;
    logic as_byte, as_half, as_word;
    assign as_byte = pack_bytes && s_tile_keep[BYTE_LANE]
        && pack_subtile == 2'(BYTE_SUBTILE);
    assign as_half = pack_halves && s_tile_keep[HALF_LANE]
        && pack_subtile == 2'(HALF_SUBTILE);
    assign as_word = !pack_bytes && !pack_halves && s_tile_keep[WORD_LANE];
    assign pack_next[index] = as_byte ? s_tile_bits[BYTE_LANE*32 + index % 8]
        : as_half ? s_tile_bits[HALF_LANE*32 + index % 16]
        : as_word ? s_tile_bits[index]
        : pack_subtile != 0 && pack_word[index];
  end

  always_comb begin
    candidate_found = 1'b0;
    candidate_slot = '0;
    for (integer slot = 0; slot < 8; slot++) begin
      if (slot >= int'(scan_slot) && slot < int'(child_count_reg)
          && enabled_reg[slot] && !sent_mask_reg[slot]
          && !candidate_found) begin
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
  end

  prism_numbergroup_native_tile_streamer u_streamer (
      .clk(clk), .rst_n(rst_n && !s_clear), .s_reset(state == PREPARE),
      .s_header(packet_header), .s_total_elements(total_reg),
      .s_mtu(mtu_reg), .s_format(format_reg),
      .s_tile_first_element(feed_first_element),
      .s_tile_count(expected_output_count), .s_tile_bits(read_word),
      .s_tile_valid(state == FEED && read_word_valid),
      .s_tile_ready(streamer_tile_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_axis_frame_bytes),
      .m_packet_id(unused_packet_id), .m_last_frame_done(last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(streamer_fault)
  );

  // The operation context and the payload words carry data only. They are
  // written before use in every operation, so they take no reset, and the
  // context is captured without waiting for its own validity check.
  always_ff @(posedge clk) begin
    if (state == IDLE && s_start_valid) begin
      operation_reg <= s_operation;
      total_reg <= s_element_count;
      mtu_reg <= s_mtu;
      format_reg <= s_output_format;
      pack_bytes <= s_output_format == PRISM_FORMAT_INT8;
      pack_halves <= s_output_format inside {PRISM_FORMAT_FP16, PRISM_FORMAT_BF16};
      values_per_tile <= s_output_format == PRISM_FORMAT_INT8 ? 7'd64
          : s_output_format == PRISM_FORMAT_FP32 ? 7'd16 : 7'd32;
      subtiles_per_word <= s_output_format == PRISM_FORMAT_INT8 ? 3'd4
          : s_output_format == PRISM_FORMAT_FP32 ? 3'd1 : 3'd2;
      source_tile_total <= 9'((s_element_count + 32'd15) >> 4);
      packed_tile_total <= s_output_format == PRISM_FORMAT_INT8
          ? 9'((s_element_count + 32'd63) >> 6)
          : s_output_format == PRISM_FORMAT_FP32
              ? 9'((s_element_count + 32'd15) >> 4)
              : 9'((s_element_count + 32'd31) >> 5);
      child_count_reg <= s_child_count;
      enabled_reg <= s_result_enabled;
      local_endpoints_reg <= s_local_endpoints;
      peer_endpoints_reg <= s_peer_endpoints;
      local_ports_reg <= s_local_ports;
      peer_macs_reg <= s_peer_macs;
      local_mac_reg <= s_local_mac;
    end
    // A complete word is written to the memory from its register, one cycle
    // after its last tile.
    if (s_tile_valid && s_tile_ready) pack_word <= pack_next;
    write_slot <= write_index;
    if (write_valid) result_tiles[write_slot] <= pack_word;
    if (state == PREPARE) feed_first_element <= '0;
    else if (feed_advance)
      feed_first_element <= feed_first_element + 32'(expected_output_count);
    if (state == PREPARE || feed_advance) begin
      expected_output_count <= feed_less[32] ? feed_source[6:0] : values_per_tile;
      // After the last tile this is not a count any more; no tile follows it.
      feed_behind <= feed_less[31:0];
    end
    if (feed_read) read_word <= result_tiles[read_issued[7:0]];
  end

  always_ff @(posedge clk) context_checked <= context_good;

  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      state <= IDLE;
      source_issued <= '0;
      source_loaded <= '0;
      write_index <= '0;
      write_valid <= 1'b0;
      collect_open <= 1'b0;
      pack_subtile <= '0;
      read_word_valid <= 1'b0;
      read_issued <= '0;
      tile_loaded <= '0;
      sent_mask_reg <= '0;
      scan_slot <= '0;
      selected_slot <= '0;
    end else begin
      write_valid <= s_tile_valid && s_tile_ready && word_complete;
      case (state)
        // A start is taken in one cycle and judged in the next, on the
        // verdict registered in the cycle of the start.
        IDLE: if (s_start_valid) state <= CHECK;
        CHECK: begin
          if (!context_checked) state <= FAULT;
          else begin
            collect_open <= 1'b1;
            source_issued <= '0;
            source_loaded <= '0;
            write_index <= '0;
            pack_subtile <= '0;
            sent_mask_reg <= '0;
            scan_slot <= '0;
            state <= COLLECT;
          end
        end
        COLLECT: begin
          if (s_tile_valid && !tile_good) begin
            collect_open <= 1'b0;
            state <= FAULT;
          end else begin
            if (request_valid && request_ready)
              source_issued <= source_issued + 9'd1;
            if (s_tile_valid && s_tile_ready) begin
              source_loaded <= source_loaded + 9'd1;
              if (source_loaded + 9'd1 == source_tile_total) collect_open <= 1'b0;
              if (word_complete) begin
                write_index <= write_index + 8'd1;
                pack_subtile <= '0;
              end else pack_subtile <= pack_subtile + 2'd1;
            end
            if (source_loaded == source_tile_total
                && source_issued == source_tile_total)
              state <= PICK;
          end
        end
        PICK: begin
          if (candidate_found) begin
            selected_slot <= candidate_slot;
            state <= PREPARE;
          end else state <= DONE;
        end
        PREPARE: begin
          read_issued <= '0;
          tile_loaded <= '0;
          read_word_valid <= 1'b0;
          state <= FEED;
        end
        FEED: begin
          if (streamer_fault) state <= FAULT;
          else begin
            if (!read_word_valid || streamer_tile_ready) begin
              if (read_issued < packed_tile_total) begin
                read_issued <= read_issued + 9'd1;
                read_word_valid <= 1'b1;
              end else read_word_valid <= 1'b0;
            end
            if (feed_advance) tile_loaded <= tile_loaded + 9'd1;
            if (last_frame_done) begin
              if (read_issued != packed_tile_total
                  || tile_loaded != packed_tile_total)
                state <= FAULT;
              else begin
                sent_mask_reg[selected_slot] <= 1'b1;
                scan_slot <= {1'b0, selected_slot} + 4'd1;
                state <= PICK;
              end
            end
          end
        end
        DONE: begin end
        FAULT: begin end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
