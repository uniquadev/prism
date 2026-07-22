//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_data_depacketizer.sv
// Module: prism_data_depacketizer
// Description: Removes DATA framing and emits aligned arithmetic tiles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_data_depacketizer #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1,
    parameter int unsigned LANES = 16
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_frame_desc_t          s_packet,
    input  prism_pkg::prism_ingress_context_t     s_context,
    input  logic                                  s_packet_valid,
    output logic                                  s_packet_ready,
    input  logic [DATA_W-1:0]                     s_axis_tdata,
    input  logic [DATA_W/8-1:0]                   s_axis_tkeep,
    input  logic                                  s_axis_tlast,
    input  logic [USER_W-1:0]                     s_axis_tuser,
    input  logic                                  s_axis_tvalid,
    output logic                                  s_axis_tready,
    output prism_pkg::prism_tile_meta_t           m_tile_meta,
    output logic [LANES*32-1:0]                   m_element_bits,
    output logic [LANES-1:0]                      m_element_keep,
    output logic                                  m_tile_valid,
    input  logic                                  m_tile_ready
);

  import prism_pkg::*;

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned PREFIX_BYTES = PRISM_ETH_HEADER_BYTES
      + PRISM_CONTROL_WORD_BYTES + PRISM_DATA_HEADER_BYTES;
  localparam int unsigned RESERVOIR_BYTES = KEEP_W * 3;
  localparam int unsigned RESERVOIR_COUNT_W = prism_clog2_safe(RESERVOIR_BYTES + 1);

  logic active;
  logic first_beat;
  logic frame_complete;
  prism_frame_desc_t packet_reg;
  prism_ingress_context_t context_reg;
  logic [RESERVOIR_BYTES*8-1:0] reservoir;
  logic [RESERVOIR_COUNT_W-1:0] reservoir_bytes;
  logic [31:0] payload_bytes_remaining;
  logic [31:0] elements_remaining;
  logic [31:0] elements_emitted;
  logic [15:0] valid_bytes;
  int unsigned bytes_per_element;
  int unsigned tile_elements;
  int unsigned tile_bytes;
  int unsigned beat_skip_bytes;
  int unsigned beat_payload_bytes;
  logic [31:0] global_first_element;
  logic tile_finishes_packet;
  logic tile_transfer;
  logic beat_transfer;
  // The canonical envelopes include validator and selector fields owned by adjacent stages.
  logic unused_packet_fields;
  logic unused_context_fields;
  assign unused_packet_fields = ^packet_reg;
  assign unused_context_fields = ^context_reg;

  initial begin
    if ((DATA_W != 512) || (LANES < 1) || (LANES > 64)
        || (PREFIX_BYTES >= KEEP_W)) begin
      $fatal(1, "prism_data_depacketizer parameters are illegal");
    end
  end

  assign s_packet_ready = !active;
  assign valid_bytes = 16'($countones(s_axis_tkeep));

  always_comb begin
    bytes_per_element = prism_bytes_per_element(context_reg.descriptor.input_format);
    global_first_element = packet_reg.header.data.chunk_index
        * prism_elements_per_chunk(context_reg.descriptor.input_format) + elements_emitted;
    tile_elements = LANES;
    if (tile_elements > elements_remaining) tile_elements = elements_remaining;
    tile_bytes = tile_elements * bytes_per_element;
    tile_finishes_packet = tile_elements == elements_remaining;

    beat_skip_bytes = first_beat ? PREFIX_BYTES : 0;
    beat_payload_bytes = 0;
    if (valid_bytes > 16'(beat_skip_bytes)) begin
      beat_payload_bytes = 32'(valid_bytes) - beat_skip_bytes;
      if (beat_payload_bytes > payload_bytes_remaining) begin
        beat_payload_bytes = payload_bytes_remaining;
      end
    end

    m_element_bits = '0;
    m_element_keep = '0;
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      if (lane < tile_elements) begin
        m_element_keep[lane] = 1'b1;
        for (int unsigned octet = 0; octet < 4; octet++) begin
          if (octet < bytes_per_element) begin
            m_element_bits[lane*32 + octet*8 +: 8] =
                reservoir[(lane*bytes_per_element + octet)*8 +: 8];
          end
        end
      end
    end

    m_tile_meta = '0;
    m_tile_meta.key = packet_reg.header.data.key;
    m_tile_meta.first_element = global_first_element;
    m_tile_meta.contributor_id = packet_reg.header.data.contributor_id;
    m_tile_meta.operation_slot = context_reg.operation_slot;
    m_tile_meta.group_slot = context_reg.group_slot;
    m_tile_meta.expected_contributors = context_reg.expected_contributors;
    m_tile_meta.input_format = context_reg.descriptor.input_format;
    m_tile_meta.output_format = context_reg.descriptor.output_format;
    m_tile_meta.accumulator_profile = context_reg.descriptor.accumulator_profile;
    m_tile_meta.selected_width_index = context_reg.selected_width_index;
    m_tile_meta.semantic = context_reg.descriptor.semantic;
    m_tile_meta.total_element_count = context_reg.descriptor.element_count;
    m_tile_meta.result_route_count = context_reg.descriptor.result_route_count;
    m_tile_meta.element_count = 8'(tile_elements);
    m_tile_meta.flags = packet_reg.header.data.flags
        | (context_reg.accumulation_inexact
            ? PRISM_DATA_FLAG_ACCUMULATION_INEXACT : 8'b0);
    m_tile_meta.last_tile = tile_finishes_packet;
  end

  assign m_tile_valid = active && (tile_elements != 0) && (bytes_per_element != 0)
      && (reservoir_bytes >= RESERVOIR_COUNT_W'(tile_bytes));
  assign tile_transfer = m_tile_valid && m_tile_ready;
  assign s_axis_tready = active && !frame_complete
      && ((32'(reservoir_bytes) + beat_payload_bytes) <= RESERVOIR_BYTES);
  assign beat_transfer = s_axis_tvalid && s_axis_tready;

  always_ff @(posedge clk) begin : update_reservoir
    logic [RESERVOIR_BYTES*8-1:0] next_reservoir;
    integer next_count;
    integer append_count;
    integer source_index;
    if (!rst_n) begin
      active <= 1'b0;
      first_beat <= 1'b1;
      frame_complete <= 1'b0;
      packet_reg <= '0;
      context_reg <= '0;
      reservoir <= '0;
      reservoir_bytes <= '0;
      payload_bytes_remaining <= '0;
      elements_remaining <= '0;
      elements_emitted <= '0;
    end else begin
      next_reservoir = reservoir;
      next_count = 32'(reservoir_bytes);

      if (tile_transfer) begin
        next_reservoir = reservoir >> (tile_bytes * 8);
        next_count = next_count - tile_bytes;
        elements_remaining <= elements_remaining - tile_elements;
        elements_emitted <= elements_emitted + tile_elements;
      end

      if (beat_transfer) begin
        append_count = beat_payload_bytes;
        for (int unsigned octet = 0; octet < KEEP_W; octet++) begin
          source_index = beat_skip_bytes + octet;
          if ((octet < append_count) && (next_count + octet < RESERVOIR_BYTES)) begin
            next_reservoir[(next_count + octet)*8 +: 8] =
                s_axis_tdata[source_index*8 +: 8];
          end
        end
        next_count = next_count + append_count;
        payload_bytes_remaining <= payload_bytes_remaining - append_count;
        first_beat <= 1'b0;
        if (s_axis_tlast) frame_complete <= 1'b1;
      end

      reservoir <= next_reservoir;
      reservoir_bytes <= RESERVOIR_COUNT_W'(next_count);

      if (s_packet_valid && s_packet_ready) begin
        packet_reg <= s_packet;
        context_reg <= s_context;
        active <= 1'b1;
        first_beat <= 1'b1;
        frame_complete <= 1'b0;
        reservoir <= '0;
        reservoir_bytes <= '0;
        elements_remaining <= ((32'(s_packet.header.data.chunk_index) + 32'd1)
            * prism_elements_per_chunk(s_context.descriptor.input_format)
            > s_context.descriptor.element_count)
            ? s_context.descriptor.element_count
                - (s_packet.header.data.chunk_index
                    * prism_elements_per_chunk(s_context.descriptor.input_format))
            : prism_elements_per_chunk(s_context.descriptor.input_format);
        payload_bytes_remaining <= (((32'(s_packet.header.data.chunk_index) + 32'd1)
            * prism_elements_per_chunk(s_context.descriptor.input_format)
            > s_context.descriptor.element_count)
            ? s_context.descriptor.element_count
                - (s_packet.header.data.chunk_index
                    * prism_elements_per_chunk(s_context.descriptor.input_format))
            : prism_elements_per_chunk(s_context.descriptor.input_format))
            * prism_bytes_per_element(s_context.descriptor.input_format);
        elements_emitted <= '0;
      end

      if (active && frame_complete && (elements_remaining == 0)) begin
        active <= 1'b0;
        frame_complete <= 1'b0;
      end
    end
  end

  logic unused_user;
  assign unused_user = ^s_axis_tuser;

endmodule
