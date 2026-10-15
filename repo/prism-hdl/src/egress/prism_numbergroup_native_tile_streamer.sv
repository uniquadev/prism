//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_native_tile_streamer.sv
// Module: prism_numbergroup_native_tile_streamer
// Description: Ping-pong native tiles into MTU-bounded NumberGroup frames.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// A tile is applied to its frame in the cycle it is taken and checked beside
// that: the result of the checks is a register. A tile that fails raises the
// fault in the next cycle, and in that cycle its frame is withheld from the
// output and put back as it was, so neither the tile nor anything after it
// leaves. The checks therefore gate two registers instead of the frame state.
module prism_numbergroup_native_tile_streamer #(
    parameter int unsigned MTU_BYTES = 1500,
    parameter int unsigned TILES_PER_FRAME = 22,
    parameter prism_pkg::prism_opcode_e PACKET_CLASS = prism_pkg::PRISM_OP_COL_RES
) (
    input  logic                                 clk,
    input  logic                                 rst_n,
    input  logic                                 s_reset,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                          s_total_elements,
    input  logic [15:0]                          s_mtu,
    input  logic [7:0]                           s_format,
    input  logic [31:0]                          s_tile_first_element,
    input  logic [6:0]                           s_tile_count,
    input  logic [511:0]                         s_tile_bits,
    input  logic                                 s_tile_valid,
    output logic                                 s_tile_ready,
    output logic [511:0]                         m_axis_tdata,
    output logic [63:0]                          m_axis_tkeep,
    output logic                                 m_axis_tlast,
    output logic [15:0]                          m_frame_bytes,
    output logic [31:0]                          m_packet_id,
    output logic                                 m_last_frame_done,
    output logic                                 m_axis_tvalid,
    input  logic                                 m_axis_tready,
    output logic                                 m_fault
);

  import prism_pkg::*;

  localparam int unsigned TILE_W = $clog2(TILES_PER_FRAME + 1);
  typedef enum logic [1:0] {EMPTY, FILL, READY, SEND} buffer_state_t;
  typedef enum logic [1:0] {OUT_IDLE, OUT_PREFETCH, OUT_SEND} output_state_t;

  buffer_state_t buffer_state [0:1];
  output_state_t output_state;
  // Frame payload lives in one distributed RAM with a single write and a
  // single read port. Word 0 of each bank is also kept in registers, because
  // a frame start consumes it in the same cycle that word 1 is read.
  (* ram_style = "distributed" *) logic [511:0] tile_ram [0:(2 << TILE_W)-1];
  logic [511:0] first_word [0:1];
  logic [511:0] masked_tile;
  logic [8:0] tile_bytes;
  logic [TILE_W:0] ram_read_address;
  logic [TILE_W-1:0] tile_counts [0:1];
  logic [15:0] element_counts [0:1];
  logic [31:0] first_elements [0:1];
  logic [31:0] packet_ids [0:1];
  logic [1:0] last_flags;
  prism_numbergroup_header_t base_headers [0:1];
  logic [479:0] selected_prefix, handoff_prefix, header_prefix;
  logic fill_bank, send_bank, out_bank;
  logic [31:0] next_global, packet_serial;
  logic [31:0] total_reg;
  logic [15:0] mtu_reg;
  logic [7:0] format_reg;
  logic [2:0] value_bytes;
  logic [6:0] values_per_tile;
  logic [TILE_W-1:0] tile_limit;
  logic total_known;
  logic [32:0] incoming_end;
  logic [511:0] read_word;
  logic [TILE_W-1:0] read_address;
  logic read_bank;
  logic [479:0] previous_tail;
  logic [TILE_W:0] beat_index;
  logic [15:0] remaining_bytes;
  logic [15:0] frame_length;
  logic handoff, handoff_pending;
  logic tile_fire, tile_reject, bank_open, beat_fire, frame_end;
  // The tile taken in the cycle before failed its checks; the bank it went
  // to, and whether it opened that bank.
  logic refused, tile_bank, tile_opened;
  logic [1:0] sendable, vacant;
  // Elements still expected by the operation; replaces end-of-vector compares.
  logic [31:0] elements_left, elements_left_reg;
  logic [32:0] packet_id_sum;

  function automatic logic [15:0] frame_bytes(
      input logic [15:0] count, input logic [7:0] format);
    logic [15:0] payload_bytes;
    payload_bytes = count * (format == PRISM_FORMAT_INT8 ? 16'd1
        : format == PRISM_FORMAT_FP32 ? 16'd4 : 16'd2);
    return 16'd60 + ((payload_bytes + 16'd3) & 16'hfffc);
  endfunction

  initial begin
    if (MTU_BYTES < 576 || MTU_BYTES > 1500 || TILES_PER_FRAME < 1
        || TILES_PER_FRAME > 22 || 42 + 4 + 64 * TILES_PER_FRAME > MTU_BYTES)
      $fatal(1, "Native tile streamer requires bounded 1500-byte frame buffers");
    if (PACKET_CLASS != PRISM_OP_COL_DATA && PACKET_CLASS != PRISM_OP_COL_RES)
      $fatal(1, "Native tile streamer requires DATA or RESULT packet class");
  end

  assign s_tile_ready = !m_fault && !s_reset
      && (buffer_state[fill_bank] == EMPTY || buffer_state[fill_bank] == FILL);
  assign value_bytes = s_format == PRISM_FORMAT_INT8 ? 3'd1
      : s_format == PRISM_FORMAT_FP32 ? 3'd4 : 3'd2;
  assign values_per_tile = 7'(64 / int'(value_bytes));
  assign tile_limit = TILE_W'((s_mtu - 16'd46) >> 6);
  assign incoming_end = {1'b0, next_global} + 33'(s_tile_count);
  assign tile_bytes = s_format == PRISM_FORMAT_INT8 ? 9'(s_tile_count)
      : s_format == PRISM_FORMAT_FP32 ? {s_tile_count, 2'b00} : {1'b0, s_tile_count, 1'b0};
  for (genvar byte_index = 0; byte_index < 64; byte_index++) begin : mask_byte
    assign masked_tile[byte_index*8 +: 8] = byte_index < int'(tile_bytes)
        ? s_tile_bits[byte_index*8 +: 8] : 8'd0;
  end
  // The last beat of a frame needs no further word of that frame, so the read
  // address can turn to the next frame without waiting for the output ready.
  assign ram_read_address = handoff_pending ? {!out_bank, TILE_W'(1)}
      : {read_bank, read_address};
  for (genvar byte_index = 0; byte_index < 64; byte_index++) begin : keep_byte
    assign m_axis_tkeep[byte_index] = remaining_bytes > 16'(byte_index);
  end
  assign m_axis_tlast = m_axis_tvalid && remaining_bytes <= 16'd64;
  assign m_frame_bytes = frame_length;
  assign m_packet_id = packet_ids[out_bank];
  assign m_last_frame_done = output_state == OUT_SEND && m_axis_tvalid
      && m_axis_tready && m_axis_tlast && last_flags[out_bank];
  assign read_bank = output_state == OUT_IDLE ? send_bank : out_bank;
  for (genvar bank = 0; bank < 2; bank++) begin : bank_flags
    assign sendable[bank] = buffer_state[bank] == READY
        && !(refused && tile_bank == 1'(bank));
    assign vacant[bank] = buffer_state[bank] == EMPTY
        || (refused && tile_opened && tile_bank == 1'(bank));
  end
  assign handoff_pending = output_state == OUT_SEND && m_axis_tvalid
      && remaining_bytes <= 16'd64 && sendable[!out_bank];
  assign handoff = handoff_pending && m_axis_tready;

  function automatic logic [479:0] frame_prefix(
      input prism_numbergroup_header_t base,
      input logic [31:0] packet_id,
      input logic [31:0] first_element,
      input logic [15:0] element_count,
      input logic last_flag,
      input logic [7:0] format
  );
    prism_numbergroup_header_t header;
    logic [447:0] bytes;
    logic [479:0] prefix;
    header = base;
    header.ethertype = PRISM_ETHERTYPE;
    header.version = 8'h20;
    header.packet_class = PACKET_CLASS;
    header.packet_id = packet_id;
    header.first_element = first_element;
    header.element_count = element_count;
    header.group_count = 8'd1;
    header.flags = {7'd0, last_flag};
    header.body_bytes = frame_bytes(element_count, format) - 16'd56;
    header.reserved = '0;
    bytes = {
        header.destination_mac, header.source_mac, header.ethertype,
        header.version, header.packet_class, header.key.job_id,
        header.key.group_id, header.key.group_generation,
        header.key.operation_id, header.key.operation_generation,
        header.source_endpoint, header.destination_endpoint,
        header.packet_id, header.first_element, header.element_count,
        header.group_count, header.flags, header.body_bytes,
        header.stream_id, header.reserved
    };
    prefix = '0;
    for (integer byte_index = 0; byte_index < 56; byte_index++)
      prefix[byte_index*8 +: 8] = bytes[(55-byte_index)*8 +: 8];
    prefix[56*8 +: 8] = format;
    prefix[58*8 +: 8] = element_count[15:8];
    prefix[59*8 +: 8] = element_count[7:0];
    return prefix;
  endfunction

  assign selected_prefix = frame_prefix(
      base_headers[send_bank], packet_ids[send_bank],
      first_elements[send_bank], element_counts[send_bank],
      last_flags[send_bank], format_reg);
  assign handoff_prefix = frame_prefix(
      base_headers[!out_bank], packet_ids[!out_bank],
      first_elements[!out_bank], element_counts[!out_bank],
      last_flags[!out_bank], format_reg);

  // A refused tile is written too; its bank is put back, so the word is
  // never read.
  always_ff @(posedge clk) begin
    if (s_tile_valid && s_tile_ready) begin
      tile_ram[{fill_bank, tile_counts[fill_bank]}] <= masked_tile;
      if (tile_counts[fill_bank] == 0) first_word[fill_bank] <= masked_tile;
    end
  end

  always_ff @(posedge clk) begin
    if (handoff || output_state == OUT_PREFETCH
        || (output_state == OUT_SEND && m_axis_tvalid && m_axis_tready))
      read_word <= tile_ram[ram_read_address];
  end

  assign tile_fire = s_tile_valid && s_tile_ready;
  assign elements_left = total_known ? elements_left_reg : s_total_elements;
  assign packet_id_sum = {1'b0, s_header.packet_id} + {1'b0, packet_serial};
  assign bank_open = buffer_state[fill_bank] == EMPTY;
  assign tile_reject = s_total_elements == 0
      || (total_known && s_total_elements != total_reg)
      || s_mtu < 16'd576 || s_mtu > 16'(MTU_BYTES)
      || (total_known && s_mtu != mtu_reg)
      || !(s_format inside {PRISM_FORMAT_INT8, PRISM_FORMAT_FP16,
          PRISM_FORMAT_BF16, PRISM_FORMAT_FP32})
      || (total_known && s_format != format_reg)
      || s_tile_first_element != next_global
      || (s_tile_first_element & (32'(values_per_tile) - 32'd1)) != 0
      || s_tile_count == 0 || s_tile_count > values_per_tile
      || 32'(s_tile_count) > elements_left
      || (s_tile_count != values_per_tile && 32'(s_tile_count) != elements_left)
      || (bank_open && packet_id_sum[32])
      || int'(tile_counts[fill_bank]) >= TILES_PER_FRAME;
  // The elements of a frame need no check of their own: a frame holds fewer
  // than TILES_PER_FRAME tiles when a tile is added, and no tile has more
  // than values_per_tile elements.
  assign beat_fire = output_state == OUT_SEND && m_axis_tvalid && m_axis_tready;
  assign frame_end = beat_fire && remaining_bytes <= 16'd64;

  // Frame context and output words carry data only. Each is written before
  // it is used, so none of them takes a reset.
  always_ff @(posedge clk) begin
    if (tile_fire) begin
      // The first tile sets what every later tile is checked against.
      if (!total_known) begin
        total_reg <= s_total_elements;
        mtu_reg <= s_mtu;
        format_reg <= s_format;
      end
      elements_left_reg <= elements_left - 32'(s_tile_count);
      if (bank_open) begin
        base_headers[fill_bank] <= s_header;
        first_elements[fill_bank] <= s_tile_first_element;
        packet_ids[fill_bank] <= packet_id_sum[31:0];
      end
      tile_bank <= fill_bank;
      tile_opened <= bank_open;
    end
    if (output_state == OUT_IDLE && buffer_state[send_bank] == READY) begin
      header_prefix <= selected_prefix;
      frame_length <= frame_bytes(element_counts[send_bank], format_reg);
    end
    if (output_state == OUT_PREFETCH) begin
      m_axis_tdata <= {first_word[out_bank][31:0], header_prefix};
      previous_tail <= first_word[out_bank][511:32];
    end
    if (handoff) begin
      header_prefix <= handoff_prefix;
      frame_length <= frame_bytes(element_counts[!out_bank], format_reg);
      m_axis_tdata <= {first_word[!out_bank][31:0], handoff_prefix};
      previous_tail <= first_word[!out_bank][511:32];
    end else if (beat_fire && !frame_end) begin
      if (int'(beat_index) + 1 < int'(tile_counts[out_bank])) begin
        m_axis_tdata <= {read_word[31:0], previous_tail};
        previous_tail <= read_word[511:32];
      end else m_axis_tdata <= {32'd0, previous_tail};
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      buffer_state[0] <= EMPTY;
      buffer_state[1] <= EMPTY;
      tile_counts[0] <= '0;
      tile_counts[1] <= '0;
      element_counts[0] <= '0;
      element_counts[1] <= '0;
      last_flags <= '0;
      fill_bank <= 1'b0;
      send_bank <= 1'b0;
      out_bank <= 1'b0;
      next_global <= '0;
      packet_serial <= '0;
      total_known <= 1'b0;
      output_state <= OUT_IDLE;
      read_address <= '0;
      beat_index <= '0;
      remaining_bytes <= '0;
      m_axis_tvalid <= 1'b0;
      m_fault <= 1'b0;
      refused <= 1'b0;
    end else begin
      refused <= tile_fire && tile_reject;
      // The bank of a refused tile goes back to what it was; no tile is
      // taken in this cycle, because the fault is already up.
      if (refused) begin
        fill_bank <= tile_bank;
        if (tile_opened) begin
          buffer_state[tile_bank] <= EMPTY;
          tile_counts[tile_bank] <= '0;
          element_counts[tile_bank] <= '0;
        end else buffer_state[tile_bank] <= FILL;
      end
      if (s_reset && output_state == OUT_IDLE && vacant == 2'b11) begin
        fill_bank <= 1'b0;
        send_bank <= 1'b0;
        next_global <= '0;
        packet_serial <= '0;
        total_known <= 1'b0;
        m_fault <= 1'b0;
      end
      if (tile_fire) begin
        if (tile_reject) m_fault <= 1'b1;
        total_known <= 1'b1;
        tile_counts[fill_bank] <= tile_counts[fill_bank] + TILE_W'(1);
        next_global <= incoming_end[31:0];
        if (bank_open) element_counts[fill_bank] <= 16'(s_tile_count);
        else element_counts[fill_bank]
            <= element_counts[fill_bank] + 16'(s_tile_count);
        if (int'(tile_counts[fill_bank]) + 1 == int'(tile_limit)
            || 32'(s_tile_count) == elements_left) begin
          buffer_state[fill_bank] <= READY;
          last_flags[fill_bank] <= 32'(s_tile_count) == elements_left;
          packet_serial <= packet_serial + 32'd1;
          fill_bank <= !fill_bank;
        end else buffer_state[fill_bank] <= FILL;
      end
      case (output_state)
        OUT_IDLE: begin
          if (sendable[send_bank]) begin
            buffer_state[send_bank] <= SEND;
            out_bank <= send_bank;
            remaining_bytes <= frame_bytes(element_counts[send_bank], format_reg);
            beat_index <= '0;
            read_address <= TILE_W'(1);
            output_state <= OUT_PREFETCH;
          end
        end
        OUT_PREFETCH: begin
          m_axis_tvalid <= 1'b1;
          read_address <= TILE_W'(2);
          output_state <= OUT_SEND;
        end
        OUT_SEND: begin
          if (frame_end) begin
            buffer_state[out_bank] <= EMPTY;
            tile_counts[out_bank] <= '0;
            element_counts[out_bank] <= '0;
            send_bank <= !send_bank;
            if (handoff) begin
              buffer_state[!out_bank] <= SEND;
              out_bank <= !out_bank;
              remaining_bytes <= frame_bytes(element_counts[!out_bank], format_reg);
              beat_index <= '0;
              read_address <= TILE_W'(2);
            end else begin
              m_axis_tvalid <= 1'b0;
              remaining_bytes <= '0;
              output_state <= OUT_IDLE;
            end
          end else if (beat_fire) begin
            remaining_bytes <= remaining_bytes - 16'd64;
            beat_index <= beat_index + 1'b1;
            if (int'(beat_index) + 1 < int'(tile_counts[out_bank]))
              read_address <= read_address + TILE_W'(1);
          end
        end
        default: output_state <= OUT_IDLE;
      endcase
    end
  end
endmodule
