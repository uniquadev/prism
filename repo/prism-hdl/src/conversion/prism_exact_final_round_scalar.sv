//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_final_round_scalar.sv
// Module: prism_exact_final_round_scalar
// Description: One final RNE conversion from exact SUM to requested native format.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Seven registered steps without stalls: a value offered with s_valid leaves
// with m_valid seven cycles later. The caller bounds what it has in flight.
//
// The steps: magnitude; position of its highest bit; exponent and shift;
// truncation, guard and sticky; rounded significand; the comparisons the
// result depends on; the result.
module prism_exact_final_round_scalar #(
    parameter int unsigned KULISCH_W = 320
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         s_valid,
    input  logic                         s_mode_wide,
    input  logic [31:0]                  s_fp32_bits,
    input  logic [7:0]                   s_kulisch_tag,
    input  logic signed [KULISCH_W-1:0]  s_kulisch_integer,
    input  logic [7:0]                   s_output_format,
    output logic                         m_valid,
    output logic [7:0]                   m_format,
    output logic [31:0]                  m_bits,
    output logic                         m_error
);

  import prism_pkg::*;

  logic signed [KULISCH_W-1:0] native_integer, exact_integer;
  logic native_finite, native_zero, native_zero_sign, native_nan;
  logic native_positive_infinity, native_negative_infinity;
  logic native_overflow, native_format_error;
  logic [7:0] exact_tag;
  logic input_sign, stage_sign, stage_valid, round_sign, round_valid;
  logic [KULISCH_W-1:0] input_magnitude, stage_magnitude, round_magnitude;
  logic [7:0] stage_tag, stage_format, round_tag, round_format;
  logic stage_base_error, stage_special_error;
  // The magnitude with the position of its highest bit.
  logic locate_valid, locate_sign, locate_base_error, locate_special_error;
  logic [KULISCH_W-1:0] locate_magnitude;
  logic [7:0] locate_tag, locate_format;
  integer locate_highest;
  // Per format: the highest bit of the smallest normal value, and the shift
  // of every value below it.
  integer locate_normal_from, locate_subnormal_shift;
  integer format_exponent_bits, format_fraction_bits, format_bias;
  logic round_base_error, round_special_error;
  logic finish_valid, finish_sign, finish_zero;
  logic finish_base_error, finish_special_error;
  logic [7:0] finish_tag, finish_format, finish_int8_quotient;
  logic finish_int8_integral, finish_int8_range, finish_round_up;
  logic [24:0] finish_truncated;
  integer finish_exponent_bits, finish_fraction_bits, finish_bias;
  integer finish_maximum_exponent, finish_minimum_exponent, finish_exponent;
  // The rounded significand is registered before the result is put together.
  logic select_valid, select_sign, select_zero;
  logic select_base_error, select_special_error;
  logic [7:0] select_tag, select_format, select_int8_quotient;
  logic select_int8_integral, select_int8_range;
  logic [24:0] select_rounded;
  integer select_exponent_bits, select_fraction_bits, select_bias;
  integer select_maximum_exponent, select_minimum_exponent, select_exponent;
  // What the result depends on, compared before it is put together: whether
  // the exponent is above its range before and after a carry out of the
  // significand, whether the value is normal, whether the significand has
  // carried, and the exponent field for both cases.
  logic pack_valid, pack_sign, pack_zero;
  logic pack_base_error, pack_special_error;
  logic [7:0] pack_tag, pack_format, pack_int8_quotient;
  logic pack_int8_integral, pack_int8_range;
  logic [24:0] pack_rounded;
  logic pack_above, pack_above_after_carry, pack_normal;
  logic pack_carry, pack_subnormal_carry, pack_no_format;
  // The fields of the result, already at their place in the word: the sign
  // bit, the exponent of all ones, the smallest normal value, the exponent
  // for both cases, and the mask of the fraction.
  logic [31:0] pack_sign_bit, pack_infinity, pack_least_normal, pack_fraction_mask;
  logic [31:0] pack_field, pack_field_after_carry;
  logic [31:0] chosen_bits;
  logic chosen_error;
  integer highest;
  integer stage_exponent_bits, stage_fraction_bits, stage_bias;
  integer stage_maximum_exponent, stage_minimum_exponent;
  integer stage_exponent, stage_shift_amount;
  integer round_exponent_bits, round_fraction_bits, round_bias;
  integer round_maximum_exponent, round_minimum_exponent;
  integer round_exponent, round_shift_amount;
  localparam int unsigned STICKY_GROUPS = (KULISCH_W + 15) / 16;
  logic [24:0] truncated, rounded;
  logic [STICKY_GROUPS*16-1:0] magnitude_padded;
  logic [STICKY_GROUPS:0] sticky_prefix;
  logic [15:0] sticky_group_bits, sticky_group_mask;
  logic guard_bit, sticky_bit, round_up;
  integer sticky_group_index, sticky_bit_index;
  logic [31:0] sign_field, fraction_mask;
  logic [KULISCH_W-1:0] int8_quotient;

  initial begin
    if (KULISCH_W < 278 || KULISCH_W > 320)
      $fatal(1, "Exact final rounder requires an FP32-compatible Kulisch width");
  end

  prism_float_to_kulisch #(.ACC_W(KULISCH_W)) u_narrow_to_exact (
      .input_bits(s_fp32_bits), .input_format(PRISM_FORMAT_FP32),
      .deposit(native_integer), .magnitude_bits(), .negate(), .finite(native_finite),
      .zero(native_zero), .zero_sign(native_zero_sign), .nan(native_nan),
      .positive_infinity(native_positive_infinity),
      .negative_infinity(native_negative_infinity),
      .overflow(native_overflow), .format_error(native_format_error)
  );

  always_comb begin
    exact_integer = s_mode_wide ? s_kulisch_integer : native_integer;
    if (s_mode_wide) exact_tag = s_kulisch_tag;
    else if (native_nan) exact_tag = 8'd1;
    else if (native_positive_infinity) exact_tag = 8'd2;
    else if (native_negative_infinity) exact_tag = 8'd3;
    else if (native_zero) exact_tag = native_zero_sign ? 8'd5 : 8'd4;
    else exact_tag = 8'd0;

    input_sign = exact_integer[KULISCH_W-1];
    input_magnitude = input_sign ? -exact_integer : exact_integer;
  end

  always_comb begin
    highest = -1;
    for (integer bit_index = 0; bit_index < KULISCH_W; bit_index++) begin
      if (stage_magnitude[bit_index]) highest = bit_index;
    end
    stage_exponent_bits = 0;
    stage_fraction_bits = 0;
    stage_bias = 0;
    case (locate_format)
      PRISM_FORMAT_FP16: begin
        stage_exponent_bits = 5;
        stage_fraction_bits = 10;
        stage_bias = 15;
      end
      PRISM_FORMAT_BF16: begin
        stage_exponent_bits = 8;
        stage_fraction_bits = 7;
        stage_bias = 127;
      end
      PRISM_FORMAT_FP32: begin
        stage_exponent_bits = 8;
        stage_fraction_bits = 23;
        stage_bias = 127;
      end
      default: begin end
    endcase
    stage_maximum_exponent = (1 << stage_exponent_bits) - 2 - stage_bias;
    stage_minimum_exponent = 1 - stage_bias;
    stage_exponent = locate_highest - 149;
    stage_shift_amount = locate_highest >= locate_normal_from
        ? locate_highest - stage_fraction_bits
        : locate_subnormal_shift;
  end
  always_comb begin
    format_exponent_bits = 0;
    format_fraction_bits = 0;
    format_bias = 0;
    case (stage_format)
      PRISM_FORMAT_FP16: begin
        format_exponent_bits = 5;
        format_fraction_bits = 10;
        format_bias = 15;
      end
      PRISM_FORMAT_BF16: begin
        format_exponent_bits = 8;
        format_fraction_bits = 7;
        format_bias = 127;
      end
      PRISM_FORMAT_FP32: begin
        format_exponent_bits = 8;
        format_fraction_bits = 23;
        format_bias = 127;
      end
      default: begin end
    endcase
  end

  always_comb begin
    magnitude_padded = (STICKY_GROUPS*16)'(round_magnitude);
    sticky_prefix = '0;
    for (integer group_index = 0; group_index < STICKY_GROUPS; group_index++)
      sticky_prefix[group_index+1] = sticky_prefix[group_index]
          || |magnitude_padded[group_index*16 +: 16];
    sticky_group_bits = '0;
    sticky_group_mask = '0;
    sticky_group_index = 0;
    sticky_bit_index = 0;
    guard_bit = 1'b0;
    sticky_bit = 1'b0;
    round_up = 1'b0;
    int8_quotient = round_magnitude >> 149;
    truncated = 25'(round_magnitude >> round_shift_amount);
    if (round_shift_amount > 0) begin
      guard_bit = round_magnitude[round_shift_amount - 1];
      sticky_group_index = (round_shift_amount - 1) / 16;
      sticky_bit_index = (round_shift_amount - 1) % 16;
      sticky_group_bits = magnitude_padded[sticky_group_index*16 +: 16];
      sticky_group_mask = (16'd1 << sticky_bit_index) - 16'd1;
      sticky_bit = sticky_prefix[sticky_group_index]
          || |(sticky_group_bits & sticky_group_mask);
      round_up = guard_bit && (sticky_bit || truncated[0]);
    end
  end

  always_comb begin
    fraction_mask = pack_fraction_mask;
    sign_field = pack_sign ? pack_sign_bit : 32'd0;
    rounded = pack_rounded;
    chosen_bits = '0;
    chosen_error = pack_base_error || pack_special_error;

    if (pack_format == PRISM_FORMAT_INT8) begin
      if (pack_tag == 8'd4 || pack_tag == 8'd5) begin
        chosen_bits = '0;
      end else if (pack_tag == 8'd0 && !pack_zero
          && pack_int8_integral && pack_int8_range) begin
        chosen_bits = pack_sign ? (32'(-pack_int8_quotient) & 32'hff)
            : 32'(pack_int8_quotient);
      end else chosen_error = 1'b1;
    end else if (pack_no_format) begin
      chosen_error = 1'b1;
    end else begin
      case (pack_tag)
        8'd1: begin
          case (pack_format)
            PRISM_FORMAT_FP16: chosen_bits = 32'h0000_7e00;
            PRISM_FORMAT_BF16: chosen_bits = 32'h0000_7fc0;
            default: chosen_bits = 32'h7fc0_0000;
          endcase
        end
        8'd2, 8'd3: begin
          chosen_bits = (pack_tag == 8'd3 ? pack_sign_bit : 32'd0) | pack_infinity;
        end
        8'd4, 8'd5: begin
          chosen_bits = pack_tag == 8'd5 ? pack_sign_bit : 32'd0;
        end
        8'd0: begin
          if (pack_zero) chosen_error = 1'b1;
          else if (pack_above) begin
            chosen_bits = sign_field | pack_infinity;
          end else begin
            if (pack_normal) begin
              // A significand that has carried is halved and its exponent
              // is one higher.
              if (pack_carry) rounded = rounded >> 1;
              if (pack_carry && pack_above_after_carry)
                chosen_bits = sign_field | pack_infinity;
              else
                chosen_bits = sign_field
                    | (pack_carry ? pack_field_after_carry : pack_field)
                    | (32'(rounded) & fraction_mask);
            end else if (pack_subnormal_carry) begin
              chosen_bits = sign_field | pack_least_normal;
            end else begin
              chosen_bits = sign_field | (32'(rounded) & fraction_mask);
            end
          end
        end
        default: chosen_error = 1'b1;
      endcase
    end
  end

  // The valid flags are the only state with a reset; the values follow them
  // through registers without enables.
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      stage_valid <= 1'b0;
      locate_valid <= 1'b0;
      round_valid <= 1'b0;
      finish_valid <= 1'b0;
      select_valid <= 1'b0;
      pack_valid <= 1'b0;
      m_valid <= 1'b0;
    end else begin
      stage_valid <= s_valid;
      locate_valid <= stage_valid;
      round_valid <= locate_valid;
      finish_valid <= round_valid;
      select_valid <= finish_valid;
      pack_valid <= select_valid;
      m_valid <= pack_valid;
    end
  end
  always_ff @(posedge clk) begin
    stage_magnitude <= input_magnitude;
    stage_sign <= input_sign;
    stage_tag <= exact_tag;
    stage_format <= s_output_format;
    stage_base_error <= native_overflow || native_format_error;
    stage_special_error <= s_mode_wide && exact_tag != 0 && exact_integer != 0;

    locate_magnitude <= stage_magnitude;
    locate_sign <= stage_sign;
    locate_tag <= stage_tag;
    locate_format <= stage_format;
    locate_base_error <= stage_base_error;
    locate_special_error <= stage_special_error;
    locate_highest <= highest;
    locate_normal_from <= 149 + 1 - format_bias;
    locate_subnormal_shift <= 149 + 1 - format_bias - format_fraction_bits;

    round_magnitude <= locate_magnitude;
    round_sign <= locate_sign;
    round_tag <= locate_tag;
    round_format <= locate_format;
    round_base_error <= locate_base_error;
    round_special_error <= locate_special_error;
    round_exponent_bits <= stage_exponent_bits;
    round_fraction_bits <= stage_fraction_bits;
    round_bias <= stage_bias;
    round_maximum_exponent <= stage_maximum_exponent;
    round_minimum_exponent <= stage_minimum_exponent;
    round_exponent <= stage_exponent;
    round_shift_amount <= stage_shift_amount;

    finish_sign <= round_sign;
    finish_zero <= round_magnitude == 0;
    finish_tag <= round_tag;
    finish_format <= round_format;
    finish_base_error <= round_base_error;
    finish_special_error <= round_special_error;
    finish_int8_quotient <= int8_quotient[7:0];
    finish_int8_integral <= (round_magnitude & ((KULISCH_W'(1) << 149) - 1)) == 0;
    finish_int8_range <= round_sign ? int8_quotient <= 128 : int8_quotient <= 127;
    finish_truncated <= truncated;
    finish_round_up <= round_up;
    finish_exponent_bits <= round_exponent_bits;
    finish_fraction_bits <= round_fraction_bits;
    finish_bias <= round_bias;
    finish_maximum_exponent <= round_maximum_exponent;
    finish_minimum_exponent <= round_minimum_exponent;
    finish_exponent <= round_exponent;

    select_sign <= finish_sign;
    select_zero <= finish_zero;
    select_tag <= finish_tag;
    select_format <= finish_format;
    select_base_error <= finish_base_error;
    select_special_error <= finish_special_error;
    select_int8_quotient <= finish_int8_quotient;
    select_int8_integral <= finish_int8_integral;
    select_int8_range <= finish_int8_range;
    select_rounded <= finish_truncated + 25'(finish_round_up);
    select_exponent_bits <= finish_exponent_bits;
    select_fraction_bits <= finish_fraction_bits;
    select_bias <= finish_bias;
    select_maximum_exponent <= finish_maximum_exponent;
    select_minimum_exponent <= finish_minimum_exponent;
    select_exponent <= finish_exponent;

    pack_sign <= select_sign;
    pack_zero <= select_zero;
    pack_tag <= select_tag;
    pack_format <= select_format;
    pack_base_error <= select_base_error;
    pack_special_error <= select_special_error;
    pack_int8_quotient <= select_int8_quotient;
    pack_int8_integral <= select_int8_integral;
    pack_int8_range <= select_int8_range;
    pack_rounded <= select_rounded;
    pack_no_format <= select_exponent_bits == 0;
    pack_sign_bit <= 32'd1 << (select_exponent_bits + select_fraction_bits);
    pack_infinity <= ((32'd1 << select_exponent_bits) - 1) << select_fraction_bits;
    pack_least_normal <= 32'd1 << select_fraction_bits;
    pack_fraction_mask <= (32'd1 << select_fraction_bits) - 1;
    pack_above <= select_exponent > select_maximum_exponent;
    pack_above_after_carry <= select_exponent >= select_maximum_exponent;
    pack_normal <= select_exponent >= select_minimum_exponent;
    pack_carry <= select_rounded == (25'd1 << (select_fraction_bits + 1));
    pack_subnormal_carry <= select_rounded == (25'd1 << select_fraction_bits);
    pack_field <= 32'(select_exponent + select_bias) << select_fraction_bits;
    pack_field_after_carry <= 32'(select_exponent + 1 + select_bias) << select_fraction_bits;

    m_format <= pack_format;
    m_bits <= chosen_bits;
    m_error <= chosen_error;
  end

  wire unused_finite = native_finite;

endmodule
