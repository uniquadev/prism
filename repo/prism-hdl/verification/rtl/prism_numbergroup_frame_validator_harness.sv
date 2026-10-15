//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_frame_validator_harness.sv
// Module: prism_numbergroup_frame_validator_harness
// Description: Complete NumberGroup frame admission probe.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_frame_validator_harness (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [511:0] s_axis_tdata,
    input  logic [63:0]  s_axis_tkeep,
    input  logic         s_axis_tlast,
    input  logic         s_axis_tuser,
    input  logic         s_axis_tvalid,
    output logic         s_axis_tready,
    input  logic [15:0]  s_mtu,
    input  logic [15:0]  s_kulisch_bits,
    output logic [15:0]  m_frame_bytes,
    output logic [4:0]   m_format_mask,
    output logic         m_accept,
    output logic [2:0]   m_error_code,
    output logic         m_valid,
    input  logic         m_ready,
    input  logic [15:0]  m_read_address,
    output logic [7:0]   m_read_data,
    output logic [31:0]  m_first_element,
    output logic [15:0]  m_element_count,
    output logic [7:0]   m_group_count,
    output logic [15:0]  m_body_bytes,
    output logic [31:0]  m_packet_id,
    output logic [7:0]   m_packet_class,
    output logic [7:0]   m_flags
);

  prism_pkg::prism_numbergroup_header_t header;
  logic unused_header_bits;
  assign unused_header_bits = ^header;

  prism_numbergroup_frame_validator #(
      .MAX_MTU(1500),
      .PORT_INDEX(7)
  ) u_validator (
      .clk(clk),
      .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata),
      .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast),
      .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid),
      .s_axis_tready(s_axis_tready),
      .s_mtu(s_mtu),
      .s_kulisch_bits(s_kulisch_bits),
      .m_header(header),
      .m_frame_bytes(m_frame_bytes),
      .m_format_mask(m_format_mask),
      .m_accept(m_accept),
      .m_error_code(m_error_code),
      .m_valid(m_valid),
      .m_ready(m_ready),
      .m_read_address(m_read_address),
      .m_read_data(m_read_data),
      .m_read_word_address(16'd0), .m_read_word_data(),
      .m_read_next_word_data(),
      .m_copy_word_address(16'd0), .m_copy_word_data()
  );

  assign m_first_element = header.first_element;
  assign m_element_count = header.element_count;
  assign m_group_count = header.group_count;
  assign m_body_bytes = header.body_bytes;
  assign m_packet_id = header.packet_id;
  assign m_packet_class = header.packet_class;
  assign m_flags = header.flags;

endmodule
