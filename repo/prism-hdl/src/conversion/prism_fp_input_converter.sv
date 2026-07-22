//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp_input_converter.sv
// Module: prism_fp_input_converter
// Description: Converts typed input lanes to the binary32 backend representation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp_input_converter #(
    parameter int unsigned LANES = 16
) (
    input  logic                     clk,
    input  logic                     rst_n,
    input  logic [LANES*32-1:0]      s_element_bits,
    input  logic [LANES-1:0]         s_element_keep,
    input  prism_pkg::prism_wire_format_e s_format,
    input  logic                     s_valid,
    output logic                     s_ready,
    output logic [LANES*32-1:0]      m_fp32_bits,
    output logic [LANES-1:0]         m_element_keep,
    output logic                     m_valid,
    input  logic                     m_ready,
    output logic                     m_format_error
);

  import prism_pkg::*;

  logic [LANES*32-1:0] converted_bits;
  logic converted_error;
  logic [LANES*32-1:0] int8_bits;
  logic [LANES*32-1:0] fp16_bits;
  logic [LANES*32-1:0] bf16_bits;
  logic [LANES*32-1:0] fp32_bits;

  for (genvar lane = 0; lane < LANES; lane++) begin : g_scalar_converters
    prism_int8_to_fp32 u_int8_to_fp32 (
        .input_bits  (s_element_bits[lane*32 +: 8]),
        .output_bits (int8_bits[lane*32 +: 32])
    );

    prism_fp16_to_fp32 u_fp16_to_fp32 (
        .input_bits  (s_element_bits[lane*32 +: 16]),
        .output_bits (fp16_bits[lane*32 +: 32])
    );

    prism_bf16_to_fp32 u_bf16_to_fp32 (
        .input_bits  (s_element_bits[lane*32 +: 16]),
        .output_bits (bf16_bits[lane*32 +: 32])
    );

    prism_fp32_canonicalize u_fp32_canonicalize (
        .input_bits  (s_element_bits[lane*32 +: 32]),
        .output_bits (fp32_bits[lane*32 +: 32])
    );
  end

  always_comb begin
    converted_bits = '0;
    converted_error = 1'b0;
    case (s_format)
      PRISM_FORMAT_INT8: converted_bits = int8_bits;
      PRISM_FORMAT_FP16: converted_bits = fp16_bits;
      PRISM_FORMAT_BF16: converted_bits = bf16_bits;
      PRISM_FORMAT_FP32: converted_bits = fp32_bits;
      default: converted_error = 1'b1;
    endcase
  end

  assign s_ready = !m_valid || m_ready;

  initial begin
    if (LANES == 0) begin
      $fatal(1, "prism_fp_input_converter LANES must be positive");
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_fp32_bits <= '0;
      m_element_keep <= '0;
      m_valid <= 1'b0;
      m_format_error <= 1'b0;
    end else if (s_ready) begin
      m_valid <= s_valid;
      if (s_valid) begin
        m_fp32_bits <= converted_bits;
        m_element_keep <= s_element_keep;
        m_format_error <= converted_error;
      end
    end
  end

endmodule
