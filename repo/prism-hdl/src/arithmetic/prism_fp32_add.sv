//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_add.sv
// Module: prism_fp32_add
// Description: Adds binary32 values in a five-stage elastic pipeline.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_add (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [31:0] s_left,
    input  logic [31:0] s_right,
    input  logic        s_valid,
    output logic        s_ready,
    output logic [31:0] m_result,
    output logic [4:0]  m_exceptions,
    output logic        m_valid,
    input  logic        m_ready
);

  logic p0_valid;
  logic p1_valid;
  logic p2_valid;
  logic p3_valid;
  logic p0_ready;
  logic p1_ready;
  logic p2_ready;
  logic p3_ready;
  logic output_ready;

  logic p0_special;
  logic [31:0] p0_special_result;
  logic [4:0] p0_special_exceptions;
  logic signed [9:0] p0_large_exponent;
  logic signed [9:0] p0_small_exponent;
  logic p0_large_sign;
  logic p0_small_sign;
  logic [23:0] p0_large_significand;
  logic [23:0] p0_small_significand;

  logic p1_special;
  logic [31:0] p1_special_result;
  logic [4:0] p1_special_exceptions;
  logic signed [9:0] p1_result_exponent;
  logic p1_large_sign;
  logic p1_small_sign;
  logic [26:0] p1_large_extended;
  logic [26:0] p1_aligned_small;

  logic p2_special;
  logic [31:0] p2_special_result;
  logic [4:0] p2_special_exceptions;
  logic signed [9:0] p2_result_exponent;
  logic p2_result_sign;
  logic [26:0] p2_arithmetic_result;
  logic p2_normalize_left;

  logic p3_special;
  logic [31:0] p3_special_result;
  logic [4:0] p3_special_exceptions;
  logic signed [9:0] p3_result_exponent;
  logic p3_result_sign;
  logic [26:0] p3_arithmetic_result;

  logic input_special;
  logic [31:0] input_special_result;
  logic [4:0] input_special_exceptions;
  logic signed [9:0] input_large_exponent;
  logic signed [9:0] input_small_exponent;
  logic input_large_sign;
  logic input_small_sign;
  logic [23:0] input_large_significand;
  logic [23:0] input_small_significand;

  logic [26:0] aligned_small;
  logic [27:0] arithmetic_sum;
  logic [26:0] arithmetic_value;
  logic signed [9:0] arithmetic_exponent;
  logic arithmetic_sign;
  logic arithmetic_normalize_left;
  logic [26:0] normalized_value;
  logic signed [9:0] normalized_exponent;
  logic [31:0] rounded_result;
  logic [4:0] rounded_exceptions;

  function automatic logic [26:0] shift_right_sticky(
      input logic [26:0] value,
      input logic [7:0] amount
  );
    logic [26:0] shifted;
    logic sticky;
    shifted = '0;
    sticky = 1'b0;
    if (amount == 0) begin
      shifted = value;
    end else if (amount >= 27) begin
      shifted[0] = |value;
    end else begin
      shifted = value >> amount;
      for (int unsigned index = 0; index < 27; index++) begin
        if (index < amount) sticky |= value[index];
      end
      shifted[0] |= sticky;
    end
    return shifted;
  endfunction

  function automatic logic [4:0] count_leading_zeros_27(
      input logic [26:0] value
  );
    logic found;
    count_leading_zeros_27 = 5'd27;
    found = 1'b0;
    for (int index = 26; index >= 0; index--) begin
      if (!found && value[index]) begin
        count_leading_zeros_27 = 5'(26 - index);
        found = 1'b1;
      end
    end
  endfunction

  assign output_ready = !m_valid || m_ready;
  assign p3_ready = !p3_valid || output_ready;
  assign p2_ready = !p2_valid || p3_ready;
  assign p1_ready = !p1_valid || p2_ready;
  assign p0_ready = !p0_valid || p1_ready;
  assign s_ready = p0_ready;

  always_comb begin
    logic left_sign;
    logic right_sign;
    logic [7:0] left_exp_field;
    logic [7:0] right_exp_field;
    logic [22:0] left_fraction;
    logic [22:0] right_fraction;
    logic left_nan;
    logic right_nan;
    logic left_inf;
    logic right_inf;
    logic left_zero;
    logic right_zero;
    logic signed [9:0] left_exponent;
    logic signed [9:0] right_exponent;
    logic [23:0] left_significand;
    logic [23:0] right_significand;

    left_sign = s_left[31];
    right_sign = s_right[31];
    left_exp_field = s_left[30:23];
    right_exp_field = s_right[30:23];
    left_fraction = s_left[22:0];
    right_fraction = s_right[22:0];
    left_nan = (left_exp_field == 8'hFF) && (left_fraction != 0);
    right_nan = (right_exp_field == 8'hFF) && (right_fraction != 0);
    left_inf = (left_exp_field == 8'hFF) && (left_fraction == 0);
    right_inf = (right_exp_field == 8'hFF) && (right_fraction == 0);
    left_zero = (left_exp_field == 0) && (left_fraction == 0);
    right_zero = (right_exp_field == 0) && (right_fraction == 0);
    left_exponent = (left_exp_field == 0)
        ? -10'sd126 : $signed({1'b0, left_exp_field}) - 10'sd127;
    right_exponent = (right_exp_field == 0)
        ? -10'sd126 : $signed({1'b0, right_exp_field}) - 10'sd127;
    left_significand = (left_exp_field == 0)
        ? {1'b0, left_fraction} : {1'b1, left_fraction};
    right_significand = (right_exp_field == 0)
        ? {1'b0, right_fraction} : {1'b1, right_fraction};

    input_special = 1'b0;
    input_special_result = '0;
    input_special_exceptions = '0;
    if (left_nan || right_nan
        || (left_inf && right_inf && (left_sign != right_sign))) begin
      input_special = 1'b1;
      input_special_result = 32'h7FC0_0000;
      input_special_exceptions[4] = 1'b1;
    end else if (left_inf) begin
      input_special = 1'b1;
      input_special_result = {left_sign, 8'hFF, 23'h0};
    end else if (right_inf) begin
      input_special = 1'b1;
      input_special_result = {right_sign, 8'hFF, 23'h0};
    end else if (left_zero && right_zero) begin
      input_special = 1'b1;
      input_special_result = {(left_sign == right_sign) && left_sign, 31'h0};
    end

    input_large_exponent = left_exponent;
    input_small_exponent = right_exponent;
    input_large_sign = left_sign;
    input_small_sign = right_sign;
    input_large_significand = left_significand;
    input_small_significand = right_significand;
    if ((right_exponent > left_exponent)
        || ((right_exponent == left_exponent)
            && (right_significand > left_significand))) begin
      input_large_exponent = right_exponent;
      input_small_exponent = left_exponent;
      input_large_sign = right_sign;
      input_small_sign = left_sign;
      input_large_significand = right_significand;
      input_small_significand = left_significand;
    end
  end

  always_comb begin
    aligned_small = shift_right_sticky(
        {p0_small_significand, 3'b000},
        8'(p0_large_exponent - p0_small_exponent));
  end

  always_comb begin
    arithmetic_sum = '0;
    arithmetic_value = '0;
    arithmetic_exponent = p1_result_exponent;
    arithmetic_sign = p1_large_sign;
    arithmetic_normalize_left = p1_large_sign != p1_small_sign;
    if (!arithmetic_normalize_left) begin
      arithmetic_sum = {1'b0, p1_large_extended}
          + {1'b0, p1_aligned_small};
      if (arithmetic_sum[27]) begin
        arithmetic_value = arithmetic_sum[27:1];
        arithmetic_value[0] |= arithmetic_sum[0];
        arithmetic_exponent = p1_result_exponent + 1;
      end else begin
        arithmetic_value = arithmetic_sum[26:0];
      end
    end else begin
      arithmetic_value = p1_large_extended - p1_aligned_small;
      if (arithmetic_value == 0) arithmetic_sign = 1'b0;
    end
  end

  always_comb begin
    logic [4:0] leading_zero_count;
    logic [8:0] normalization_limit;
    logic [4:0] normalization_shift;

    normalized_value = p2_arithmetic_result;
    normalized_exponent = p2_result_exponent;
    leading_zero_count = count_leading_zeros_27(p2_arithmetic_result);
    normalization_limit = 9'(p2_result_exponent + 10'sd126);
    normalization_shift = (9'(leading_zero_count) < normalization_limit)
        ? leading_zero_count : 5'(normalization_limit);
    if (p2_normalize_left && (p2_arithmetic_result != 0)) begin
      normalized_value = p2_arithmetic_result << normalization_shift;
      normalized_exponent = p2_result_exponent - 10'(normalization_shift);
    end
  end

  always_comb begin
    logic guard_bit;
    logic round_bit;
    logic sticky_bit;
    logic operation_inexact;
    logic round_increment;
    logic [24:0] rounded_significand;
    logic [23:0] final_significand;
    logic signed [9:0] final_exponent;

    rounded_result = 32'h0000_0000;
    rounded_exceptions = '0;
    guard_bit = p3_arithmetic_result[2];
    round_bit = p3_arithmetic_result[1];
    sticky_bit = p3_arithmetic_result[0];
    operation_inexact = guard_bit || round_bit || sticky_bit;
    round_increment = guard_bit
        && (round_bit || sticky_bit || p3_arithmetic_result[3]);
    rounded_significand = {1'b0, p3_arithmetic_result[26:3]}
        + {24'b0, round_increment};
    final_significand = rounded_significand[23:0];
    final_exponent = p3_result_exponent;
    if (rounded_significand[24]) begin
      final_significand = rounded_significand[24:1];
      final_exponent = p3_result_exponent + 1;
    end

    if (p3_special) begin
      rounded_result = p3_special_result;
      rounded_exceptions = p3_special_exceptions;
    end else if (p3_arithmetic_result == 0) begin
      rounded_result = 32'h0000_0000;
    end else if (final_exponent > 127) begin
      rounded_result = {p3_result_sign, 8'hFF, 23'h0};
      rounded_exceptions[2] = 1'b1;
      rounded_exceptions[0] = 1'b1;
    end else if ((final_exponent == -126) && !final_significand[23]) begin
      rounded_result = {p3_result_sign, 8'h00, final_significand[22:0]};
      rounded_exceptions[1] = operation_inexact;
      rounded_exceptions[0] = operation_inexact;
    end else begin
      rounded_result = {
        p3_result_sign, 8'(final_exponent + 10'sd127), final_significand[22:0]
      };
      rounded_exceptions[0] = operation_inexact;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      p0_valid <= 1'b0;
      p1_valid <= 1'b0;
      p2_valid <= 1'b0;
      p3_valid <= 1'b0;
      m_valid <= 1'b0;
    end else begin
      if (p0_ready) begin
        p0_valid <= s_valid;
      end
      if (p1_ready) begin
        p1_valid <= p0_valid;
      end
      if (p2_ready) begin
        p2_valid <= p1_valid;
      end
      if (p3_ready) begin
        p3_valid <= p2_valid;
      end
      if (output_ready) begin
        m_valid <= p3_valid;
      end
    end
  end

  // Datapath registers deliberately have no reset. Their contents are
  // unobservable while the corresponding valid bit is clear. Keeping reset
  // off the arithmetic payload reduces control sets and reset fanout when the
  // adder is replicated across every lane.
  always_ff @(posedge clk) begin
    if (p0_ready && s_valid) begin
      p0_special <= input_special;
      p0_special_result <= input_special_result;
      p0_special_exceptions <= input_special_exceptions;
      p0_large_exponent <= input_large_exponent;
      p0_small_exponent <= input_small_exponent;
      p0_large_sign <= input_large_sign;
      p0_small_sign <= input_small_sign;
      p0_large_significand <= input_large_significand;
      p0_small_significand <= input_small_significand;
    end
    if (p1_ready && p0_valid) begin
      p1_special <= p0_special;
      p1_special_result <= p0_special_result;
      p1_special_exceptions <= p0_special_exceptions;
      p1_result_exponent <= p0_large_exponent;
      p1_large_sign <= p0_large_sign;
      p1_small_sign <= p0_small_sign;
      p1_large_extended <= {p0_large_significand, 3'b000};
      p1_aligned_small <= aligned_small;
    end
    if (p2_ready && p1_valid) begin
      p2_special <= p1_special;
      p2_special_result <= p1_special_result;
      p2_special_exceptions <= p1_special_exceptions;
      p2_result_exponent <= arithmetic_exponent;
      p2_result_sign <= arithmetic_sign;
      p2_arithmetic_result <= arithmetic_value;
      p2_normalize_left <= arithmetic_normalize_left;
    end
    if (p3_ready && p2_valid) begin
      p3_special <= p2_special;
      p3_special_result <= p2_special_result;
      p3_special_exceptions <= p2_special_exceptions;
      p3_result_exponent <= normalized_exponent;
      p3_result_sign <= p2_result_sign;
      p3_arithmetic_result <= normalized_value;
    end
    if (output_ready && p3_valid) begin
      m_result <= rounded_result;
      m_exceptions <= rounded_exceptions;
    end
  end

endmodule
