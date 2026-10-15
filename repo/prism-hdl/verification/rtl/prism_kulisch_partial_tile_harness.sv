//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_partial_tile_harness.sv
// Module: prism_kulisch_partial_tile_harness
// Description: Exact tile adapter and Kulisch NumberGroup DATA sender.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_partial_tile_harness #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MTU_BYTES = 576
) (
    input  logic                                 clk,
    input  logic                                 rst_n,
    input  logic                                 s_reset,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                          s_total_elements,
    input  logic [15:0]                          s_mtu,
    input  logic [31:0]                          s_tile_first_element,
    input  logic [4:0]                           s_tile_count,
    input  logic [127:0]                         s_tile_tags,
    input  logic [16*KULISCH_W-1:0]              s_tile_integers,
    input  logic                                 s_tile_valid,
    output logic                                 s_tile_ready,
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

  logic [31:0] pair_first;
  logic [1:0] pair_count;
  logic [15:0] pair_tags;
  logic [2*KULISCH_W-1:0] pair_integers;
  logic pair_valid, pair_ready, pair_fault, streamer_fault;

  assign m_fault = pair_fault || streamer_fault;

  prism_kulisch_tile_pairer #(.KULISCH_W(KULISCH_W)) u_pairer (
      .clk(clk), .rst_n(rst_n), .s_clear(s_reset),
      .s_first_element(s_tile_first_element),
      .s_count(s_tile_count), .s_tags(s_tile_tags),
      .s_integers(s_tile_integers),
      .s_valid(s_tile_valid), .s_ready(s_tile_ready),
      .m_first_element(pair_first), .m_count(pair_count),
      .m_tags(pair_tags), .m_integers(pair_integers),
      .m_valid(pair_valid), .m_ready(pair_ready),
      .m_fault(pair_fault)
  );

  prism_numbergroup_kulisch_tile_streamer #(
      .KULISCH_W(KULISCH_W), .MTU_BYTES(MTU_BYTES)
  ) u_streamer (
      .clk(clk), .rst_n(rst_n), .s_reset(s_reset),
      .s_header(s_header), .s_total_elements(s_total_elements),
      .s_mtu(s_mtu), .s_tile_first_element(pair_first),
      .s_tile_count(pair_count), .s_tags(pair_tags),
      .s_integers(pair_integers),
      .s_tile_valid(pair_valid), .s_tile_ready(pair_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_frame_bytes),
      .m_packet_id(m_packet_id),
      .m_last_frame_done(m_last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(streamer_fault)
  );

endmodule
