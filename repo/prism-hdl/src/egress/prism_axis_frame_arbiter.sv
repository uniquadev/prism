//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_axis_frame_arbiter.sv
// Module: prism_axis_frame_arbiter
// Description: Arbitrates whole CONTROL and RES frames without beat interleaving.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_axis_frame_arbiter #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  logic [DATA_W-1:0]                     s0_axis_tdata,
    input  logic [DATA_W/8-1:0]                   s0_axis_tkeep,
    input  logic                                  s0_axis_tlast,
    input  logic [USER_W-1:0]                     s0_axis_tuser,
    input  logic                                  s0_axis_tvalid,
    output logic                                  s0_axis_tready,
    input  logic [DATA_W-1:0]                     s1_axis_tdata,
    input  logic [DATA_W/8-1:0]                   s1_axis_tkeep,
    input  logic                                  s1_axis_tlast,
    input  logic [USER_W-1:0]                     s1_axis_tuser,
    input  logic                                  s1_axis_tvalid,
    output logic                                  s1_axis_tready,
    output logic [DATA_W-1:0]                     m_axis_tdata,
    output logic [DATA_W/8-1:0]                   m_axis_tkeep,
    output logic                                  m_axis_tlast,
    output logic [USER_W-1:0]                     m_axis_tuser,
    output logic                                  m_axis_tvalid,
    input  logic                                  m_axis_tready
);

  logic locked;
  logic selected;
  logic round_robin;
  logic candidate;

  always_comb begin
    if (locked) candidate = selected;
    else if (s0_axis_tvalid && s1_axis_tvalid) candidate = round_robin;
    else candidate = s1_axis_tvalid;

    s0_axis_tready = !candidate && m_axis_tready;
    s1_axis_tready = candidate && m_axis_tready;
    if (candidate) begin
      m_axis_tdata = s1_axis_tdata;
      m_axis_tkeep = s1_axis_tkeep;
      m_axis_tlast = s1_axis_tlast;
      m_axis_tuser = s1_axis_tuser;
      m_axis_tvalid = s1_axis_tvalid;
    end else begin
      m_axis_tdata = s0_axis_tdata;
      m_axis_tkeep = s0_axis_tkeep;
      m_axis_tlast = s0_axis_tlast;
      m_axis_tuser = s0_axis_tuser;
      m_axis_tvalid = s0_axis_tvalid;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      locked <= 1'b0;
      selected <= 1'b0;
      round_robin <= 1'b0;
    end else if (m_axis_tvalid && m_axis_tready) begin
      if (!locked && !m_axis_tlast) begin
        locked <= 1'b1;
        selected <= candidate;
      end
      if (m_axis_tlast) begin
        locked <= 1'b0;
        round_robin <= ~candidate;
      end
    end
  end

endmodule
