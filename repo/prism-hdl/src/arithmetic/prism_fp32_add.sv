//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_add.sv
// Module: prism_fp32_add
// Description: Adds two binary32 values with canonical exceptions and ties-to-even rounding.
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

  logic [31:0] result_comb;
  logic [4:0] exceptions_comb;

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
  logic [23:0] left_significand;
  logic [23:0] right_significand;
  integer left_exponent;
  integer right_exponent;
  integer large_exponent;
  integer small_exponent;
  integer result_exponent;
  integer exponent_delta;
  logic large_sign;
  logic small_sign;
  logic [23:0] large_significand;
  logic [23:0] small_significand;
  logic [26:0] large_extended;
  logic [26:0] small_extended;
  logic [26:0] aligned_small;
  logic [27:0] add_result;
  logic [26:0] arithmetic_result;
  logic [24:0] rounded_significand;
  logic [23:0] final_significand;
  logic result_sign;
  logic guard_bit;
  logic round_bit;
  logic sticky_bit;
  logic round_increment;
  logic operation_inexact;

  function automatic logic [26:0] shift_right_sticky(
      input logic [26:0] value,
      input int unsigned amount
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
        if (index < amount) begin
          sticky |= value[index];
        end
      end
      shifted[0] |= sticky;
    end
    return shifted;
  endfunction

  assign s_ready = !m_valid || m_ready;

  always_comb begin
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
    left_significand = (left_exp_field == 0) ? {1'b0, left_fraction} : {1'b1, left_fraction};
    right_significand = (right_exp_field == 0) ? {1'b0, right_fraction} : {1'b1, right_fraction};
    left_exponent = (left_exp_field == 0) ? -126 : int'(left_exp_field) - 127;
    right_exponent = (right_exp_field == 0) ? -126 : int'(right_exp_field) - 127;
    large_exponent = left_exponent;
    small_exponent = right_exponent;
    large_sign = left_sign;
    small_sign = right_sign;
    large_significand = left_significand;
    small_significand = right_significand;
    large_extended = '0;
    small_extended = '0;
    aligned_small = '0;
    add_result = '0;
    arithmetic_result = '0;
    rounded_significand = '0;
    final_significand = '0;
    result_exponent = 0;
    exponent_delta = 0;
    result_sign = 1'b0;
    guard_bit = 1'b0;
    round_bit = 1'b0;
    sticky_bit = 1'b0;
    round_increment = 1'b0;
    operation_inexact = 1'b0;
    result_comb = 32'h0000_0000;
    exceptions_comb = 5'b00000;

    if (left_nan || right_nan || (left_inf && right_inf && (left_sign != right_sign))) begin
      result_comb = 32'h7FC0_0000;
      exceptions_comb[4] = 1'b1;
    end else if (left_inf) begin
      result_comb = {left_sign, 8'hFF, 23'h0};
    end else if (right_inf) begin
      result_comb = {right_sign, 8'hFF, 23'h0};
    end else if (left_zero && right_zero) begin
      result_comb = {(left_sign == right_sign) && left_sign, 31'h0};
    end else begin
      if ((right_exponent > left_exponent)
          || ((right_exponent == left_exponent) && (right_significand > left_significand))) begin
        large_exponent = right_exponent;
        small_exponent = left_exponent;
        large_sign = right_sign;
        small_sign = left_sign;
        large_significand = right_significand;
        small_significand = left_significand;
      end
      result_exponent = large_exponent;
      exponent_delta = large_exponent - small_exponent;
      large_extended = {large_significand, 3'b000};
      small_extended = {small_significand, 3'b000};
      aligned_small = shift_right_sticky(small_extended, exponent_delta);
      result_sign = large_sign;

      if (large_sign == small_sign) begin
        add_result = {1'b0, large_extended} + {1'b0, aligned_small};
        if (add_result[27]) begin
          arithmetic_result = add_result[27:1];
          arithmetic_result[0] |= add_result[0];
          result_exponent += 1;
        end else begin
          arithmetic_result = add_result[26:0];
        end
      end else begin
        arithmetic_result = large_extended - aligned_small;
        if (arithmetic_result == 0) begin
          result_sign = 1'b0;
        end else begin
          for (int unsigned step = 0; step < 26; step++) begin
            if (!arithmetic_result[26] && (result_exponent > -126)) begin
              arithmetic_result = arithmetic_result << 1;
              result_exponent -= 1;
            end
          end
        end
      end

      if (arithmetic_result == 0) begin
        result_comb = 32'h0000_0000;
      end else begin
        guard_bit = arithmetic_result[2];
        round_bit = arithmetic_result[1];
        sticky_bit = arithmetic_result[0];
        operation_inexact = guard_bit || round_bit || sticky_bit;
        round_increment = guard_bit
            && (round_bit || sticky_bit || arithmetic_result[3]);
        rounded_significand =
            {1'b0, arithmetic_result[26:3]} + {24'b0, round_increment};
        if (rounded_significand[24]) begin
          final_significand = rounded_significand[24:1];
          result_exponent += 1;
        end else begin
          final_significand = rounded_significand[23:0];
        end

        if (result_exponent > 127) begin
          result_comb = {result_sign, 8'hFF, 23'h0};
          exceptions_comb[2] = 1'b1;
          exceptions_comb[0] = 1'b1;
        end else if ((result_exponent == -126) && !final_significand[23]) begin
          result_comb = {result_sign, 8'h00, final_significand[22:0]};
          exceptions_comb[1] = operation_inexact;
          exceptions_comb[0] = operation_inexact;
        end else begin
          result_comb = {result_sign, 8'(result_exponent + 127), final_significand[22:0]};
          exceptions_comb[0] = operation_inexact;
        end
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_result <= '0;
      m_exceptions <= '0;
      m_valid <= 1'b0;
    end else if (s_ready) begin
      m_valid <= s_valid;
      if (s_valid) begin
        m_result <= result_comb;
        m_exceptions <= exceptions_comb;
      end
    end
  end

endmodule
