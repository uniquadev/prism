//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_reduced_tile_arbiter.sv
// Module: prism_reduced_tile_arbiter
// Description: Merges banked reduced-tile streams while preserving warning metadata.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_reduced_tile_arbiter #(
    parameter int unsigned INPUTS = 2,
    parameter int unsigned LANES = 16
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_tile_meta_t               s_meta [0:INPUTS-1],
    input  logic [LANES*32-1:0]                       s_fp32_bits [0:INPUTS-1],
    input  logic [LANES-1:0]                          s_element_keep [0:INPUTS-1],
    input  logic [INPUTS-1:0]                         s_warning,
    input  logic [INPUTS-1:0]                         s_valid,
    output logic [INPUTS-1:0]                         s_ready,
    output prism_pkg::prism_tile_meta_t               m_meta,
    output logic [LANES*32-1:0]                       m_fp32_bits,
    output logic [LANES-1:0]                          m_element_keep,
    output logic                                      m_warning,
    output logic                                      m_valid,
    input  logic                                      m_ready
);

  import prism_pkg::*;

  localparam int unsigned INPUT_W = prism_clog2_safe(INPUTS);
  logic [INPUT_W-1:0] round_robin;
  logic candidate_found;
  logic [INPUT_W-1:0] candidate;

  initial begin
    if ((INPUTS < 1) || (LANES < 1)) begin
      $fatal(1, "prism_reduced_tile_arbiter parameters must be positive");
    end
  end

  always_comb begin
    candidate_found = 1'b0;
    candidate = round_robin;
    for (int unsigned offset = 0; offset < INPUTS; offset++) begin
      if (s_valid[(32'(round_robin) + offset) % INPUTS] && !candidate_found) begin
        candidate_found = 1'b1;
        candidate = INPUT_W'((32'(round_robin) + offset) % INPUTS);
      end
    end
    s_ready = '0;
    if (candidate_found) s_ready[candidate] = m_ready;
    m_meta = s_meta[candidate];
    m_fp32_bits = s_fp32_bits[candidate];
    m_element_keep = s_element_keep[candidate];
    m_warning = s_warning[candidate];
    m_valid = candidate_found;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      round_robin <= '0;
    end else if (m_valid && m_ready) begin
      round_robin <= (candidate == INPUT_W'(INPUTS - 1)) ? '0 : candidate + 1'b1;
    end
  end

endmodule
