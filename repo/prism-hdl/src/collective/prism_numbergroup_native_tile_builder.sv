//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_native_tile_builder.sv
// Module: prism_numbergroup_native_tile_builder
// Description: Places validated native values in global range/lane positions.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Values arrive byte by byte and are collected into a tile of sixteen lanes.
// An accepted byte is first registered with its position and written into
// the tile one cycle later, so the byte and the logic that accepts it do not
// reach every byte of the tile in the same cycle. The tile is therefore
// offered two cycles after its last byte.
module prism_numbergroup_native_tile_builder #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned TILE_ELEMENTS = 16,
    parameter int unsigned ISSUE_SLICES = 4
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_tile_meta_t           s_base_meta,
    input  logic [31:0]                           s_global_index,
    input  logic [7:0]                            s_format,
    input  logic [15:0]                           s_byte_index,
    input  logic [7:0]                            s_value_byte,
    input  logic                                  s_element_last_byte,
    input  logic                                  s_packet_last_byte,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output prism_pkg::prism_tile_meta_t           m_meta,
    output logic [DATA_W-1:0]                     m_element_bits,
    output logic [ISSUE_SLICES*TILE_ELEMENTS-1:0] m_element_keep,
    output logic                                  m_valid,
    input  logic                                  m_ready
);

  import prism_pkg::*;

  typedef enum logic [1:0] {BUILD, FLUSH, EMIT} state_t;
  state_t state;
  logic write_valid;
  logic [$clog2(DATA_W/8)-1:0] write_slot;
  logic [7:0] write_byte;
  logic have_tile;
  logic [31:0] tile_first;
  logic [7:0] tile_format;
  logic [DATA_W-1:0] tile_bits;
  logic [TILE_ELEMENTS-1:0] tile_keep;
  logic [7:0] tile_count;
  prism_tile_meta_t base_meta_reg;
  logic [31:0] incoming_first;
  logic boundary;
  logic [2:0] value_width;
  int unsigned byte_slot;
  int unsigned lane;

  initial begin
    if (DATA_W != 512 || TILE_ELEMENTS != 16 || ISSUE_SLICES < 1
        || ISSUE_SLICES * TILE_ELEMENTS > 64) begin
      $fatal(1, "NumberGroup native tile builder requires 16-lane 512-bit tiles");
    end
  end

  assign incoming_first = (s_global_index / TILE_ELEMENTS) * TILE_ELEMENTS;
  assign boundary = have_tile && s_valid && s_byte_index == 0
      && (incoming_first != tile_first || s_format != tile_format);
  assign s_ready = state == BUILD && !boundary
      && (s_format == PRISM_FORMAT_INT8 || s_format == PRISM_FORMAT_FP16
          || s_format == PRISM_FORMAT_BF16 || s_format == PRISM_FORMAT_FP32);
  assign m_valid = state == EMIT;
  assign m_element_bits = tile_bits;
  assign m_element_keep = {{(ISSUE_SLICES*TILE_ELEMENTS-TILE_ELEMENTS){1'b0}}, tile_keep};

  always_comb begin
    m_meta = base_meta_reg;
    m_meta.first_element = tile_first;
    m_meta.issue_group_first_element = tile_first;
    m_meta.input_format = prism_wire_format_e'(tile_format);
    m_meta.element_count = tile_count;
    // One emitted range fragment is one issue group, even when more fragments
    // of the same packet later fill other lanes of this arithmetic range.
    m_meta.last_tile = 1'b1;
  end

  always_comb begin
    case (s_format)
      PRISM_FORMAT_INT8: value_width = 3'd1;
      PRISM_FORMAT_FP16, PRISM_FORMAT_BF16: value_width = 3'd2;
      PRISM_FORMAT_FP32: value_width = 3'd4;
      default: value_width = '0;
    endcase
    lane = int'(s_global_index) % TILE_ELEMENTS;
    byte_slot = lane * int'(value_width) + int'(s_byte_index);
  end

  always_ff @(posedge clk) begin
    write_slot <= $bits(write_slot)'(byte_slot);
    write_byte <= s_value_byte;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= BUILD;
      have_tile <= 1'b0;
      tile_first <= '0;
      tile_format <= '0;
      tile_bits <= '0;
      tile_keep <= '0;
      tile_count <= '0;
      base_meta_reg <= '0;
      write_valid <= 1'b0;
    end else begin
      write_valid <= 1'b0;
      if (write_valid) tile_bits[int'(write_slot)*8 +: 8] <= write_byte;
      case (state)
        BUILD: begin
          if (boundary) begin
            state <= FLUSH;
          end else if (s_valid && s_ready) begin
            if (!have_tile) begin
              have_tile <= 1'b1;
              tile_first <= incoming_first;
              tile_format <= s_format;
              base_meta_reg <= s_base_meta;
            end
            write_valid <= byte_slot < DATA_W/8;
            if (s_element_last_byte) begin
              tile_keep[lane] <= 1'b1;
              tile_count <= tile_count + 8'd1;
            end
            if (s_packet_last_byte) begin
              state <= FLUSH;
            end
          end
        end
        // The last byte reaches the tile in this cycle.
        FLUSH: state <= EMIT;
        EMIT: begin
          if (m_ready) begin
            state <= BUILD;
            have_tile <= 1'b0;
            tile_bits <= '0;
            tile_keep <= '0;
            tile_count <= '0;
          end
        end
        default: state <= BUILD;
      endcase
    end
  end

endmodule
