//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_to_fp32.sv
// Module: prism_kulisch_to_fp32
// Description: Normalizes and rounds one signed fixed-point accumulator to binary32.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_to_fp32 #(
    parameter int unsigned ACC_W = 320
) (
    input  logic signed [ACC_W-1:0]              accumulator,
    input  prism_pkg::prism_wire_format_e        input_format,
    input  logic                                 saw_nan,
    input  logic                                 saw_positive_infinity,
    input  logic                                 saw_negative_infinity,
    input  logic                                 saw_finite_nonzero,
    input  logic                                 saw_zero,
    input  logic                                 all_zero_negative,
    output logic [31:0]                          fp32_bits,
    output logic                                 overflow,
    output logic                                 underflow,
    output logic                                 inexact
);

  import prism_pkg::*;

  logic sign;
  logic [ACC_W-1:0] magnitude;
  integer most_significant_bit;
  integer unit_exponent;
  integer unbiased_exponent;
  integer shift_amount;
  integer subnormal_shift;
  logic [24:0] rounded_significand;
  logic [23:0] significand;
  logic guard_bit;
  logic sticky_bit;
  logic increment;
  logic [24:0] subnormal_fraction;

  initial begin
    if ((ACC_W < 8) || (ACC_W > 320)) begin
      $fatal(1, "prism_kulisch_to_fp32 ACC_W must be in 8..320");
    end
  end

  always_comb begin
    sign = accumulator[ACC_W-1];
    magnitude = sign ? (~accumulator + 1'b1) : accumulator;
    most_significant_bit = -1;
    for (int index = 0; index < ACC_W; index++) begin
      if (magnitude[index]) most_significant_bit = index;
    end
    case (input_format)
      PRISM_FORMAT_INT8: unit_exponent = 0;
      PRISM_FORMAT_FP16: unit_exponent = -24;
      PRISM_FORMAT_BF16: unit_exponent = -133;
      default: unit_exponent = -149;
    endcase

    fp32_bits = '0;
    overflow = 1'b0;
    underflow = 1'b0;
    inexact = 1'b0;
    unbiased_exponent = most_significant_bit + unit_exponent;
    shift_amount = 0;
    subnormal_shift = 0;
    significand = '0;
    rounded_significand = '0;
    guard_bit = 1'b0;
    sticky_bit = 1'b0;
    increment = 1'b0;
    subnormal_fraction = '0;

    if (saw_nan || (saw_positive_infinity && saw_negative_infinity)) begin
      fp32_bits = 32'h7FC0_0000;
    end else if (saw_positive_infinity || saw_negative_infinity) begin
      fp32_bits = {saw_negative_infinity, 8'hFF, 23'b0};
    end else if (most_significant_bit < 0) begin
      fp32_bits = {(saw_zero && !saw_finite_nonzero && all_zero_negative), 31'b0};
    end else if (unbiased_exponent > 127) begin
      fp32_bits = {sign, 8'hFF, 23'b0};
      overflow = 1'b1;
      inexact = 1'b1;
    end else if (unbiased_exponent >= -126) begin
      if (most_significant_bit > 23) begin
        shift_amount = most_significant_bit - 23;
        significand = 24'(magnitude >> shift_amount);
        guard_bit = magnitude[shift_amount-1];
        for (int index = 0; index < ACC_W; index++) begin
          if (index < shift_amount-1) sticky_bit |= magnitude[index];
        end
      end else begin
        significand = 24'(magnitude << (23 - most_significant_bit));
      end
      increment = guard_bit && (sticky_bit || significand[0]);
      rounded_significand = {1'b0, significand} + {24'b0, increment};
      inexact = guard_bit || sticky_bit;
      if (rounded_significand[24]) begin
        rounded_significand = rounded_significand >> 1;
        unbiased_exponent = unbiased_exponent + 1;
      end
      if (unbiased_exponent > 127) begin
        fp32_bits = {sign, 8'hFF, 23'b0};
        overflow = 1'b1;
        inexact = 1'b1;
      end else begin
        fp32_bits = {sign, 8'(unbiased_exponent + 127), rounded_significand[22:0]};
      end
    end else begin
      subnormal_shift = unit_exponent + 149;
      if (subnormal_shift >= 0) begin
        if (subnormal_shift >= 25) begin
          subnormal_fraction = '0;
        end else begin
          subnormal_fraction = 25'(magnitude) << subnormal_shift;
        end
      end else begin
        shift_amount = -subnormal_shift;
        subnormal_fraction = 25'(magnitude >> shift_amount);
        if (shift_amount > 0) begin
          guard_bit = magnitude[shift_amount-1];
          for (int index = 0; index < ACC_W; index++) begin
            if (index < shift_amount-1) sticky_bit |= magnitude[index];
          end
        end
        increment = guard_bit && (sticky_bit || subnormal_fraction[0]);
        subnormal_fraction = subnormal_fraction + {24'b0, increment};
        inexact = guard_bit || sticky_bit;
      end
      underflow = inexact;
      if (subnormal_fraction[23]) begin
        fp32_bits = {sign, 8'h01, 23'b0};
      end else begin
        fp32_bits = {sign, 8'h00, subnormal_fraction[22:0]};
      end
    end
  end

endmodule
