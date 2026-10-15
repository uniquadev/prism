//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_native_tile_reader.sv
// Module: prism_numbergroup_native_tile_reader
// Description: One validated uniform native NumberGroup into 512-bit native tiles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_native_tile_reader (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [31:0]  s_first_element,
    input  logic [15:0]  s_element_count,
    input  logic [7:0]   s_format,
    input  logic         s_start_valid,
    output logic         s_start_ready,
    output logic [15:0]  m_read_word_address,
    input  logic [511:0] s_read_word,
    input  logic [511:0] s_read_next_word,
    output logic [31:0]  m_tile_first_element,
    output logic [7:0]   m_tile_count,
    output logic [511:0] m_tile_bits,
    output logic [63:0]  m_tile_keep,
    output logic         m_tile_valid,
    input  logic         m_tile_ready,
    output logic         m_done_valid,
    input  logic         m_done_ready
);

  typedef enum logic [1:0] {IDLE, RUN, DONE} state_t;
  state_t state;
  logic [7:0] format_reg;
  logic [2:0] value_bytes;
  logic [31:0] first_reg;
  logic [15:0] count_reg, index_reg;
  logic [511:0] word_reg, next_word_reg;
  logic [511:0] aligned_values, positioned_values;
  logic [15:0] remaining;
  logic [6:0] tile_capacity;
  logic [5:0] lane_start;
  logic [15:0] next_index;
  logic [31:0] tile_base_byte, next_tile_base_byte;

  assign s_start_ready = state == IDLE;
  assign m_read_word_address = state == RUN
      ? 16'(next_tile_base_byte >> 6) : 16'd0;
  assign value_bytes = format_reg == 8'h01 ? 3'd1
      : format_reg == 8'h02 || format_reg == 8'h03 ? 3'd2 : 3'd4;
  assign tile_capacity = format_reg == 8'h01 ? 7'd64
      : format_reg == 8'h02 || format_reg == 8'h03 ? 7'd32 : 7'd16;
  assign lane_start = format_reg == 8'h01
      ? 6'(first_reg + 32'(index_reg))
      : format_reg == 8'h02 || format_reg == 8'h03
          ? {1'b0, 5'(first_reg + 32'(index_reg))}
          : {2'b00, 4'(first_reg + 32'(index_reg))};
  assign m_tile_first_element = first_reg + 32'(index_reg) - 32'(lane_start);
  assign remaining = count_reg - index_reg;
  assign m_tile_count = remaining >= (16'(tile_capacity) - 16'(lane_start))
      ? 8'(tile_capacity - {1'b0, lane_start}) : 8'(remaining);
  assign m_tile_keep = ((64'h1 << m_tile_count) - 64'd1) << lane_start;
  assign tile_base_byte = 32'd60 + 32'(index_reg) * 32'(value_bytes);
  assign next_index = index_reg + 16'(m_tile_count);
  assign next_tile_base_byte = 32'd60 + 32'(next_index) * 32'(value_bytes);
  assign aligned_values = 512'({next_word_reg, word_reg}
      >> (tile_base_byte[5:0] * 8));
  assign m_tile_valid = state == RUN;
  assign m_done_valid = state == DONE;

  assign positioned_values = 512'(aligned_values
      << (32'(lane_start) * 32'(value_bytes) * 8));
  always_comb begin
    m_tile_bits = '0;
    case (format_reg)
      8'h01: for (integer lane = 0; lane < 64; lane++)
        if (m_tile_keep[lane])
          m_tile_bits[lane*8 +: 8] = positioned_values[lane*8 +: 8];
      8'h02, 8'h03: for (integer lane = 0; lane < 32; lane++)
        if (m_tile_keep[lane])
          m_tile_bits[lane*16 +: 16] = positioned_values[lane*16 +: 16];
      default: for (integer lane = 0; lane < 16; lane++)
        if (m_tile_keep[lane])
          m_tile_bits[lane*32 +: 32] = positioned_values[lane*32 +: 32];
    endcase
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE;
      format_reg <= '0;
      first_reg <= '0;
      count_reg <= '0;
      index_reg <= '0;
      word_reg <= '0;
      next_word_reg <= '0;
    end else begin
      case (state)
        IDLE: begin
          if (s_start_valid) begin
            first_reg <= s_first_element;
            format_reg <= s_format;
            count_reg <= s_element_count;
            index_reg <= '0;
            word_reg <= s_read_word;
            next_word_reg <= s_read_next_word;
            state <= s_element_count == 0 ? DONE : RUN;
          end
        end
        RUN: begin
          if (m_tile_ready) begin
            if (next_index == count_reg) state <= DONE;
            else begin
              index_reg <= next_index;
              word_reg <= s_read_word;
              next_word_reg <= s_read_next_word;
            end
          end
        end
        DONE: begin
          if (m_done_ready) state <= IDLE;
        end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
