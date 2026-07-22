//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_to_fp16.sv
// Module: prism_fp32_to_fp16
// Description: Narrows binary32 to binary16 with ties-to-even rounding and status.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_to_fp16 (
    input  logic [31:0] input_bits,
    output logic [15:0] output_bits,
    output logic overflow,
    output logic underflow,
    output logic inexact,
    output logic canonical_nan
);

  logic sign;
  logic [7:0] exponent32;
  logic [22:0] fraction32;
  logic [23:0] significand;
  logic [11:0] rounded_significand;
  logic [10:0] kept_significand;
  logic [12:0] normal_remainder;
  logic [63:0] wide_significand;
  logic [63:0] truncated;
  logic [63:0] remainder;
  logic [63:0] halfway;
  integer unbiased_exponent;
  integer shift_amount;
  integer half_exponent;
  logic increment;

  always_comb begin
    sign = input_bits[31];
    exponent32 = input_bits[30:23];
    fraction32 = input_bits[22:0];
    significand = {1'b1, fraction32};
    rounded_significand = '0;
    kept_significand = '0;
    normal_remainder = '0;
    wide_significand = {40'h0, significand};
    truncated = '0;
    remainder = '0;
    halfway = '0;
    unbiased_exponent = int'(exponent32) - 127;
    shift_amount = 0;
    half_exponent = 0;
    increment = 1'b0;
    output_bits = {sign, 15'h0000};
    overflow = 1'b0;
    underflow = 1'b0;
    inexact = 1'b0;
    canonical_nan = 1'b0;

    if (exponent32 == 8'hFF) begin
      if (fraction32 != 0) begin
        output_bits = 16'h7E00;
        canonical_nan = 1'b1;
      end else begin
        output_bits = {sign, 5'h1F, 10'h000};
      end
    end else if ((exponent32 == 0) && (fraction32 == 0)) begin
      output_bits = {sign, 15'h0000};
    end else if ((exponent32 == 0) || (unbiased_exponent < -25)) begin
      output_bits = {sign, 15'h0000};
      underflow = 1'b1;
      inexact = 1'b1;
    end else if (unbiased_exponent > 15) begin
      output_bits = {sign, 5'h1F, 10'h000};
      overflow = 1'b1;
      inexact = 1'b1;
    end else if (unbiased_exponent >= -14) begin
      half_exponent = unbiased_exponent + 15;
      kept_significand = significand[23:13];
      normal_remainder = significand[12:0];
      increment = (normal_remainder > 13'h1000)
          || ((normal_remainder == 13'h1000) && kept_significand[0]);
      rounded_significand = {1'b0, kept_significand} + {11'b0, increment};
      inexact = (normal_remainder != 0);
      if (rounded_significand[11]) begin
        half_exponent = half_exponent + 1;
        rounded_significand = rounded_significand >> 1;
      end
      if (half_exponent >= 31) begin
        output_bits = {sign, 5'h1F, 10'h000};
        overflow = 1'b1;
        inexact = 1'b1;
      end else begin
        output_bits = {sign, half_exponent[4:0], rounded_significand[9:0]};
      end
    end else begin
      shift_amount = -unbiased_exponent - 1;
      truncated = wide_significand >> shift_amount;
      halfway = 64'h1 << (shift_amount - 1);
      remainder = wide_significand & ((64'h1 << shift_amount) - 64'd1);
      increment = (remainder > halfway) || ((remainder == halfway) && truncated[0]);
      truncated = truncated + {63'b0, increment};
      inexact = (remainder != 0);
      underflow = inexact;
      if (truncated[10]) begin
        output_bits = {sign, 5'h01, 10'h000};
      end else begin
        output_bits = {sign, 5'h00, truncated[9:0]};
      end
    end
  end

endmodule
