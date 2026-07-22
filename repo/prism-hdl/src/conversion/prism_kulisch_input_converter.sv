//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_input_converter.sv
// Module: prism_kulisch_input_converter
// Description: Converts typed lanes to aligned signed deposits and special-value flags.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_input_converter #(
    parameter int unsigned ACC_W = 288,
    parameter int unsigned LANES = 16
) (
    input  logic                               clk,
    input  logic                               rst_n,
    input  logic [LANES*32-1:0]                s_element_bits,
    input  logic [LANES-1:0]                   s_element_keep,
    input  prism_pkg::prism_wire_format_e      s_format,
    input  logic                               s_valid,
    output logic                               s_ready,
    output logic signed [LANES*ACC_W-1:0]      m_deposits,
    output logic [LANES-1:0]                   m_element_keep,
    output logic [LANES-1:0]                   m_finite,
    output logic [LANES-1:0]                   m_zero,
    output logic [LANES-1:0]                   m_zero_sign,
    output logic [LANES-1:0]                   m_nan,
    output logic [LANES-1:0]                   m_positive_infinity,
    output logic [LANES-1:0]                   m_negative_infinity,
    output logic [LANES-1:0]                   m_overflow,
    output logic                               m_format_error,
    output logic                               m_valid,
    input  logic                               m_ready
);

  import prism_pkg::*;

  logic signed [LANES*ACC_W-1:0] int8_deposits;
  logic signed [LANES*ACC_W-1:0] fp16_deposits;
  logic signed [LANES*ACC_W-1:0] bf16_deposits;
  logic signed [LANES*ACC_W-1:0] fp32_deposits;
  logic [LANES-1:0] int8_finite, int8_zero, int8_zero_sign, int8_nan;
  logic [LANES-1:0] int8_pos_inf, int8_neg_inf, int8_overflow;
  logic [LANES-1:0] fp16_finite, fp16_zero, fp16_zero_sign, fp16_nan;
  logic [LANES-1:0] fp16_pos_inf, fp16_neg_inf, fp16_overflow;
  logic [LANES-1:0] bf16_finite, bf16_zero, bf16_zero_sign, bf16_nan;
  logic [LANES-1:0] bf16_pos_inf, bf16_neg_inf, bf16_overflow;
  logic [LANES-1:0] fp32_finite, fp32_zero, fp32_zero_sign, fp32_nan;
  logic [LANES-1:0] fp32_pos_inf, fp32_neg_inf, fp32_overflow;

  logic signed [LANES*ACC_W-1:0] deposits_comb;
  logic [LANES-1:0] finite_comb, zero_comb, zero_sign_comb, nan_comb;
  logic [LANES-1:0] pos_inf_comb, neg_inf_comb, overflow_comb;
  logic format_error_comb;

  for (genvar lane = 0; lane < LANES; lane++) begin : g_deposit_converters
    prism_int8_to_kulisch #(
        .ACC_W(ACC_W)
    ) u_int8 (
        .input_bits(s_element_bits[lane*32 +: 8]),
        .deposit(int8_deposits[lane*ACC_W +: ACC_W]),
        .finite(int8_finite[lane]),
        .zero(int8_zero[lane]),
        .zero_sign(int8_zero_sign[lane]),
        .nan(int8_nan[lane]),
        .positive_infinity(int8_pos_inf[lane]),
        .negative_infinity(int8_neg_inf[lane]),
        .overflow(int8_overflow[lane])
    );
    prism_fp16_to_kulisch #(
        .ACC_W(ACC_W)
    ) u_fp16 (
        .input_bits(s_element_bits[lane*32 +: 16]),
        .deposit(fp16_deposits[lane*ACC_W +: ACC_W]),
        .finite(fp16_finite[lane]),
        .zero(fp16_zero[lane]),
        .zero_sign(fp16_zero_sign[lane]),
        .nan(fp16_nan[lane]),
        .positive_infinity(fp16_pos_inf[lane]),
        .negative_infinity(fp16_neg_inf[lane]),
        .overflow(fp16_overflow[lane])
    );
    prism_bf16_to_kulisch #(
        .ACC_W(ACC_W)
    ) u_bf16 (
        .input_bits(s_element_bits[lane*32 +: 16]),
        .deposit(bf16_deposits[lane*ACC_W +: ACC_W]),
        .finite(bf16_finite[lane]),
        .zero(bf16_zero[lane]),
        .zero_sign(bf16_zero_sign[lane]),
        .nan(bf16_nan[lane]),
        .positive_infinity(bf16_pos_inf[lane]),
        .negative_infinity(bf16_neg_inf[lane]),
        .overflow(bf16_overflow[lane])
    );
    prism_fp32_to_kulisch #(
        .ACC_W(ACC_W)
    ) u_fp32 (
        .input_bits(s_element_bits[lane*32 +: 32]),
        .deposit(fp32_deposits[lane*ACC_W +: ACC_W]),
        .finite(fp32_finite[lane]),
        .zero(fp32_zero[lane]),
        .zero_sign(fp32_zero_sign[lane]),
        .nan(fp32_nan[lane]),
        .positive_infinity(fp32_pos_inf[lane]),
        .negative_infinity(fp32_neg_inf[lane]),
        .overflow(fp32_overflow[lane])
    );
  end

  always_comb begin
    deposits_comb = '0;
    finite_comb = '0;
    zero_comb = '0;
    zero_sign_comb = '0;
    nan_comb = '0;
    pos_inf_comb = '0;
    neg_inf_comb = '0;
    overflow_comb = '0;
    format_error_comb = 1'b0;
    case (s_format)
      PRISM_FORMAT_INT8: begin
        deposits_comb = int8_deposits; finite_comb = int8_finite; zero_comb = int8_zero;
        zero_sign_comb = int8_zero_sign; nan_comb = int8_nan; pos_inf_comb = int8_pos_inf;
        neg_inf_comb = int8_neg_inf; overflow_comb = int8_overflow;
      end
      PRISM_FORMAT_FP16: begin
        deposits_comb = fp16_deposits; finite_comb = fp16_finite; zero_comb = fp16_zero;
        zero_sign_comb = fp16_zero_sign; nan_comb = fp16_nan; pos_inf_comb = fp16_pos_inf;
        neg_inf_comb = fp16_neg_inf; overflow_comb = fp16_overflow;
      end
      PRISM_FORMAT_BF16: begin
        deposits_comb = bf16_deposits; finite_comb = bf16_finite; zero_comb = bf16_zero;
        zero_sign_comb = bf16_zero_sign; nan_comb = bf16_nan; pos_inf_comb = bf16_pos_inf;
        neg_inf_comb = bf16_neg_inf; overflow_comb = bf16_overflow;
      end
      PRISM_FORMAT_FP32: begin
        deposits_comb = fp32_deposits; finite_comb = fp32_finite; zero_comb = fp32_zero;
        zero_sign_comb = fp32_zero_sign; nan_comb = fp32_nan; pos_inf_comb = fp32_pos_inf;
        neg_inf_comb = fp32_neg_inf; overflow_comb = fp32_overflow;
      end
      default: format_error_comb = 1'b1;
    endcase
  end

  assign s_ready = !m_valid || m_ready;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_deposits <= '0;
      m_element_keep <= '0;
      m_finite <= '0;
      m_zero <= '0;
      m_zero_sign <= '0;
      m_nan <= '0;
      m_positive_infinity <= '0;
      m_negative_infinity <= '0;
      m_overflow <= '0;
      m_format_error <= 1'b0;
      m_valid <= 1'b0;
    end else if (s_ready) begin
      m_valid <= s_valid;
      if (s_valid) begin
        m_deposits <= deposits_comb;
        m_element_keep <= s_element_keep;
        m_finite <= finite_comb;
        m_zero <= zero_comb;
        m_zero_sign <= zero_sign_comb;
        m_nan <= nan_comb;
        m_positive_infinity <= pos_inf_comb;
        m_negative_infinity <= neg_inf_comb;
        m_overflow <= overflow_comb;
        m_format_error <= format_error_comb;
      end
    end
  end

endmodule
