//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_reader_harness.sv
// Module: prism_numbergroup_reader_harness
// Description: Complete-frame admission and ordered NumberGroup value probe.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_reader_harness (
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
    output logic         m_frame_valid,
    output logic         m_frame_accept,
    output logic [2:0]   m_frame_error,
    output logic [31:0]  m_global_index,
    output logic [7:0]   m_format,
    output logic [7:0]   m_group_index,
    output logic [15:0]  m_value_bytes,
    output logic [15:0]  m_byte_index,
    output logic [7:0]   m_value_byte,
    output logic         m_element_last_byte,
    output logic         m_group_last_byte,
    output logic         m_packet_last_byte,
    output logic         m_value_valid,
    input  logic         m_value_ready,
    output logic         m_done_valid
);

  prism_pkg::prism_numbergroup_header_t header;
  logic [15:0] frame_bytes;
  logic [4:0] format_mask;
  logic [15:0] read_address;
  logic [7:0] read_data;
  logic reader_ready;
  logic unused_reader_ready;
  logic unused_frame_bytes;
  assign unused_reader_ready = reader_ready;
  assign unused_frame_bytes = ^{frame_bytes, format_mask};

  prism_numbergroup_frame_validator #(
      .MAX_MTU(1500)
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
      .m_frame_bytes(frame_bytes),
      .m_format_mask(format_mask),
      .m_accept(m_frame_accept),
      .m_error_code(m_frame_error),
      .m_valid(m_frame_valid),
      .m_ready(m_frame_valid && (!m_frame_accept || m_done_valid)),
      .m_read_address(read_address),
      .m_read_data(read_data),
      .m_read_word_address(16'd0), .m_read_word_data(),
      .m_read_next_word_data(),
      .m_copy_word_address(16'd0), .m_copy_word_data()
  );

  prism_numbergroup_value_reader u_reader (
      .clk(clk),
      .rst_n(rst_n),
      .s_header(header),
      .s_kulisch_bits(s_kulisch_bits),
      .s_valid(m_frame_valid && m_frame_accept),
      .s_ready(reader_ready),
      .read_address(read_address),
      .read_data(read_data),
      .m_global_index(m_global_index),
      .m_format(m_format),
      .m_group_index(m_group_index),
      .m_value_bytes(m_value_bytes),
      .m_byte_index(m_byte_index),
      .m_value_byte(m_value_byte),
      .m_element_last_byte(m_element_last_byte),
      .m_group_last_byte(m_group_last_byte),
      .m_packet_last_byte(m_packet_last_byte),
      .m_valid(m_value_valid),
      .m_ready(m_value_ready),
      .m_done_valid(m_done_valid),
      .m_done_ready(1'b1)
  );

endmodule
