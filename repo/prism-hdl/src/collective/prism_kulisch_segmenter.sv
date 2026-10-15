//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_segmenter.sv
// Module: prism_kulisch_segmenter
// Description: Reassembles validated Kulisch bytes into narrow signed segments.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_segmenter (
    input  logic          clk,
    input  logic          rst_n,
    input  logic [31:0]   s_global_index,
    input  logic [7:0]    s_format,
    input  logic [15:0]   s_byte_index,
    input  logic [7:0]    s_value_byte,
    input  logic          s_element_last_byte,
    input  logic          s_valid,
    output logic          s_ready,
    output logic [31:0]   m_global_index,
    output logic [7:0]    m_state_tag,
    output logic [15:0]   m_segment_index,
    output logic [31:0]   m_segment_data,
    output logic [3:0]    m_segment_keep,
    output logic          m_segment_last,
    output logic          m_valid,
    input  logic          m_ready
);

  import prism_pkg::*;

  typedef enum logic {COLLECT, OUTPUT_SEGMENT} state_t;
  state_t state;
  logic [31:0] global_index_reg;
  logic [7:0] state_tag_reg;
  logic [15:0] segment_index_reg;
  logic [31:0] segment_data_reg;
  logic [3:0] segment_keep_reg;
  logic segment_last_reg;
  logic [15:0] integer_byte_index;
  logic [1:0] octet_index;

  assign s_ready = state == COLLECT && s_format == PRISM_FORMAT_KULISCH;
  assign m_valid = state == OUTPUT_SEGMENT;
  assign m_global_index = global_index_reg;
  assign m_state_tag = state_tag_reg;
  assign m_segment_index = segment_index_reg;
  assign m_segment_data = segment_data_reg;
  assign m_segment_keep = segment_keep_reg;
  assign m_segment_last = segment_last_reg;
  assign integer_byte_index = s_byte_index - 16'd1;
  assign octet_index = integer_byte_index[1:0];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= COLLECT;
      global_index_reg <= '0;
      state_tag_reg <= '0;
      segment_index_reg <= '0;
      segment_data_reg <= '0;
      segment_keep_reg <= '0;
      segment_last_reg <= 1'b0;
    end else begin
      case (state)
        COLLECT: begin
          if (s_valid && s_ready) begin
            if (s_byte_index == 0) begin
              global_index_reg <= s_global_index;
              state_tag_reg <= s_value_byte;
            end else begin
              segment_index_reg <= integer_byte_index >> 2;
              segment_data_reg[octet_index*8 +: 8] <= s_value_byte;
              segment_keep_reg[octet_index] <= 1'b1;
              if (octet_index == 2'd3 || s_element_last_byte) begin
                segment_last_reg <= s_element_last_byte;
                state <= OUTPUT_SEGMENT;
              end
            end
          end
        end
        OUTPUT_SEGMENT: begin
          if (m_ready) begin
            segment_data_reg <= '0;
            segment_keep_reg <= '0;
            segment_last_reg <= 1'b0;
            state <= COLLECT;
          end
        end
        default: state <= COLLECT;
      endcase
    end
  end

endmodule
