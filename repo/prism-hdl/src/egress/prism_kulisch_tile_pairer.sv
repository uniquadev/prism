//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_tile_pairer.sv
// Module: prism_kulisch_tile_pairer
// Description: Exact sixteen-lane tiles into consecutive Kulisch value pairs.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_tile_pairer #(
    parameter int unsigned KULISCH_W = 320
) (
    input  logic                           clk,
    input  logic                           rst_n,
    input  logic                           s_clear,
    input  logic [31:0]                    s_first_element,
    input  logic [4:0]                     s_count,
    input  logic [127:0]                   s_tags,
    input  logic [16*KULISCH_W-1:0]        s_integers,
    input  logic                           s_valid,
    output logic                           s_ready,
    output logic [31:0]                    m_first_element,
    output logic [1:0]                     m_count,
    output logic [15:0]                    m_tags,
    output logic [2*KULISCH_W-1:0]         m_integers,
    output logic                           m_valid,
    input  logic                           m_ready,
    output logic                           m_fault
);

  logic [15:0] pair_tags [0:7];
  logic [2*KULISCH_W-1:0] pair_integers [0:7];
  logic [31:0] first_reg;
  logic [4:0] count_reg;
  logic [2:0] pair_index;
  logic busy, last_pair;
  logic [32:0] incoming_end;

  assign incoming_end = {1'b0, s_first_element} + 33'(s_count);
  assign last_pair = {1'b0, pair_index} + 4'd1 >= (({1'b0, count_reg} + 6'd1) >> 1);
  assign s_ready = !s_clear && !m_fault
      && (!busy || (m_ready && last_pair));
  assign m_valid = busy;
  assign m_first_element = first_reg + 32'({pair_index, 1'b0});
  assign m_count = count_reg - {pair_index, 1'b0} >= 5'd2 ? 2'd2 : 2'd1;
  assign m_tags = pair_tags[pair_index];
  assign m_integers = pair_integers[pair_index];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      first_reg <= '0;
      count_reg <= '0;
      pair_index <= '0;
      busy <= 1'b0;
      m_fault <= 1'b0;
    end else begin
      if (s_clear && !busy) begin
        pair_index <= '0;
        m_fault <= 1'b0;
      end else if (s_valid && s_ready) begin
        if (s_count == 0 || s_count > 5'd16
            || incoming_end > 33'h1_0000_0000) begin
          busy <= 1'b0;
          m_fault <= 1'b1;
        end else begin
          first_reg <= s_first_element;
          count_reg <= s_count;
          pair_index <= '0;
          busy <= 1'b1;
          for (integer pair = 0; pair < 8; pair++) begin
            pair_tags[pair] <= s_tags[pair*16 +: 16];
            pair_integers[pair]
                <= s_integers[pair*2*KULISCH_W +: 2*KULISCH_W];
          end
        end
      end else if (m_valid && m_ready) begin
        if (last_pair) busy <= 1'b0;
        else pair_index <= pair_index + 3'd1;
      end
    end
  end

endmodule
