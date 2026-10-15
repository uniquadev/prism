//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_auto_partial_stream_harness.sv
// Module: prism_exact_auto_partial_stream_harness
// Description: Exact striped arithmetic feeding the wide AUTO partial sender.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_exact_auto_partial_stream_harness (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [511:0] s_header_beat,
    input  logic [31:0]  s_total_elements,
    input  logic [15:0]  s_mtu,
    input  logic [15:0]  s_kulisch_bits,
    input  logic [31:0]  s_first_element,
    input  logic [511:0] s_bits,
    input  logic [63:0]  s_keep,
    input  logic         s_valid,
    output logic         s_ready,
    input  logic [7:0]   s_read_slot,
    input  logic         s_read_valid,
    output logic         s_read_ready,
    output logic [511:0] m_axis_tdata,
    output logic [63:0]  m_axis_tkeep,
    output logic         m_axis_tlast,
    output logic [15:0]  m_frame_bytes,
    output logic [31:0]  m_packet_id,
    output logic         m_last_frame_done,
    output logic         m_axis_tvalid,
    input  logic         m_axis_tready,
    output logic         m_fault
);

  prism_pkg::prism_numbergroup_header_t header;
  logic header_ready, header_valid;
  logic [7:0] result_slot;
  logic [127:0] result_present;
  logic [1023:0] result_tags;
  logic [40959:0] result_integers;
  logic result_valid, result_ready, bank_fault, sender_fault;
  // The sender has a ready, the banks have none: results wait in between.
  logic request_ready, bank_read_ready, held_valid;
  logic [7:0] held_slot;
  logic [127:0] held_present;
  logic [1023:0] held_tags;
  logic [40959:0] held_integers;
  assign s_read_ready = bank_read_ready && request_ready;
  prism_bank_result_hold #(.WIDTH(8 + 128 + 1024 + 40960)) u_hold (
      .clk(clk), .rst_n(rst_n),
      .m_request_ready(request_ready),
      .s_request_fire(s_read_valid && s_read_ready),
      .s_data({result_slot, result_present, result_tags, result_integers}),
      .s_valid(result_valid),
      .m_data({held_slot, held_present, held_tags, held_integers}),
      .m_valid(held_valid), .m_ready(result_ready)
  );

  prism_numbergroup_header_parser u_parser (
      .s_tdata(s_header_beat), .s_tkeep('1), .s_valid(held_valid),
      .s_ready(header_ready), .m_header(header), .m_valid(header_valid),
      .m_ready(result_ready)
  );

  prism_striped_exact_tile_port #(
      .BANKS(8), .RESULT_LANES(128)
  ) u_exact (
      .clk(clk), .rst_n(rst_n), .s_first_element(s_first_element),
      .s_format(prism_pkg::PRISM_FORMAT_FP32), .s_bits(s_bits),
      .s_keep(s_keep), .s_valid(s_valid), .s_ready(s_ready),
      .s_flush(1'b0), .s_release(1'b0), .s_release_ready(),
      .s_result_slot(s_read_slot), .s_wide_result(1'b1),
      .s_result_read_valid(s_read_valid && request_ready),
      .s_result_read_ready(bank_read_ready),
      .m_result_slot(result_slot), .m_result_present(result_present),
      .m_result_tags(result_tags), .m_result_integers(result_integers),
      .m_result_valid(result_valid),
      .m_arithmetic_fault(bank_fault)
  );

  prism_numbergroup_auto_partial_sender #(.LANES(128)) u_sender (
      .clk(clk), .rst_n(rst_n), .s_reset(1'b0),
      .s_header(header), .s_total_elements(s_total_elements),
      .s_mtu(s_mtu), .s_kulisch_bits(s_kulisch_bits),
      .s_tile_first_element(32'(held_slot) << 4),
      .s_tile_keep(held_present), .s_native_input(1'b0),
      .s_tile_native_bits('0), .s_tile_tags(held_tags),
      .s_tile_integers(held_integers),
      .s_tile_valid(header_valid), .s_tile_ready(result_ready),
      .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
      .m_axis_tlast(m_axis_tlast), .m_frame_bytes(m_frame_bytes),
      .m_packet_id(m_packet_id), .m_last_frame_done(m_last_frame_done),
      .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
      .m_fault(sender_fault)
  );

  assign m_fault = bank_fault || sender_fault;
  wire unused_header_ready = header_ready;

endmodule
