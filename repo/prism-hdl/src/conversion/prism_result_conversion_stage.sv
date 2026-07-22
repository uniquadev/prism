//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_result_conversion_stage.sv
// Module: prism_result_conversion_stage
// Description: Converts reduced FP32 lanes to the configured result wire format.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_result_conversion_stage #(
    parameter int unsigned LANES = 16
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_tile_meta_t           s_meta,
    input  logic [LANES*32-1:0]                   s_fp32_bits,
    input  logic [LANES-1:0]                      s_element_keep,
    input  logic                                  s_accumulation_inexact,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output prism_pkg::prism_tile_meta_t           m_meta,
    output logic [LANES*32-1:0]                   m_element_bits,
    output logic [LANES-1:0]                      m_element_keep,
    output logic                                  m_accumulation_inexact,
    output logic [LANES-1:0]                      m_overflow,
    output logic [LANES-1:0]                      m_underflow,
    output logic [LANES-1:0]                      m_inexact,
    output logic                                  m_format_error,
    output logic                                  m_valid,
    input  logic                                  m_ready
);

  import prism_pkg::*;

  prism_tile_meta_t meta_reg;
  logic warning_reg;
  logic metadata_valid;
  logic converter_ready;
  logic converter_valid;
  logic [LANES-1:0] unused_nan;

  assign s_ready = converter_ready && (!metadata_valid || (m_valid && m_ready));
  assign m_meta = meta_reg;
  assign m_accumulation_inexact = warning_reg;
  assign m_valid = metadata_valid && converter_valid;

  prism_fp_output_converter #(
      .LANES(LANES)
  ) u_output_converter (
      .clk(clk),
      .rst_n(rst_n),
      .s_fp32_bits(s_fp32_bits),
      .s_element_keep(s_element_keep),
      .s_format(prism_wire_format_e'(s_meta.output_format)),
      .s_valid(s_valid && s_ready),
      .s_ready(converter_ready),
      .m_element_bits(m_element_bits),
      .m_element_keep(m_element_keep),
      .m_overflow(m_overflow),
      .m_underflow(m_underflow),
      .m_inexact(m_inexact),
      .m_canonical_nan(unused_nan),
      .m_format_error(m_format_error),
      .m_valid(converter_valid),
      .m_ready(m_ready && metadata_valid)
  );

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      meta_reg <= '0;
      warning_reg <= 1'b0;
      metadata_valid <= 1'b0;
    end else begin
      if (m_valid && m_ready) metadata_valid <= 1'b0;
      if (s_valid && s_ready) begin
        meta_reg <= s_meta;
        warning_reg <= s_accumulation_inexact;
        metadata_valid <= 1'b1;
      end
    end
  end

endmodule
