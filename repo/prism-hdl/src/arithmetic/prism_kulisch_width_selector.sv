//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_width_selector.sv
// Module: prism_kulisch_width_selector
// Description: Chooses the smallest compiled Kulisch width that covers an operation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_width_selector #(
    parameter int unsigned WIDTH_COUNT = 3,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320
) (
    input  logic                               clk,
    input  logic                               rst_n,
    input  prism_pkg::prism_wire_format_e      s_input_format,
    input  logic [31:0]                        s_maximum_terms,
    input  logic                               s_valid,
    output logic                               s_ready,
    output logic [15:0]                        m_required_width,
    output logic [15:0]                        m_selected_width,
    output logic [1:0]                         m_width_index,
    output logic                               m_sufficient,
    output logic                               m_accumulation_inexact,
    output logic                               m_valid,
    input  logic                               m_ready
);

  import prism_pkg::*;

  logic [15:0] required_width_comb;
  logic [15:0] selected_width_comb;
  logic [1:0] selected_index_comb;
  logic sufficient_comb;
  int unsigned widths [0:2];
  int unsigned largest_width;
  logic [1:0] largest_index;

  assign s_ready = !m_valid || m_ready;

  initial begin
    if ((WIDTH_COUNT == 0) || (WIDTH_COUNT > 3)) begin
      $fatal(1, "prism_kulisch_width_selector WIDTH_COUNT must be in 1..3");
    end
    if ((WIDTH_0 == 0) || ((WIDTH_COUNT > 1) && (WIDTH_1 == 0))
        || ((WIDTH_COUNT > 2) && (WIDTH_2 == 0))) begin
      $fatal(1, "compiled Kulisch widths must be positive");
    end
    if (((WIDTH_COUNT > 1) && (WIDTH_0 == WIDTH_1))
        || ((WIDTH_COUNT > 2) && ((WIDTH_0 == WIDTH_2) || (WIDTH_1 == WIDTH_2)))) begin
      $fatal(1, "compiled Kulisch widths must be unique");
    end
  end

  always_comb begin
    widths[0] = WIDTH_0;
    widths[1] = WIDTH_1;
    widths[2] = WIDTH_2;
    required_width_comb = 16'(prism_required_kulisch_width(s_input_format, s_maximum_terms));
    largest_width = widths[0];
    largest_index = 0;
    selected_width_comb = 16'(widths[0]);
    selected_index_comb = 2'd0;
    sufficient_comb = 1'b0;

    for (int unsigned index = 0; index < WIDTH_COUNT; index++) begin
      if (widths[index] > largest_width) begin
        largest_width = widths[index];
        largest_index = 2'(index);
      end
      if ((widths[index] >= required_width_comb)
          && (!sufficient_comb || (widths[index] < selected_width_comb))) begin
        selected_width_comb = 16'(widths[index]);
        selected_index_comb = 2'(index);
        sufficient_comb = 1'b1;
      end
    end
    if (!sufficient_comb) begin
      selected_width_comb = 16'(largest_width);
      selected_index_comb = largest_index;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_required_width <= '0;
      m_selected_width <= '0;
      m_width_index <= '0;
      m_sufficient <= 1'b0;
      m_accumulation_inexact <= 1'b0;
      m_valid <= 1'b0;
    end else if (s_ready) begin
      m_valid <= s_valid;
      if (s_valid) begin
        m_required_width <= required_width_comb;
        m_selected_width <= selected_width_comb;
        m_width_index <= selected_index_comb;
        m_sufficient <= sufficient_comb;
        m_accumulation_inexact <= !sufficient_comb;
      end
    end
  end

endmodule
