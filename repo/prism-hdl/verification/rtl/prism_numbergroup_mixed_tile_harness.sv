//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_mixed_tile_harness.sv
// Module: prism_numbergroup_mixed_tile_harness
// Description: Concrete NumberGroup tile sender with a parsed CCL header template.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_mixed_tile_harness #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MTU_BYTES = 576
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic [511:0]                    s_header_beat,
    input  logic [31:0]                     s_total_elements,
    input  logic [15:0]                     s_mtu,
    input  logic [15:0]                     s_kulisch_bits,
    input  logic [31:0]                     s_tile_first_element,
    input  logic [4:0]                      s_tile_count,
    input  logic [127:0]                    s_formats,
    input  logic [511:0]                    s_native_bits,
    input  logic [127:0]                    s_tags,
    input  logic [16*KULISCH_W-1:0]         s_integers,
    input  logic                            s_tile_valid,
    output logic                            s_tile_ready,
    output logic [511:0]                    m_axis_tdata,
    output logic [63:0]                     m_axis_tkeep,
    output logic                            m_axis_tlast,
    output logic [15:0]                     m_frame_bytes,
    output logic [31:0]                     m_packet_id,
    output logic                            m_last_frame_done,
    output logic                            m_axis_tvalid,
    input  logic                            m_axis_tready,
    output logic                            m_fault
);

  prism_pkg::prism_numbergroup_header_t header;
  logic parser_ready, parser_valid;
  prism_numbergroup_header_parser u_parser (
      .s_tdata(s_header_beat), .s_tkeep('1), .s_valid(s_tile_valid),
      .s_ready(parser_ready), .m_header(header), .m_valid(parser_valid),
      .m_ready(s_tile_ready)
  );

  prism_numbergroup_mixed_tile_streamer #(
      .KULISCH_W(KULISCH_W), .MTU_BYTES(MTU_BYTES)
  ) u_sender (
      .clk(clk), .rst_n(rst_n), .s_reset(1'b0),
      .s_header(header), .s_total_elements(s_total_elements), .s_mtu(s_mtu),
      .s_kulisch_bits(s_kulisch_bits), .s_first_frame_tiles(8'd0),
      .s_tile_first_element(s_tile_first_element),
      .s_tile_count(s_tile_count), .s_formats(s_formats),
      .s_native_bits(s_native_bits), .s_tags(s_tags),
      .s_integers(s_integers), .s_tile_valid(parser_valid),
      .s_tile_ready(s_tile_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_frame_bytes),
      .m_packet_id(m_packet_id), .m_last_frame_done(m_last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(m_fault)
  );
  wire unused_parser_ready = parser_ready;

endmodule
