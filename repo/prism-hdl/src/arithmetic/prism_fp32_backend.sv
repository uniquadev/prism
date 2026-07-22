//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_backend.sv
// Module: prism_fp32_backend
// Description: Applies one binary32 adder per active arithmetic lane.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_backend #(
    parameter int unsigned LANES = 16,
    parameter int unsigned TAG_W = 16
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic [LANES*32-1:0]     s_left,
    input  logic [LANES*32-1:0]     s_right,
    input  logic [LANES-1:0]        s_lane_keep,
    input  logic [TAG_W-1:0]        s_tag,
    input  logic                    s_valid,
    output logic                    s_ready,
    output logic [LANES*32-1:0]     m_result,
    output logic [LANES-1:0]        m_lane_keep,
    output logic [LANES*5-1:0]      m_exceptions,
    output logic [TAG_W-1:0]        m_tag,
    output logic                    m_valid,
    input  logic                    m_ready
);

  logic [LANES-1:0] lane_ready;
  logic [LANES-1:0] lane_valid;
  logic request_ready;

  assign request_ready = &lane_ready;
  assign s_ready = request_ready;
  assign m_valid = &lane_valid;

  initial begin
    if ((LANES == 0) || (TAG_W == 0)) begin
      $fatal(1, "prism_fp32_backend parameters must be positive");
    end
  end

  for (genvar lane = 0; lane < LANES; lane++) begin : g_adders
    prism_fp32_add u_fp32_add (
        .clk          (clk),
        .rst_n        (rst_n),
        .s_left       (s_left[lane*32 +: 32]),
        .s_right      (s_right[lane*32 +: 32]),
        .s_valid      (s_valid && request_ready),
        .s_ready      (lane_ready[lane]),
        .m_result     (m_result[lane*32 +: 32]),
        .m_exceptions (m_exceptions[lane*5 +: 5]),
        .m_valid      (lane_valid[lane]),
        .m_ready      (m_ready)
    );
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_lane_keep <= '0;
      m_tag <= '0;
    end else if (s_valid && s_ready) begin
      m_lane_keep <= s_lane_keep;
      m_tag <= s_tag;
    end
  end

endmodule
