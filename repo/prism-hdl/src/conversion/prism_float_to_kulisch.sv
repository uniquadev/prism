//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_float_to_kulisch.sv
// Module: prism_float_to_kulisch
// Description: Maps one FP16, BF16, or FP32 operand to a Kulisch deposit.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_float_to_kulisch #(
    parameter int unsigned ACC_W = 279
) (
    input  logic [31:0]                            input_bits,
    input  prism_pkg::prism_wire_format_e         input_format,
    output logic signed [ACC_W-1:0]               deposit,
    // The same value as a magnitude and a sign: deposit is magnitude_bits,
    // negated when negate is set. An adder that subtracts a negated operand
    // needs no separate negation.
    output logic [ACC_W-1:0]                      magnitude_bits,
    output logic                                  negate,
    output logic                                  finite,
    output logic                                  zero,
    output logic                                  zero_sign,
    output logic                                  nan,
    output logic                                  positive_infinity,
    output logic                                  negative_infinity,
    output logic                                  overflow,
    output logic                                  format_error
);

  import prism_pkg::*;

  // FP32 magnitudes span 277 fixed point bits. Keep one leading zero so the
  // same 278 bit container can be interpreted as a signed deposit.
  localparam int unsigned MAG_W = 278;

  logic sign;
  logic [7:0] exponent;
  logic [23:0] significand;
  logic [8:0] scale_shift;
  logic exponent_zero;
  logic exponent_all_ones;
  logic fraction_nonzero;
  logic format_supported;
  logic [MAG_W-1:0] magnitude;
  logic [MAG_W-1:0] positive_limit;
  logic [MAG_W-1:0] negative_limit;
  logic [ACC_W-1:0] representable_magnitude;
  logic [ACC_W-1:0] signed_magnitude;
  int unsigned shift_amount;

  initial begin
    if ((ACC_W < 8) || (ACC_W > 320)) begin
      $fatal(1, "prism_float_to_kulisch ACC_W must be in 8..320");
    end
  end

  always_comb begin
    sign = 1'b0;
    exponent = '0;
    significand = '0;
    scale_shift = '0;
    exponent_zero = 1'b1;
    exponent_all_ones = 1'b0;
    fraction_nonzero = 1'b0;
    format_supported = 1'b1;

    case (input_format)
      PRISM_FORMAT_FP16: begin
        sign = input_bits[15];
        exponent = {3'b0, input_bits[14:10]};
        exponent_zero = !(|input_bits[14:10]);
        exponent_all_ones = &input_bits[14:10];
        fraction_nonzero = |input_bits[9:0];
        significand = {13'b0, |input_bits[14:10], input_bits[9:0]};
        scale_shift = 9'd124 + 9'((|input_bits[14:10])
            ? input_bits[14:10] : 5'd1);
      end
      PRISM_FORMAT_BF16: begin
        sign = input_bits[15];
        exponent = input_bits[14:7];
        exponent_zero = !(|input_bits[14:7]);
        exponent_all_ones = &input_bits[14:7];
        fraction_nonzero = |input_bits[6:0];
        significand = {16'b0, |input_bits[14:7], input_bits[6:0]};
        scale_shift = 9'd15 + 9'((|input_bits[14:7])
            ? input_bits[14:7] : 8'd1);
      end
      PRISM_FORMAT_FP32: begin
        sign = input_bits[31];
        exponent = input_bits[30:23];
        exponent_zero = !(|input_bits[30:23]);
        exponent_all_ones = &input_bits[30:23];
        fraction_nonzero = |input_bits[22:0];
        significand = {|input_bits[30:23], input_bits[22:0]};
        scale_shift = (|input_bits[30:23])
            ? 9'(input_bits[30:23] - 8'd1) : 9'd0;
      end
      default: format_supported = 1'b0;
    endcase

    magnitude = '0;
    positive_limit = ({{(MAG_W-1){1'b0}}, 1'b1} << (ACC_W - 1)) - 1'b1;
    negative_limit = {{(MAG_W-1){1'b0}}, 1'b1} << (ACC_W - 1);
    representable_magnitude = '0;
    signed_magnitude = '0;
    shift_amount = 0;
    deposit = '0;
    magnitude_bits = '0;
    negate = 1'b0;
    finite = 1'b0;
    zero = 1'b0;
    zero_sign = 1'b0;
    nan = 1'b0;
    positive_infinity = 1'b0;
    negative_infinity = 1'b0;
    overflow = 1'b0;
    format_error = !format_supported;

    if (format_supported) begin
      if (exponent_all_ones) begin
        if (fraction_nonzero) begin
          nan = 1'b1;
        end else if (sign) begin
          negative_infinity = 1'b1;
        end else begin
          positive_infinity = 1'b1;
        end
      end else begin
        finite = 1'b1;
        if (exponent_zero && !fraction_nonzero) begin
          zero = 1'b1;
          zero_sign = sign;
        end else begin
          shift_amount = int'(scale_shift);
          magnitude = {{(MAG_W-24){1'b0}}, significand} << shift_amount;
          representable_magnitude = ACC_W'(magnitude);
          if (ACC_W >= MAG_W) begin
            overflow = 1'b0;
          end else begin
            overflow = sign ? (magnitude > negative_limit)
                            : (magnitude > positive_limit);
          end
          negate = sign;
          magnitude_bits = !overflow ? representable_magnitude
              : sign ? {1'b1, {(ACC_W-1){1'b0}}} : {1'b0, {(ACC_W-1){1'b1}}};
          if (overflow) begin
            deposit = sign ? {1'b1, {(ACC_W-1){1'b0}}}
                           : {1'b0, {(ACC_W-1){1'b1}}};
          end else begin
            signed_magnitude = sign
                ? (~representable_magnitude + ACC_W'(1))
                : representable_magnitude;
            deposit = signed_magnitude;
          end
        end
      end
    end
  end

endmodule
