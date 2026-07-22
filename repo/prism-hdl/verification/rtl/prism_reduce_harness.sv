//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_reduce_harness.sv
// Module: prism_reduce_harness
// Description: Provides a focused conversion and reduction verification boundary.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Typed verification boundary for conversion, reduction, and result formatting.
// The scheduler never receives packet bytes from this harness.
module prism_reduce_harness #(
    parameter int unsigned LANES = 4,
    parameter int unsigned WIDTH_COUNT = 3,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320,
    parameter int unsigned RANGES = 4
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic [15:0]                  s_contributor_id,
    input  logic [15:0]                  s_operation_slot,
    input  logic [15:0]                  s_expected_contributors,
    input  logic [7:0]                   s_input_format,
    input  logic [7:0]                   s_output_format,
    input  logic [7:0]                   s_accumulator_profile,
    input  logic [1:0]                   s_width_index,
    input  logic [LANES*32-1:0]          s_element_bits,
    input  logic [LANES-1:0]             s_element_keep,
    input  logic                         s_valid,
    output logic                         s_ready,
    output logic [LANES*32-1:0]          m_element_bits,
    output logic [LANES-1:0]             m_element_keep,
    output logic [15:0]                  m_operation_slot,
    output logic                         m_accumulation_inexact,
    output logic                         m_valid,
    input  logic                         m_ready
);

  import prism_pkg::*;
  prism_tile_meta_t input_meta, converted_meta, reduced_meta, unused_output_meta;
  logic [LANES*32-1:0] converted_fp32, reduced_fp32;
  logic signed [LANES*WIDTH_2-1:0] converted_deposits;
  logic [LANES-1:0] converted_keep, converted_finite, converted_zero;
  logic [LANES-1:0] converted_zero_sign, converted_nan, converted_pos_inf;
  logic [LANES-1:0] converted_neg_inf, converted_overflow, reduced_keep;
  logic converted_error, converted_valid, converted_ready;
  logic [1:0] converted_width_index;
  logic reduced_warning, reduced_valid, reduced_ready;
  logic output_error;
  logic [LANES-1:0] output_overflow, output_underflow, output_inexact;

  // ---------------------------------------------------------------------------
  // Scenario metadata
  // ---------------------------------------------------------------------------

  always_comb begin
    input_meta = '0;
    input_meta.contributor_id = s_contributor_id;
    input_meta.operation_slot = s_operation_slot;
    input_meta.group_slot = 16'd0;
    input_meta.expected_contributors = s_expected_contributors;
    input_meta.input_format = s_input_format;
    input_meta.output_format = s_output_format;
    input_meta.accumulator_profile = s_accumulator_profile;
    input_meta.selected_width_index = s_width_index;
    input_meta.semantic = PRISM_SEMANTIC_ALLREDUCE;
    input_meta.total_element_count = LANES;
    input_meta.result_route_count = 16'd1;
    input_meta.element_count = 8'(LANES);
    input_meta.last_tile = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // Typed reduction pipeline under test
  // ---------------------------------------------------------------------------

  prism_input_conversion_stage #(
      .LANES(LANES),
      .WIDTH_COUNT(WIDTH_COUNT),
      .WIDTH_0(WIDTH_0),
      .WIDTH_1(WIDTH_1),
      .WIDTH_2(WIDTH_2)
  ) u_input_conversion (
      .clk(clk),
      .rst_n(rst_n),
      .s_meta(input_meta),
      .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep),
      .s_width_index(s_width_index),
      .s_valid(s_valid),
      .s_ready(s_ready),
      .m_meta(converted_meta),
      .m_fp32_bits(converted_fp32),
      .m_kulisch_deposits(converted_deposits),
      .m_element_keep(converted_keep),
      .m_finite(converted_finite),
      .m_zero(converted_zero),
      .m_zero_sign(converted_zero_sign),
      .m_nan(converted_nan),
      .m_positive_infinity(converted_pos_inf),
      .m_negative_infinity(converted_neg_inf),
      .m_deposit_overflow(converted_overflow),
      .m_format_error(converted_error),
      .m_width_index(converted_width_index),
      .m_valid(converted_valid),
      .m_ready(converted_ready)
  );

  prism_range_scheduler #(
      .LANES(LANES),
      .RANGES(RANGES),
      .CONTRIBUTORS(2),
      .WIDTH_0(WIDTH_0),
      .WIDTH_1(WIDTH_1),
      .WIDTH_2(WIDTH_2)
  ) u_scheduler (
      .clk(clk),
      .rst_n(rst_n),
      .s_meta(converted_meta),
      .s_fp32_bits(converted_fp32),
      .s_kulisch_deposits(converted_deposits),
      .s_element_keep(converted_keep),
      .s_finite(converted_finite),
      .s_zero(converted_zero),
      .s_zero_sign(converted_zero_sign),
      .s_nan(converted_nan),
      .s_positive_infinity(converted_pos_inf),
      .s_negative_infinity(converted_neg_inf),
      .s_deposit_overflow(converted_overflow),
      .s_width_index(converted_width_index),
      .s_format_error(converted_error),
      .s_valid(converted_valid),
      .s_ready(converted_ready),
      .m_meta(reduced_meta),
      .m_fp32_bits(reduced_fp32),
      .m_element_keep(reduced_keep),
      .m_accumulation_inexact(reduced_warning),
      .m_valid(reduced_valid),
      .m_ready(reduced_ready)
  );

  prism_result_conversion_stage #(
      .LANES(LANES)
  ) u_output_conversion (
      .clk(clk),
      .rst_n(rst_n),
      .s_meta(reduced_meta),
      .s_fp32_bits(reduced_fp32),
      .s_element_keep(reduced_keep),
      .s_accumulation_inexact(reduced_warning),
      .s_valid(reduced_valid),
      .s_ready(reduced_ready),
      .m_meta(unused_output_meta),
      .m_element_bits(m_element_bits),
      .m_element_keep(m_element_keep),
      .m_accumulation_inexact(m_accumulation_inexact),
      .m_overflow(output_overflow),
      .m_underflow(output_underflow),
      .m_inexact(output_inexact),
      .m_format_error(output_error),
      .m_valid(m_valid),
      .m_ready(m_ready)
  );

  assign m_operation_slot = unused_output_meta.operation_slot;

endmodule
