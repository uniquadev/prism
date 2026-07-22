//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp_output_converter.sv
// Module: prism_fp_output_converter
// Description: Converts binary32 result lanes to FP16, BF16, or FP32 wire elements.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp_output_converter #(
    parameter int unsigned LANES = 16
) (
    input  logic                               clk,
    input  logic                               rst_n,
    input  logic [LANES*32-1:0]                s_fp32_bits,
    input  logic [LANES-1:0]                   s_element_keep,
    input  prism_pkg::prism_wire_format_e      s_format,
    input  logic                               s_valid,
    output logic                               s_ready,
    output logic [LANES*32-1:0]                m_element_bits,
    output logic [LANES-1:0]                   m_element_keep,
    output logic [LANES-1:0]                   m_overflow,
    output logic [LANES-1:0]                   m_underflow,
    output logic [LANES-1:0]                   m_inexact,
    output logic [LANES-1:0]                   m_canonical_nan,
    output logic                               m_format_error,
    output logic                               m_valid,
    input  logic                               m_ready
);

  import prism_pkg::*;

  logic [LANES*16-1:0] fp16_bits;
  logic [LANES*16-1:0] bf16_bits;
  logic [LANES*32-1:0] canonical_fp32_bits;
  logic [LANES-1:0] fp16_overflow, fp16_underflow, fp16_inexact, fp16_nan;
  logic [LANES-1:0] bf16_overflow, bf16_underflow, bf16_inexact, bf16_nan;
  logic [LANES*32-1:0] element_bits_comb;
  logic [LANES-1:0] overflow_comb, underflow_comb, inexact_comb, nan_comb;
  logic format_error_comb;

  for (genvar lane = 0; lane < LANES; lane++) begin : g_output_converters
    prism_fp32_to_fp16 u_fp16 (
        .input_bits(s_fp32_bits[lane*32 +: 32]),
        .output_bits(fp16_bits[lane*16 +: 16]),
        .overflow(fp16_overflow[lane]),
        .underflow(fp16_underflow[lane]),
        .inexact(fp16_inexact[lane]),
        .canonical_nan(fp16_nan[lane])
    );
    prism_fp32_to_bf16 u_bf16 (
        .input_bits(s_fp32_bits[lane*32 +: 32]),
        .output_bits(bf16_bits[lane*16 +: 16]),
        .overflow(bf16_overflow[lane]),
        .underflow(bf16_underflow[lane]),
        .inexact(bf16_inexact[lane]),
        .canonical_nan(bf16_nan[lane])
    );
    prism_fp32_canonicalize u_fp32 (
        .input_bits(s_fp32_bits[lane*32 +: 32]),
        .output_bits(canonical_fp32_bits[lane*32 +: 32])
    );
  end

  always_comb begin
    element_bits_comb = '0;
    overflow_comb = '0;
    underflow_comb = '0;
    inexact_comb = '0;
    nan_comb = '0;
    format_error_comb = 1'b0;
    case (s_format)
      PRISM_FORMAT_FP16: begin
        for (int unsigned lane = 0; lane < LANES; lane++) begin
          element_bits_comb[lane*32 +: 16] = fp16_bits[lane*16 +: 16];
        end
        overflow_comb = fp16_overflow; underflow_comb = fp16_underflow;
        inexact_comb = fp16_inexact; nan_comb = fp16_nan;
      end
      PRISM_FORMAT_BF16: begin
        for (int unsigned lane = 0; lane < LANES; lane++) begin
          element_bits_comb[lane*32 +: 16] = bf16_bits[lane*16 +: 16];
        end
        overflow_comb = bf16_overflow; underflow_comb = bf16_underflow;
        inexact_comb = bf16_inexact; nan_comb = bf16_nan;
      end
      PRISM_FORMAT_FP32: begin
        element_bits_comb = canonical_fp32_bits;
        for (int unsigned lane = 0; lane < LANES; lane++) begin
          nan_comb[lane] = (s_fp32_bits[lane*32 + 23 +: 8] == 8'hFF)
              && (s_fp32_bits[lane*32 +: 23] != 0);
        end
      end
      default: format_error_comb = 1'b1;
    endcase
  end

  assign s_ready = !m_valid || m_ready;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_element_bits <= '0;
      m_element_keep <= '0;
      m_overflow <= '0;
      m_underflow <= '0;
      m_inexact <= '0;
      m_canonical_nan <= '0;
      m_format_error <= 1'b0;
      m_valid <= 1'b0;
    end else if (s_ready) begin
      m_valid <= s_valid;
      if (s_valid) begin
        m_element_bits <= element_bits_comb;
        m_element_keep <= s_element_keep;
        m_overflow <= overflow_comb;
        m_underflow <= underflow_comb;
        m_inexact <= inexact_comb;
        m_canonical_nan <= nan_comb;
        m_format_error <= format_error_comb;
      end
    end
  end

endmodule
