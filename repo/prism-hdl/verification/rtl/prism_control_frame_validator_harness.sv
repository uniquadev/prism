//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_frame_validator_harness.sv
// Module: prism_control_frame_validator_harness
// Description: Protocol 2.0 CONTROL frame validator port adapter for Cocotb.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_frame_validator_harness (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [511:0] s_axis_tdata,
    input  logic [63:0]  s_axis_tkeep,
    input  logic         s_axis_tlast,
    input  logic         s_axis_tuser,
    input  logic         s_axis_tvalid,
    output logic         s_axis_tready,
    input  logic [15:0]  s_mtu,
    output logic [31:0]  m_transaction_id,
    output logic [7:0]   m_command,
    output logic [15:0]  m_body_bytes,
    output logic [15:0]  m_frame_bytes,
    output logic         m_accept,
    output logic [2:0]   m_error_code,
    output logic         m_valid,
    input  logic         m_ready,
    input  logic [15:0]  m_read_address,
    output logic [7:0]   m_read_data
);

  prism_pkg::prism_control_frame_header_t header;

  prism_control_frame_validator u_validator (
      .clk(clk), .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast), .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
      .s_mtu(s_mtu), .m_header(header), .m_frame_bytes(m_frame_bytes),
      .m_accept(m_accept), .m_error_code(m_error_code),
      .m_valid(m_valid), .m_ready(m_ready),
      .m_read_address(m_read_address), .m_read_data(m_read_data)
  );

  assign m_transaction_id = header.transaction_id;
  assign m_command = header.command;
  assign m_body_bytes = header.body_bytes;

endmodule
