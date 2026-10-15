//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_native_partial_tile_harness.sv
// Module: prism_native_partial_tile_harness
// Description: Native-width partial tiles into NumberGroup DATA frames.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_native_partial_tile_harness #(
    parameter int unsigned FORMAT = int'(prism_pkg::PRISM_FORMAT_FP32)
) (
    input  logic                                 clk,
    input  logic                                 rst_n,
    input  logic                                 s_reset,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                          s_total_elements,
    input  logic [15:0]                          s_mtu,
    input  logic [31:0]                          s_tile_first_element,
    input  logic [6:0]                           s_tile_count,
    input  logic [511:0]                         s_tile_bits,
    input  logic                                 s_tile_valid,
    output logic                                 s_tile_ready,
    output logic [7:0]                           m_format,
    output logic [511:0]                         m_axis_tdata,
    output logic [63:0]                          m_axis_tkeep,
    output logic                                 m_axis_tlast,
    output logic [15:0]                          m_frame_bytes,
    output logic [31:0]                          m_packet_id,
    output logic                                 m_last_frame_done,
    output logic                                 m_axis_tvalid,
    input  logic                                 m_axis_tready,
    output logic                                 m_fault
);

  assign m_format = 8'(FORMAT);

  prism_numbergroup_native_tile_streamer #(
      .PACKET_CLASS(prism_pkg::PRISM_OP_COL_DATA)
  ) u_streamer (
      .clk(clk), .rst_n(rst_n), .s_reset(s_reset),
      .s_header(s_header), .s_total_elements(s_total_elements),
      .s_mtu(s_mtu), .s_format(8'(FORMAT)),
      .s_tile_first_element(s_tile_first_element),
      .s_tile_count(s_tile_count), .s_tile_bits(s_tile_bits),
      .s_tile_valid(s_tile_valid), .s_tile_ready(s_tile_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_frame_bytes),
      .m_packet_id(m_packet_id),
      .m_last_frame_done(m_last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(m_fault)
  );

endmodule
