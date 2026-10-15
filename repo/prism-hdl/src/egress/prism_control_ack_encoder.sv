//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_ack_encoder.sv
// Module: prism_control_ack_encoder
// Description: One-beat protocol 2.0 CONTROL ACK with Ethernet padding.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_ack_encoder (
    input  logic                              clk,
    input  logic                              rst_n,
    input  prism_pkg::prism_operation_key_t   s_operation,
    input  logic [31:0]                       s_transaction_id,
    input  logic [15:0]                       s_source_endpoint,
    input  logic [15:0]                       s_destination_endpoint,
    input  logic [47:0]                       s_source_mac,
    input  logic [47:0]                       s_destination_mac,
    input  logic [7:0]                        s_status,
    input  logic                              s_valid,
    output logic                              s_ready,
    output logic [511:0]                      m_axis_tdata,
    output logic [63:0]                       m_axis_tkeep,
    output logic                              m_axis_tlast,
    output logic                              m_axis_tuser,
    output logic [15:0]                       m_frame_bytes,
    output logic                              m_axis_tvalid,
    input  logic                              m_axis_tready
);

  logic [511:0] next_frame, frame_reg;
  logic full;

  always_comb begin
    next_frame = '0;
    for (integer index = 0; index < 6; index++) begin
      next_frame[index*8 +: 8] = s_destination_mac[(5-index)*8 +: 8];
      next_frame[(6+index)*8 +: 8] = s_source_mac[(5-index)*8 +: 8];
    end
    next_frame[12*8 +: 8] = 8'h88;
    next_frame[13*8 +: 8] = 8'hb5;
    next_frame[14*8 +: 8] = 8'h20;
    next_frame[15*8 +: 8] = 8'h01;
    for (integer index = 0; index < 8; index++)
      next_frame[(16+index)*8 +: 8] = s_operation.job_id[(7-index)*8 +: 8];
    next_frame[24*8 +: 8] = s_operation.group_id[15:8];
    next_frame[25*8 +: 8] = s_operation.group_id[7:0];
    next_frame[26*8 +: 8] = s_operation.group_generation[15:8];
    next_frame[27*8 +: 8] = s_operation.group_generation[7:0];
    next_frame[28*8 +: 8] = s_operation.operation_id[15:8];
    next_frame[29*8 +: 8] = s_operation.operation_id[7:0];
    for (integer index = 0; index < 4; index++) begin
      next_frame[(30+index)*8 +: 8] =
          s_operation.operation_generation[(3-index)*8 +: 8];
      next_frame[(34+index)*8 +: 8] = s_transaction_id[(3-index)*8 +: 8];
    end
    next_frame[38*8 +: 8] = s_source_endpoint[15:8];
    next_frame[39*8 +: 8] = s_source_endpoint[7:0];
    next_frame[40*8 +: 8] = s_destination_endpoint[15:8];
    next_frame[41*8 +: 8] = s_destination_endpoint[7:0];
    next_frame[42*8 +: 8] = 8'h05;
    next_frame[43*8 +: 8] = s_status;
    next_frame[47*8 +: 8] = 8'h01;
  end

  assign s_ready = !full || m_axis_tready;
  assign m_axis_tdata = frame_reg;
  assign m_axis_tkeep = 64'h0fff_ffff_ffff_ffff;
  assign m_axis_tlast = 1'b1;
  assign m_axis_tuser = 1'b0;
  assign m_frame_bytes = 16'd60;
  assign m_axis_tvalid = full;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      frame_reg <= '0;
      full <= 1'b0;
    end else if (s_valid && s_ready) begin
      frame_reg <= next_frame;
      full <= 1'b1;
    end else if (full && m_axis_tready) full <= 1'b0;
  end

endmodule
