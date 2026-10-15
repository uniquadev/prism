//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_result_tile_harness.sv
// Module: prism_exact_result_tile_harness
// Description: Exact tile RAM read through sixteen parallel final rounders.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_exact_result_tile_harness (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [7:0]   s_slot,
    input  logic [31:0]  s_first_element,
    input  logic [7:0]   s_format,
    input  logic [511:0] s_element_bits,
    input  logic [15:0]  s_element_keep,
    input  logic         s_valid,
    output logic         s_ready,
    input  logic [7:0]   s_result_slot,
    input  logic         s_result_read_valid,
    output logic         s_result_read_ready,
    input  logic [7:0]   s_output_format,
    output logic [31:0]  m_first_element,
    output logic [15:0]  m_element_keep,
    output logic [511:0] m_element_bits,
    output logic         m_error,
    output logic         m_valid,
    input  logic         m_ready
);

  logic [7:0] result_slot;
  logic [15:0] result_present;
  logic [127:0] result_tags;
  logic [5119:0] result_integers;
  logic result_valid, result_ready, request_ready, bank_read_ready;
  // A read is granted only while the rounding has a place for its result.
  assign s_result_read_ready = bank_read_ready && request_ready;
  logic [31:0] unused_first;
  logic [15:0] unused_keep;
  logic [127:0] unused_tags;
  logic [5119:0] unused_integers;
  logic [31:0] unused_errors;
  logic unused_tile_valid;
  logic unused_release_ready;
  wire unused_results = ^{unused_first, unused_keep, unused_tags,
      unused_integers, unused_errors, unused_tile_valid,
      unused_release_ready};

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

  prism_exact_final_round_tile u_round (
      .clk(clk), .rst_n(rst_n),
      .s_first_element(32'(result_slot) << 4),
      .s_element_keep(result_present),
      .s_kulisch_tags(result_tags),
      .s_kulisch_integers(result_integers),
      .s_output_format(s_output_format),
      .s_valid(result_valid), .s_ready(result_ready),
      .m_request_ready(request_ready),
      .s_enable(1'b1), .s_fault(1'b0), .s_flush(1'b0),
      .m_first_element(m_first_element), .m_element_keep(m_element_keep),
      .m_element_bits(m_element_bits), .m_error(m_error),
      .m_valid(m_valid), .m_ready(m_ready)
  );

endmodule
