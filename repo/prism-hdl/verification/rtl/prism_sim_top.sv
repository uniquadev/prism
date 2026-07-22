//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_sim_top.sv
// Module: prism_sim_top
// Description: Exposes the complete PRISM core to Cocotb simulation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_sim_top (
    // Clock, reset, and runtime configuration
    input logic clk,
    input logic rst_n,
    input logic millisecond_tick,
    input logic laboratory_extension_enabled,
    input logic [47:0] local_mac_0,
    input logic [47:0] local_mac_1,

    // Ingress port 0
    input logic [511:0] s0_tdata,
    input logic [63:0] s0_tkeep,
    input logic s0_tlast,
    input logic s0_tuser,
    input logic s0_tvalid,
    output logic s0_tready,

    // Ingress port 1
    input logic [511:0] s1_tdata,
    input logic [63:0] s1_tkeep,
    input logic s1_tlast,
    input logic s1_tuser,
    input logic s1_tvalid,
    output logic s1_tready,

    // Egress port 0
    output logic [511:0] m0_tdata,
    output logic [63:0] m0_tkeep,
    output logic m0_tlast,
    output logic m0_tuser,
    output logic m0_tvalid,
    output logic [15:0] m0_frame_bytes,
    input logic m0_tready,

    // Egress port 1
    output logic [511:0] m1_tdata,
    output logic [63:0] m1_tkeep,
    output logic m1_tlast,
    output logic m1_tuser,
    output logic m1_tvalid,
    output logic [15:0] m1_frame_bytes,
    input logic m1_tready
);

  // ---------------------------------------------------------------------------
  // Cocotb scalar ports <-> reusable core arrays
  // ---------------------------------------------------------------------------

  logic [95:0] local_macs;
  logic [511:0] s_data [0:1];
  logic [63:0] s_keep [0:1];
  logic [1:0] s_last, s_valid, s_ready;
  logic [0:0] s_user [0:1];
  logic [511:0] m_data [0:1];
  logic [63:0] m_keep [0:1];
  logic [1:0] m_last, m_valid, m_ready;
  logic [0:0] m_user [0:1];
  logic [15:0] frame_bytes [0:1];

  assign local_macs = {local_mac_1, local_mac_0};
  assign s_data[0] = s0_tdata;
  assign s_data[1] = s1_tdata;
  assign s_keep[0] = s0_tkeep;
  assign s_keep[1] = s1_tkeep;
  assign s_last = {s1_tlast, s0_tlast};
  assign s_user[0] = s0_tuser;
  assign s_user[1] = s1_tuser;
  assign s_valid = {s1_tvalid, s0_tvalid};
  assign s0_tready = s_ready[0];
  assign s1_tready = s_ready[1];
  assign m0_tdata = m_data[0];
  assign m1_tdata = m_data[1];
  assign m0_tkeep = m_keep[0];
  assign m1_tkeep = m_keep[1];
  assign m0_tlast = m_last[0];
  assign m1_tlast = m_last[1];
  assign m0_tuser = m_user[0];
  assign m1_tuser = m_user[1];
  assign m0_tvalid = m_valid[0];
  assign m1_tvalid = m_valid[1];
  assign m0_frame_bytes = frame_bytes[0];
  assign m1_frame_bytes = frame_bytes[1];
  assign m_ready = {m1_tready, m0_tready};

  // ---------------------------------------------------------------------------
  // Device under test
  // ---------------------------------------------------------------------------

  prism_collective_core u_core (
      // Clock, reset, and runtime configuration
      .clk(clk),
      .rst_n(rst_n),
      .millisecond_tick(millisecond_tick),
      .local_macs(local_macs),
      .laboratory_extension_enabled(laboratory_extension_enabled),

      // Ingress streams
      .s_axis_tdata(s_data),
      .s_axis_tkeep(s_keep),
      .s_axis_tlast(s_last),
      .s_axis_tuser(s_user),
      .s_axis_tvalid(s_valid),
      .s_axis_tready(s_ready),

      // Egress streams
      .m_axis_tdata(m_data),
      .m_axis_tkeep(m_keep),
      .m_axis_tlast(m_last),
      .m_axis_tuser(m_user),
      .m_axis_tvalid(m_valid),
      .m_axis_frame_bytes(frame_bytes),
      .m_axis_tready(m_ready)
  );

endmodule
