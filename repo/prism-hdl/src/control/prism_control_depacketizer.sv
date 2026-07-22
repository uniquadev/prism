//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_depacketizer.sv
// Module: prism_control_depacketizer
// Description: Extracts CONTROL payload bytes from framed AXI packets.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_depacketizer #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_frame_desc_t          s_packet,
    input  logic                                  s_packet_valid,
    output logic                                  s_packet_ready,
    input  logic [DATA_W-1:0]                     s_axis_tdata,
    input  logic [DATA_W/8-1:0]                   s_axis_tkeep,
    input  logic                                  s_axis_tlast,
    input  logic [USER_W-1:0]                     s_axis_tuser,
    input  logic                                  s_axis_tvalid,
    output logic                                  s_axis_tready,
    output prism_pkg::prism_control_header_t      m_header,
    output logic [15:0]                           m_payload_length,
    output logic                                  m_start_valid,
    input  logic                                  m_start_ready,
    output logic [7:0]                            m_byte,
    output logic                                  m_byte_last,
    output logic                                  m_byte_valid,
    input  logic                                  m_byte_ready
);

  import prism_pkg::*;

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned BYTE_INDEX_W = prism_clog2_safe(KEEP_W);
  localparam int unsigned PREFIX_BYTES = PRISM_ETH_HEADER_BYTES
      + PRISM_CONTROL_WORD_BYTES + PRISM_CONTROL_HEADER_BYTES;

  logic active;
  logic [BYTE_INDEX_W-1:0] byte_index;
  logic [15:0] payload_remaining;
  logic [15:0] valid_bytes;
  logic final_byte_in_beat;
  // Frame integrity was consumed by the validator before this typed boundary.
  logic unused_validated_frame_fields;
  assign unused_validated_frame_fields = ^s_packet;

  initial begin
    if ((DATA_W != 512) || (PREFIX_BYTES >= KEEP_W)) begin
      $fatal(1, "prism_control_depacketizer requires the 512-bit framing profile");
    end
  end

  assign valid_bytes = 16'($countones(s_axis_tkeep));
  assign s_packet_ready = !active && m_start_ready;
  assign m_header = s_packet.header.control;
  assign m_payload_length = s_packet.frame_bytes - 16'(PREFIX_BYTES);
  assign m_start_valid = !active && s_packet_valid;

  assign m_byte = s_axis_tdata[byte_index*8 +: 8];
  assign m_byte_valid = active && (payload_remaining != 0) && s_axis_tvalid;
  assign m_byte_last = m_byte_valid && (payload_remaining == 1);
  assign final_byte_in_beat = 16'(byte_index) + 16'd1 == valid_bytes;
  assign s_axis_tready = active && ((payload_remaining == 0)
      || (m_byte_ready && m_byte_valid && final_byte_in_beat));

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      active <= 1'b0;
      byte_index <= BYTE_INDEX_W'(PREFIX_BYTES);
      payload_remaining <= '0;
    end else begin
      if (s_packet_valid && s_packet_ready) begin
        active <= 1'b1;
        byte_index <= BYTE_INDEX_W'(PREFIX_BYTES);
        payload_remaining <= s_packet.frame_bytes - 16'(PREFIX_BYTES);
      end

      if (m_byte_valid && m_byte_ready) begin
        payload_remaining <= payload_remaining - 1'b1;
        if (!final_byte_in_beat) begin
          byte_index <= byte_index + 1'b1;
        end
      end

      if (s_axis_tvalid && s_axis_tready) begin
        byte_index <= '0;
        if (s_axis_tlast) begin
          active <= 1'b0;
          payload_remaining <= '0;
        end
      end
    end
  end

  logic unused_user;
  assign unused_user = ^s_axis_tuser;

endmodule
