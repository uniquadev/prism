//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_kulisch_result_frame_harness.sv
// Module: prism_exact_kulisch_result_frame_harness
// Description: Exact tile bank through Kulisch RESULT NumberGroup frames.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_exact_kulisch_result_frame_harness (
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
    output logic [511:0]                         m_axis_tdata,
    output logic [63:0]                          m_axis_tkeep,
    output logic                                 m_axis_tlast,
    output logic [15:0]                          m_frame_bytes,
    output logic                                 m_axis_tvalid,
    input  logic                                 m_axis_tready,
    output logic                                 m_fault
);

  logic [7:0] result_slot;
  logic [15:0] result_present;
  logic [127:0] result_tags;
  logic [5119:0] result_integers;
  logic result_valid, result_ready;
  // The serializer has a ready, the bank has none: results wait in between.
  localparam int unsigned RESULT_W = $bits(result_slot) + 16 + 128 + 5120;
  logic request_ready, bank_read_ready, held_valid;
  logic [$bits(result_slot)-1:0] held_slot;
  logic [15:0] held_present;
  logic [127:0] held_tags;
  logic [5119:0] held_integers;
  assign s_result_read_ready = bank_read_ready && request_ready;
  prism_bank_result_hold #(.WIDTH(RESULT_W)) u_hold (
      .clk(clk), .rst_n(rst_n),
      .m_request_ready(request_ready),
      .s_request_fire(s_result_read_valid && s_result_read_ready),
      .s_data({result_slot, result_present, result_tags, result_integers}),
      .s_valid(result_valid),
      .m_data({held_slot, held_present, held_tags, held_integers}),
      .m_valid(held_valid), .m_ready(result_ready)
  );
  logic [31:0] pair_first;
  logic [1:0] pair_count;
  logic [15:0] pair_tags;
  logic [639:0] pair_integers;
  logic pair_valid, pair_ready, serializer_fault, streamer_fault;
  logic [31:0] unused_first;
  logic [15:0] unused_keep;
  logic [127:0] unused_tags;
  logic [5119:0] unused_integers;
  logic [31:0] unused_errors;
  logic unused_tile_valid, unused_release_ready, unused_last_frame_done;
  logic [31:0] unused_packet_id;
  wire unused_results = ^{unused_first, unused_keep, unused_tags,
      unused_integers, unused_errors, unused_tile_valid,
      unused_release_ready, unused_last_frame_done, unused_packet_id};

  prism_exact_native_tile_pipeline u_bank (
      .clk(clk), .rst_n(rst_n),
      .s_slot(s_slot), .s_first_element(s_first_element),
      .s_format(s_format), .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep), .s_valid(s_valid), .s_ready(s_ready),
      .s_release(1'b0), .s_release_ready(unused_release_ready),
      .s_result_slot(s_result_slot),
      .s_result_read_arm(s_result_read_valid),
      .s_result_read_valid(s_result_read_valid && request_ready),
      .s_result_read_ready(bank_read_ready),
      .m_result_slot(result_slot), .m_result_present(result_present),
      .m_result_tags(result_tags), .m_result_integers(result_integers),
      .m_result_valid(result_valid),
      .m_first_element(unused_first), .m_element_keep(unused_keep),
      .m_kulisch_tags(unused_tags), .m_kulisch_integers(unused_integers),
      .m_errors(unused_errors), .m_valid(unused_tile_valid), .m_ready(1'b1)
  );

  prism_kulisch_tile_serializer16 u_serializer (
      .clk(clk), .rst_n(rst_n), .s_clear(1'b0),
      .s_first_element(32'(held_slot) << 4),
      .s_keep(held_present), .s_tags(held_tags),
      .s_integers(held_integers),
      .s_valid(held_valid), .s_ready(result_ready),
      .m_first_element(pair_first), .m_count(pair_count),
      .m_tags(pair_tags), .m_integers(pair_integers),
      .m_valid(pair_valid), .m_ready(pair_ready), .m_fault(serializer_fault)
  );

  prism_numbergroup_kulisch_tile_streamer #(
      .PACKET_CLASS(prism_pkg::PRISM_OP_COL_RES)
  ) u_streamer (
      .clk(clk), .rst_n(rst_n), .s_reset(1'b0),
      .s_header(s_header), .s_total_elements(s_total_elements),
      .s_mtu(16'd1500), .s_tile_first_element(pair_first),
      .s_tile_count(pair_count), .s_tags(pair_tags),
      .s_integers(pair_integers), .s_tile_valid(pair_valid),
      .s_tile_ready(pair_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_frame_bytes),
      .m_packet_id(unused_packet_id),
      .m_last_frame_done(unused_last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(streamer_fault)
  );

  assign m_fault = serializer_fault || streamer_fault;

endmodule
