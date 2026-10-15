//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_tile_serializer16.sv
// Module: prism_kulisch_tile_serializer16
// Description: Converts a sixteen-lane exact result tile into two-lane wire tiles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_tile_serializer16 #(
    parameter int unsigned KULISCH_W = 320
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         s_clear,
    input  logic [31:0]                  s_first_element,
    input  logic [15:0]                  s_keep,
    input  logic [127:0]                 s_tags,
    input  logic [16*KULISCH_W-1:0]      s_integers,
    input  logic                         s_valid,
    output logic                         s_ready,
    output logic [31:0]                  m_first_element,
    output logic [1:0]                   m_count,
    output logic [15:0]                  m_tags,
    output logic [2*KULISCH_W-1:0]       m_integers,
    output logic                         m_valid,
    input  logic                         m_ready,
    output logic                         m_fault
);

  logic [31:0] first_reg;
  logic [127:0] tags_reg;
  logic [16*KULISCH_W-1:0] integers_reg;
  logic [4:0] total, cursor;
  logic busy;
  logic [4:0] next_cursor;

  assign s_ready = !busy && !m_fault && !s_clear;
  assign m_valid = busy;
  assign m_first_element = first_reg + 32'(cursor);
  assign m_count = total - cursor >= 5'd2 ? 2'd2 : 2'd1;
  assign m_tags[7:0] = tags_reg[cursor*8 +: 8];
  assign m_tags[15:8] = m_count == 2
      ? tags_reg[(cursor+5'd1)*8 +: 8] : '0;
  assign m_integers[0 +: KULISCH_W]
      = integers_reg[cursor*KULISCH_W +: KULISCH_W];
  assign m_integers[KULISCH_W +: KULISCH_W] = m_count == 2
      ? integers_reg[(int'(cursor)+1)*KULISCH_W +: KULISCH_W] : '0;
  assign next_cursor = cursor + {3'd0, m_count};

  initial begin
    if (KULISCH_W < 278 || KULISCH_W > 4096)
      $fatal(1, "Kulisch tile width is outside the supported protocol range");
  end

  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      first_reg <= '0;
      tags_reg <= '0;
      integers_reg <= '0;
      total <= '0;
      cursor <= '0;
      busy <= 1'b0;
      m_fault <= 1'b0;
    end else begin
      if (s_valid && s_ready) begin
        if (s_keep == 0 || s_keep != (16'hffff >> (16 - $countones(s_keep))))
          m_fault <= 1'b1;
        else begin
          first_reg <= s_first_element;
          tags_reg <= s_tags;
          integers_reg <= s_integers;
          total <= 5'($countones(s_keep));
          cursor <= '0;
          busy <= 1'b1;
        end
      end
      if (m_valid && m_ready) begin
        cursor <= next_cursor;
        if (next_cursor == total) busy <= 1'b0;
      end
    end
  end

endmodule
