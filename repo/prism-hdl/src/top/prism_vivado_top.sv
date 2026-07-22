//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_vivado_top.sv
// Module: prism_vivado_top
// Description: Flattens PRISM core interfaces for standalone Vivado synthesis.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_vivado_top #(
    parameter int unsigned NUM_PORTS = 2
) (
    // Clock, reset, and runtime configuration
    input  logic                         axis_aclk,
    input  logic                         axis_aresetn,
    input  logic                         millisecond_tick,
    input  logic [NUM_PORTS*48-1:0]      local_macs,
    input  logic                         laboratory_extension_enabled,

    // Flattened ingress AXI streams
    input  logic [NUM_PORTS*512-1:0]     s_axis_tdata,
    input  logic [NUM_PORTS*64-1:0]      s_axis_tkeep,
    input  logic [NUM_PORTS-1:0]         s_axis_tlast,
    input  logic [NUM_PORTS-1:0]         s_axis_tuser,
    input  logic [NUM_PORTS-1:0]         s_axis_tvalid,
    output logic [NUM_PORTS-1:0]         s_axis_tready,

    // Flattened egress AXI streams
    output logic [NUM_PORTS*512-1:0]     m_axis_tdata,
    output logic [NUM_PORTS*64-1:0]      m_axis_tkeep,
    output logic [NUM_PORTS-1:0]         m_axis_tlast,
    output logic [NUM_PORTS-1:0]         m_axis_tuser,
    output logic [NUM_PORTS-1:0]         m_axis_tvalid,
    output logic [NUM_PORTS*16-1:0]      m_axis_frame_bytes,
    input  logic [NUM_PORTS-1:0]         m_axis_tready
);

  // ---------------------------------------------------------------------------
  // Core-side unpacked AXI arrays
  // ---------------------------------------------------------------------------

  logic [511:0] core_s_data [0:NUM_PORTS-1];
  logic [63:0] core_s_keep [0:NUM_PORTS-1];
  logic [0:0] core_s_user [0:NUM_PORTS-1];
  logic [511:0] core_m_data [0:NUM_PORTS-1];
  logic [63:0] core_m_keep [0:NUM_PORTS-1];
  logic [0:0] core_m_user [0:NUM_PORTS-1];
  logic [15:0] core_frame_bytes [0:NUM_PORTS-1];

  // ---------------------------------------------------------------------------
  // Flattened external ports <-> reusable core arrays
  // ---------------------------------------------------------------------------

  for (genvar port = 0; port < NUM_PORTS; port++) begin : gen_flatten
    assign core_s_data[port] = s_axis_tdata[port*512 +: 512];
    assign core_s_keep[port] = s_axis_tkeep[port*64 +: 64];
    assign core_s_user[port] = s_axis_tuser[port];
    assign m_axis_tdata[port*512 +: 512] = core_m_data[port];
    assign m_axis_tkeep[port*64 +: 64] = core_m_keep[port];
    assign m_axis_tuser[port] = core_m_user[port];
    assign m_axis_frame_bytes[port*16 +: 16] = core_frame_bytes[port];
  end

  // ---------------------------------------------------------------------------
  // Reusable PRISM collective core
  // ---------------------------------------------------------------------------

  prism_collective_core #(
      .NUM_PORTS(NUM_PORTS)
  ) u_core (
      // Clock, reset, and runtime configuration
      .clk(axis_aclk),
      .rst_n(axis_aresetn),
      .millisecond_tick(millisecond_tick),
      .local_macs(local_macs),
      .laboratory_extension_enabled(laboratory_extension_enabled),

      // Ingress streams
      .s_axis_tdata(core_s_data),
      .s_axis_tkeep(core_s_keep),
      .s_axis_tlast(s_axis_tlast),
      .s_axis_tuser(core_s_user),
      .s_axis_tvalid(s_axis_tvalid),
      .s_axis_tready(s_axis_tready),

      // Egress streams
      .m_axis_tdata(core_m_data),
      .m_axis_tkeep(core_m_keep),
      .m_axis_tlast(m_axis_tlast),
      .m_axis_tuser(core_m_user),
      .m_axis_tvalid(m_axis_tvalid),
      .m_axis_frame_bytes(core_frame_bytes),
      .m_axis_tready(m_axis_tready)
  );

endmodule
