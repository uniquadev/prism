//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_result_frame_harness.sv
// Module: prism_exact_result_frame_harness
// Description: Exact tile accumulation, native rounding and RESULT frames.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_exact_result_frame_harness (
    input  logic                                 clk,
    input  logic                                 rst_n,
    input  logic [7:0]                           s_slot,
    input  logic [31:0]                          s_first_element,
    input  logic [7:0]                           s_format,
    input  logic [511:0]                         s_element_bits,
    input  logic [15:0]                          s_element_keep,
    input  logic                                 s_valid,
    output logic                                 s_ready,
    input  logic [7:0]                           s_result_slot,
    input  logic                                 s_result_read_valid,
    output logic                                 s_result_read_ready,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                          s_total_elements,
    input  logic [7:0]                           s_output_format,
    output logic [511:0]                         m_axis_tdata,
    output logic [63:0]                          m_axis_tkeep,
    output logic                                 m_axis_tlast,
    output logic [15:0]                          m_frame_bytes,
    output logic                                 m_axis_tvalid,
    input  logic                                 m_axis_tready,
    output logic                                 m_fault
);

  logic [31:0] tile_first;
  logic [15:0] tile_keep;
  logic [511:0] tile_bits;
  logic tile_error, tile_valid, tile_ready;
  logic streamer_fault;
  logic [31:0] unused_packet_id;
  logic unused_last_frame_done;
  assign m_fault = tile_error || streamer_fault;

  prism_exact_result_tile_harness u_tiles (
      .clk(clk), .rst_n(rst_n),
      .s_slot(s_slot), .s_first_element(s_first_element),
      .s_format(s_format), .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep), .s_valid(s_valid), .s_ready(s_ready),
      .s_result_slot(s_result_slot),
      .s_result_read_valid(s_result_read_valid),
      .s_result_read_ready(s_result_read_ready),
      .s_output_format(s_output_format),
      .m_first_element(tile_first), .m_element_keep(tile_keep),
      .m_element_bits(tile_bits), .m_error(tile_error),
      .m_valid(tile_valid), .m_ready(tile_ready)
  );

  prism_numbergroup_native_tile_streamer u_streamer (
      .clk(clk), .rst_n(rst_n), .s_reset(1'b0),
      .s_header(s_header), .s_total_elements(s_total_elements),
      .s_mtu(16'd1500), .s_format(s_output_format),
      .s_tile_first_element(tile_first),
      .s_tile_count(7'($countones(tile_keep))),
      .s_tile_bits(tile_bits),
      .s_tile_valid(tile_valid && !tile_error), .s_tile_ready(tile_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_frame_bytes),
      .m_packet_id(unused_packet_id),
      .m_last_frame_done(unused_last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(streamer_fault)
  );

endmodule
