//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_binary_float_to_kulisch.sv
// Module: prism_binary_float_to_kulisch
// Description: Maps one finite binary float to an aligned signed fixed-point deposit.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_binary_float_to_kulisch #(
    parameter int unsigned EXP_W = 8,
    parameter int unsigned FRAC_W = 23,
    parameter int unsigned ACC_W = 288
) (
    input  logic [EXP_W+FRAC_W:0] input_bits,
    output logic signed [ACC_W-1:0] deposit,
    output logic finite,
    output logic zero,
    output logic zero_sign,
    output logic nan,
    output logic positive_infinity,
    output logic negative_infinity,
    output logic overflow
);

  localparam int unsigned INPUT_W = 1 + EXP_W + FRAC_W;
  localparam int unsigned MAG_W = 321;

  logic sign;
  logic [EXP_W-1:0] exponent;
  logic [FRAC_W-1:0] fraction;
  logic [FRAC_W:0] significand;
  logic [MAG_W-1:0] magnitude;
  logic [MAG_W-1:0] positive_limit;
  logic [MAG_W-1:0] negative_limit;
  logic [ACC_W-1:0] signed_magnitude;
  int unsigned shift_amount;

  initial begin
    if ((EXP_W == 0) || (FRAC_W == 0)) begin
      $fatal(1, "prism_binary_float_to_kulisch exponent and fraction widths must be positive");
    end
    if ((ACC_W < 2) || (ACC_W > 320)) begin
      $fatal(1, "prism_binary_float_to_kulisch ACC_W must be in 2..320");
    end
  end

  always_comb begin
    sign = input_bits[INPUT_W-1];
    exponent = input_bits[FRAC_W +: EXP_W];
    fraction = input_bits[FRAC_W-1:0];
    significand = '0;
    magnitude = '0;
    positive_limit = ({{(MAG_W-1){1'b0}}, 1'b1} << (ACC_W - 1)) - 1'b1;
    negative_limit = {{(MAG_W-1){1'b0}}, 1'b1} << (ACC_W - 1);
    signed_magnitude = '0;
    shift_amount = 0;
    deposit = '0;
    finite = 1'b0;
    zero = 1'b0;
    zero_sign = 1'b0;
    nan = 1'b0;
    positive_infinity = 1'b0;
    negative_infinity = 1'b0;
    overflow = 1'b0;

    if (&exponent) begin
      if (fraction != 0) begin
        nan = 1'b1;
      end else if (sign) begin
        negative_infinity = 1'b1;
      end else begin
        positive_infinity = 1'b1;
      end
    end else begin
      finite = 1'b1;
      if ((exponent == 0) && (fraction == 0)) begin
        zero = 1'b1;
        zero_sign = sign;
      end else begin
        if (exponent == 0) begin
          significand = {1'b0, fraction};
          shift_amount = 0;
        end else begin
          significand = {1'b1, fraction};
          shift_amount = int'(exponent) - 1;
        end
        magnitude = {{(MAG_W-(FRAC_W+1)){1'b0}}, significand} << shift_amount;
        overflow = sign ? (magnitude > negative_limit) : (magnitude > positive_limit);
        if (overflow) begin
          deposit = sign ? {1'b1, {(ACC_W-1){1'b0}}} : {1'b0, {(ACC_W-1){1'b1}}};
        end else begin
          signed_magnitude = sign
              ? (~magnitude[ACC_W-1:0] + ACC_W'(1))
              : magnitude[ACC_W-1:0];
          deposit = signed_magnitude;
        end
      end
    end
  end

endmodule
