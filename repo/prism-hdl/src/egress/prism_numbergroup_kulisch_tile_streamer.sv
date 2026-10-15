//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_kulisch_tile_streamer.sv
// Module: prism_numbergroup_kulisch_tile_streamer
// Description: Packs exact values into two alternating AXI frame buffers.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_kulisch_tile_streamer #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MTU_BYTES = 1500,
    parameter prism_pkg::prism_opcode_e PACKET_CLASS = prism_pkg::PRISM_OP_COL_DATA
) (
    input  logic                                 clk,
    input  logic                                 rst_n,
    input  logic                                 s_reset,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                          s_total_elements,
    input  logic [15:0]                          s_mtu,
    input  logic [31:0]                          s_tile_first_element,
    input  logic [1:0]                           s_tile_count,
    input  logic [15:0]                          s_tags,
    input  logic [2*KULISCH_W-1:0]               s_integers,
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

  localparam int unsigned INTEGER_BYTES = (KULISCH_W + 7) / 8;
  localparam int unsigned PAD_W = INTEGER_BYTES * 8;
  localparam int unsigned VALUE_BYTES = INTEGER_BYTES + 1;
  localparam int unsigned VALUE_W = VALUE_BYTES * 8;
  localparam int unsigned VALUES_PER_FRAME = (MTU_BYTES - 60) / VALUE_BYTES;
  localparam int unsigned MAX_BEATS = (MTU_BYTES + 63) / 64;
  localparam int unsigned COUNT_W = $clog2(VALUES_PER_FRAME + 1);
  localparam int unsigned BEAT_W = $clog2(MAX_BEATS + 1);
  localparam int unsigned STAGE_W = 1024 + 3 * VALUE_W;
  localparam int unsigned STAGE_COUNT_W = $clog2(STAGE_W + 1);

  typedef enum logic [1:0] {EMPTY, FILL, READY, SEND} buffer_state_t;
  buffer_state_t buffer_state [0:1];
  logic [511:0] beats [0:1][0:MAX_BEATS-1];
  logic [15:0] frame_lengths [0:1];
  logic [31:0] packet_ids [0:1];
  logic [1:0] last_flags;
  logic fill_bank, send_bank, out_bank;
  logic [31:0] next_global, packet_serial, total_reg;
  logic [15:0] mtu_reg, mtu_sampled;
  logic total_known;
  logic capacity_valid;
  logic [COUNT_W-1:0] frame_capacity, frame_target, received_count;
  logic [COUNT_W-1:0] active_target_reg;
  logic [BEAT_W-1:0] write_index, read_index;
  logic [STAGE_W-1:0] stage_bits, append_bits, packed_bits;
  logic [STAGE_COUNT_W-1:0] stage_count;
  logic [STAGE_COUNT_W:0] packed_count;
  logic [2*VALUE_W-1:0] pair_bits;
  logic [15:0] incoming_frame_length, output_remaining;
  logic [31:0] remaining_elements;
  logic [15:0] value_limit;
  logic [32:0] incoming_end;
  logic [COUNT_W:0] received_next;
  logic start_frame, tile_fire, input_complete, write_beat, last_write;
  logic input_valid;

  initial begin
    if (KULISCH_W < 278 || KULISCH_W > 4096
        || MTU_BYTES < 576 || MTU_BYTES > 1500
        || VALUES_PER_FRAME < 1 || MAX_BEATS < 9)
      $fatal(1, "Kulisch tile streamer cannot fit a concrete element");
  end

  function automatic logic [15:0] frame_bytes(input logic [COUNT_W-1:0] count);
    logic [15:0] payload;
    payload = 16'(count) * 16'(VALUE_BYTES);
    return 16'd60 + ((payload + 16'd3) & 16'hfffc);
  endfunction

  function automatic logic [479:0] frame_prefix(
      input prism_numbergroup_header_t base,
      input logic [31:0] packet_id,
      input logic [31:0] first_element,
      input logic [COUNT_W-1:0] element_count,
      input logic last_flag
  );
    prism_numbergroup_header_t header;
    logic [447:0] header_bytes;
    logic [479:0] prefix;
    header = base;
    header.ethertype = PRISM_ETHERTYPE;
    header.version = 8'h20;
    header.packet_class = PACKET_CLASS;
    header.packet_id = packet_id;
    header.first_element = first_element;
    header.element_count = 16'(element_count);
    header.group_count = 8'd1;
    header.flags = {7'd0, last_flag};
    header.body_bytes = frame_bytes(element_count) - 16'd56;
    header.reserved = '0;
    header_bytes = {
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
      prefix[byte_index*8 +: 8] = header_bytes[(55-byte_index)*8 +: 8];
    prefix[56*8 +: 8] = PRISM_FORMAT_KULISCH;
    prefix[58*8 +: 8] = 8'(element_count >> 8);
    prefix[59*8 +: 8] = 8'(element_count);
    return prefix;
  endfunction

  assign remaining_elements = s_total_elements - next_global;
  assign value_limit = s_mtu >= 16'd60
      ? 16'((int'(s_mtu) - 60) / VALUE_BYTES) : 16'd0;
  assign frame_target = remaining_elements < 32'(frame_capacity)
      ? COUNT_W'(remaining_elements)
      : remaining_elements > 32'(frame_capacity)
          && frame_capacity > COUNT_W'(1) && frame_capacity[0]
      ? frame_capacity - COUNT_W'(1) : frame_capacity;
  assign start_frame = buffer_state[fill_bank] == EMPTY;
  assign incoming_frame_length = frame_bytes(frame_target);
  assign incoming_end = {1'b0, next_global} + 33'(s_tile_count);
  assign received_next = start_frame
      ? (COUNT_W+1)'(s_tile_count)
      : {1'b0, received_count} + (COUNT_W+1)'(s_tile_count);
  assign input_complete = start_frame
      ? received_next == {1'b0, frame_target}
      : received_next == {1'b0, active_target_reg};
  assign tile_fire = s_tile_valid && s_tile_ready;
  assign s_tile_ready = !m_fault && !s_reset
      && (VALUES_PER_FRAME == 1 || (capacity_valid && mtu_sampled == s_mtu))
      && (start_frame || (buffer_state[fill_bank] == FILL
          && received_count < active_target_reg))
      && (start_frame
          ? 480 + 2 * VALUE_W <= STAGE_W
          : int'(stage_count) + 2 * VALUE_W <= STAGE_W);
  assign m_axis_tkeep = output_remaining >= 16'd64 ? '1
      : (64'h1 << output_remaining) - 64'd1;
  assign m_axis_tlast = m_axis_tvalid && output_remaining <= 16'd64;
  assign m_frame_bytes = frame_lengths[out_bank];
  assign m_packet_id = packet_ids[out_bank];
  assign m_last_frame_done = m_axis_tvalid && m_axis_tready
      && m_axis_tlast && last_flags[out_bank];

  always_comb begin
    input_valid = s_tile_count inside {2'd1, 2'd2};
    pair_bits = '0;
    for (integer lane = 0; lane < 2; lane++) begin
      if (lane < int'(s_tile_count)) begin
        if (s_tags[lane*8 +: 8] > 8'd5
            || ((s_tags[lane*8 +: 8] == 0)
                != (s_integers[lane*KULISCH_W +: KULISCH_W] != 0))
            || (s_tags[lane*8 +: 8] != 0
                && s_integers[lane*KULISCH_W +: KULISCH_W] != 0))
          input_valid = 1'b0;
        pair_bits[lane*VALUE_W +: VALUE_W] = {
            {{(PAD_W-KULISCH_W){s_integers[(lane+1)*KULISCH_W-1]}},
             s_integers[lane*KULISCH_W +: KULISCH_W]},
            s_tags[lane*8 +: 8]
        };
      end
    end
  end

  always_comb begin
    append_bits = stage_bits;
    packed_count = {1'b0, stage_count};
    if (tile_fire) begin
      if (start_frame) begin
        append_bits = STAGE_W'(frame_prefix(s_header,
            s_header.packet_id + packet_serial, next_global, frame_target,
            next_global + 32'(frame_target) == s_total_elements));
        packed_count = (STAGE_COUNT_W+1)'(480);
      end
      append_bits |= STAGE_W'(pair_bits) << packed_count;
      packed_count += (STAGE_COUNT_W+1)'(int'(s_tile_count) * VALUE_W);
    end
  end
  assign write_beat = (buffer_state[fill_bank] == FILL || tile_fire)
      && (packed_count >= (STAGE_COUNT_W+1)'(512)
          || ((tile_fire && input_complete
              || !start_frame && received_count == active_target_reg)
              && packed_count != 0));
  assign last_write = write_beat
      && (tile_fire && input_complete
          || !start_frame && received_count == active_target_reg)
      && packed_count <= (STAGE_COUNT_W+1)'(512);

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      buffer_state[0] <= EMPTY;
      buffer_state[1] <= EMPTY;
      frame_lengths[0] <= '0;
      frame_lengths[1] <= '0;
      packet_ids[0] <= '0;
      packet_ids[1] <= '0;
      last_flags <= '0;
      fill_bank <= 1'b0;
      send_bank <= 1'b0;
      out_bank <= 1'b0;
      next_global <= '0;
      packet_serial <= '0;
      total_reg <= '0;
      mtu_reg <= '0;
      mtu_sampled <= '0;
      frame_capacity <= COUNT_W'(VALUES_PER_FRAME == 1 ? 1 : 0);
      capacity_valid <= 1'b0;
      total_known <= 1'b0;
      received_count <= '0;
      active_target_reg <= '0;
      write_index <= '0;
      read_index <= '0;
      stage_bits <= '0;
      stage_count <= '0;
      output_remaining <= '0;
      m_axis_tdata <= '0;
      m_axis_tvalid <= 1'b0;
      m_fault <= 1'b0;
    end else begin
      // MTU is operation configuration. Register its division before accepting
      // data so it cannot sit on the arithmetic/egress ready path.
      mtu_sampled <= s_mtu;
      frame_capacity <= COUNT_W'(value_limit > 16'(VALUES_PER_FRAME)
          ? VALUES_PER_FRAME : value_limit);
      capacity_valid <= 1'b1;
      if (s_reset && !m_axis_tvalid
          && buffer_state[0] == EMPTY && buffer_state[1] == EMPTY) begin
        fill_bank <= 1'b0;
        send_bank <= 1'b0;
        next_global <= '0;
        packet_serial <= '0;
        total_known <= 1'b0;
        m_fault <= 1'b0;
      end

      if (tile_fire) begin
        if (!input_valid || s_total_elements == 0
            || s_mtu < 16'd576 || s_mtu > 16'(MTU_BYTES)
            || frame_target == 0 || incoming_frame_length > s_mtu
            || (total_known && (s_total_elements != total_reg
                || s_mtu != mtu_reg))
            || s_tile_first_element != next_global
            || incoming_end > {1'b0, s_total_elements}
            || received_next > {1'b0, start_frame
                ? frame_target : active_target_reg}
            || (start_frame && packet_serial > 32'hffff_ffff - s_header.packet_id))
          m_fault <= 1'b1;
        else begin
          next_global <= incoming_end[31:0];
          total_reg <= s_total_elements;
          mtu_reg <= s_mtu;
          total_known <= 1'b1;
          received_count <= COUNT_W'(received_next);
          if (start_frame) begin
            active_target_reg <= frame_target;
            frame_lengths[fill_bank] <= incoming_frame_length;
            packet_ids[fill_bank] <= s_header.packet_id + packet_serial;
            last_flags[fill_bank] <= next_global + 32'(frame_target)
                == s_total_elements;
            buffer_state[fill_bank] <= FILL;
          end
        end
      end

      if (write_beat && !m_fault) begin
        if (int'(write_index) >= MAX_BEATS) m_fault <= 1'b1;
        else beats[fill_bank][write_index] <= append_bits[511:0];
        write_index <= write_index + BEAT_W'(1);
        stage_bits <= append_bits >> 512;
        stage_count <= packed_count > (STAGE_COUNT_W+1)'(512)
            ? STAGE_COUNT_W'(packed_count - (STAGE_COUNT_W+1)'(512)) : '0;
      end else if (tile_fire) begin
        stage_bits <= append_bits;
        stage_count <= STAGE_COUNT_W'(packed_count);
      end

      if (last_write && !m_fault) begin
        buffer_state[fill_bank] <= READY;
        fill_bank <= !fill_bank;
        packet_serial <= packet_serial + 32'd1;
        received_count <= '0;
        active_target_reg <= '0;
        write_index <= '0;
        stage_bits <= '0;
        stage_count <= '0;
      end

      if (m_axis_tvalid && m_axis_tready) begin
        if (output_remaining <= 16'd64) begin
          buffer_state[out_bank] <= EMPTY;
          send_bank <= !send_bank;
          // The next bank may finish packing on this same clock edge.
          if (buffer_state[!out_bank] == READY
              || (last_write && fill_bank == !out_bank && !m_fault)) begin
            out_bank <= !out_bank;
            buffer_state[!out_bank] <= SEND;
            read_index <= '0;
            output_remaining <= frame_lengths[!out_bank];
            m_axis_tdata <= beats[!out_bank][0];
          end else begin
            m_axis_tvalid <= 1'b0;
            output_remaining <= '0;
          end
        end else begin
          read_index <= read_index + BEAT_W'(1);
          output_remaining <= output_remaining - 16'd64;
          m_axis_tdata <= beats[out_bank][read_index + BEAT_W'(1)];
        end
      end else if (!m_axis_tvalid && buffer_state[send_bank] == READY) begin
        out_bank <= send_bank;
        buffer_state[send_bank] <= SEND;
        read_index <= '0;
        output_remaining <= frame_lengths[send_bank];
        m_axis_tdata <= beats[send_bank][0];
        m_axis_tvalid <= 1'b1;
      end
    end
  end

endmodule
