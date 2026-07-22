//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_input_conversion_stage.sv
// Module: prism_input_conversion_stage
// Description: Selects the FP32 or compiled Kulisch conversion bank for one tile.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_input_conversion_stage #(
    parameter int unsigned LANES = 16,
    parameter int unsigned WIDTH_COUNT = 3,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_tile_meta_t           s_meta,
    input  logic [LANES*32-1:0]                   s_element_bits,
    input  logic [LANES-1:0]                      s_element_keep,
    input  logic [1:0]                            s_width_index,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output prism_pkg::prism_tile_meta_t           m_meta,
    output logic [LANES*32-1:0]                   m_fp32_bits,
    output logic signed [LANES*WIDTH_2-1:0]       m_kulisch_deposits,
    output logic [LANES-1:0]                      m_element_keep,
    output logic [LANES-1:0]                      m_finite,
    output logic [LANES-1:0]                      m_zero,
    output logic [LANES-1:0]                      m_zero_sign,
    output logic [LANES-1:0]                      m_nan,
    output logic [LANES-1:0]                      m_positive_infinity,
    output logic [LANES-1:0]                      m_negative_infinity,
    output logic [LANES-1:0]                      m_deposit_overflow,
    output logic                                  m_format_error,
    output logic [1:0]                            m_width_index,
    output logic                                  m_valid,
    input  logic                                  m_ready
);

  import prism_pkg::*;

  prism_tile_meta_t meta_reg;
  logic [1:0] width_index_reg;
  logic meta_valid;
  logic input_select_fp;
  logic current_select_fp;
  logic pipeline_advance;

  logic fp_ready, fp_valid, fp_error;
  logic [LANES*32-1:0] fp_bits;
  logic [LANES-1:0] fp_keep;

  logic k0_ready, k0_valid, k0_error;
  logic signed [LANES*WIDTH_0-1:0] k0_deposits;
  logic [LANES-1:0] k0_keep, k0_finite, k0_zero, k0_zero_sign, k0_nan;
  logic [LANES-1:0] k0_pos_inf, k0_neg_inf, k0_overflow;
  logic k1_ready, k1_valid, k1_error;
  logic signed [LANES*WIDTH_1-1:0] k1_deposits;
  logic [LANES-1:0] k1_keep, k1_finite, k1_zero, k1_zero_sign, k1_nan;
  logic [LANES-1:0] k1_pos_inf, k1_neg_inf, k1_overflow;
  logic k2_ready, k2_valid, k2_error;
  logic signed [LANES*WIDTH_2-1:0] k2_deposits;
  logic [LANES-1:0] k2_keep, k2_finite, k2_zero, k2_zero_sign, k2_nan;
  logic [LANES-1:0] k2_pos_inf, k2_neg_inf, k2_overflow;

  initial begin
    if ((LANES < 1) || (WIDTH_COUNT < 1) || (WIDTH_COUNT > 3)
        || (WIDTH_0 < 8) || (WIDTH_1 < WIDTH_0) || (WIDTH_2 < WIDTH_1)) begin
      $fatal(1, "prism_input_conversion_stage parameters are illegal");
    end
  end

  assign input_select_fp = s_meta.accumulator_profile != PRISM_ACC_KULISCH_FP32;
  assign current_select_fp = meta_reg.accumulator_profile != PRISM_ACC_KULISCH_FP32;
  assign pipeline_advance = !meta_valid || (m_valid && m_ready);
  // Readiness is deliberately independent of the unregistered input metadata.
  // The upstream arbiter may use ready while choosing a tile; feeding the chosen
  // format back into ready would create a combinational selection loop.  Each
  // converter is a one-entry registered boundary, and only the selected converter
  // receives valid, so all compiled converter inputs can advance together.
  assign s_ready = pipeline_advance && fp_ready && k0_ready
      && ((WIDTH_COUNT < 2) || k1_ready)
      && ((WIDTH_COUNT < 3) || k2_ready);
  always_comb begin
    if (current_select_fp) begin
      m_valid = meta_valid && fp_valid;
    end else begin
      case (width_index_reg)
        2'd0: m_valid = meta_valid && k0_valid;
        2'd1: m_valid = meta_valid && (WIDTH_COUNT > 1) && k1_valid;
        2'd2: m_valid = meta_valid && (WIDTH_COUNT > 2) && k2_valid;
        default: m_valid = 1'b0;
      endcase
    end
  end
  assign m_meta = meta_reg;
  assign m_fp32_bits = fp_bits;
  assign m_width_index = width_index_reg;

  // ---------------------------------------------------------------------------
  // FP32-path conversion bank
  // ---------------------------------------------------------------------------

  prism_fp_input_converter #(
      .LANES(LANES)
  ) u_fp_converter (
      .clk(clk),
      .rst_n(rst_n),
      .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep),
      .s_format(prism_wire_format_e'(s_meta.input_format)),
      .s_valid(s_valid && s_ready && input_select_fp),
      .s_ready(fp_ready),
      .m_fp32_bits(fp_bits),
      .m_element_keep(fp_keep),
      .m_valid(fp_valid),
      .m_ready(m_ready && meta_valid && current_select_fp),
      .m_format_error(fp_error)
  );

  // ---------------------------------------------------------------------------
  // Compiled Kulisch-width conversion banks
  // ---------------------------------------------------------------------------

  prism_kulisch_input_converter #(
      .ACC_W(WIDTH_0),
      .LANES(LANES)
  ) u_kulisch_0 (
      .clk(clk),
      .rst_n(rst_n),
      .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep),
      .s_format(prism_wire_format_e'(s_meta.input_format)),
      .s_valid(s_valid && s_ready && !input_select_fp && (s_width_index == 0)),
      .s_ready(k0_ready),
      .m_deposits(k0_deposits),
      .m_element_keep(k0_keep),
      .m_finite(k0_finite),
      .m_zero(k0_zero),
      .m_zero_sign(k0_zero_sign),
      .m_nan(k0_nan),
      .m_positive_infinity(k0_pos_inf),
      .m_negative_infinity(k0_neg_inf),
      .m_overflow(k0_overflow),
      .m_format_error(k0_error),
      .m_valid(k0_valid),
      .m_ready(m_ready && meta_valid && !current_select_fp && (width_index_reg == 0))
  );

  generate if (WIDTH_COUNT > 1) begin : gen_width_1
    prism_kulisch_input_converter #(
        .ACC_W(WIDTH_1),
        .LANES(LANES)
    ) u_kulisch_1 (
      .clk(clk),
      .rst_n(rst_n),
      .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep),
      .s_format(prism_wire_format_e'(s_meta.input_format)),
      .s_valid(s_valid && s_ready && !input_select_fp && (s_width_index == 1)),
      .s_ready(k1_ready),
      .m_deposits(k1_deposits),
      .m_element_keep(k1_keep),
      .m_finite(k1_finite),
      .m_zero(k1_zero),
      .m_zero_sign(k1_zero_sign),
      .m_nan(k1_nan),
      .m_positive_infinity(k1_pos_inf),
      .m_negative_infinity(k1_neg_inf),
      .m_overflow(k1_overflow),
      .m_format_error(k1_error),
      .m_valid(k1_valid),
      .m_ready(m_ready && meta_valid && !current_select_fp && (width_index_reg == 1))
    );
  end else begin : gen_no_width_1
    assign k1_ready = 1'b0;
    assign k1_valid = 1'b0;
    assign k1_error = 1'b1;
    assign k1_deposits = '0;
    assign k1_keep = '0;
    assign k1_finite = '0;
    assign k1_zero = '0;
    assign k1_zero_sign = '0;
    assign k1_nan = '0;
    assign k1_pos_inf = '0;
    assign k1_neg_inf = '0;
    assign k1_overflow = '0;
  end endgenerate

  generate if (WIDTH_COUNT > 2) begin : gen_width_2
    prism_kulisch_input_converter #(
        .ACC_W(WIDTH_2),
        .LANES(LANES)
    ) u_kulisch_2 (
      .clk(clk),
      .rst_n(rst_n),
      .s_element_bits(s_element_bits),
      .s_element_keep(s_element_keep),
      .s_format(prism_wire_format_e'(s_meta.input_format)),
      .s_valid(s_valid && s_ready && !input_select_fp && (s_width_index == 2)),
      .s_ready(k2_ready),
      .m_deposits(k2_deposits),
      .m_element_keep(k2_keep),
      .m_finite(k2_finite),
      .m_zero(k2_zero),
      .m_zero_sign(k2_zero_sign),
      .m_nan(k2_nan),
      .m_positive_infinity(k2_pos_inf),
      .m_negative_infinity(k2_neg_inf),
      .m_overflow(k2_overflow),
      .m_format_error(k2_error),
      .m_valid(k2_valid),
      .m_ready(m_ready && meta_valid && !current_select_fp && (width_index_reg == 2))
    );
  end else begin : gen_no_width_2
    assign k2_ready = 1'b0;
    assign k2_valid = 1'b0;
    assign k2_error = 1'b1;
    assign k2_deposits = '0;
    assign k2_keep = '0;
    assign k2_finite = '0;
    assign k2_zero = '0;
    assign k2_zero_sign = '0;
    assign k2_nan = '0;
    assign k2_pos_inf = '0;
    assign k2_neg_inf = '0;
    assign k2_overflow = '0;
  end endgenerate

  always_comb begin
    m_kulisch_deposits = '0;
    m_element_keep = current_select_fp ? fp_keep : '0;
    m_finite = '0;
    m_zero = '0;
    m_zero_sign = '0;
    m_nan = '0;
    m_positive_infinity = '0;
    m_negative_infinity = '0;
    m_deposit_overflow = '0;
    m_format_error = current_select_fp ? fp_error : 1'b0;
    if (!current_select_fp) case (width_index_reg)
      2'd0: begin
        for (int unsigned lane = 0; lane < LANES; lane++) begin
          m_kulisch_deposits[lane*WIDTH_2 +: WIDTH_2] =
              {{(WIDTH_2-WIDTH_0){k0_deposits[lane*WIDTH_0 + WIDTH_0-1]}},
                  k0_deposits[lane*WIDTH_0 +: WIDTH_0]};
        end
        m_element_keep = k0_keep; m_finite = k0_finite; m_zero = k0_zero;
        m_zero_sign = k0_zero_sign; m_nan = k0_nan; m_positive_infinity = k0_pos_inf;
        m_negative_infinity = k0_neg_inf; m_deposit_overflow = k0_overflow;
        m_format_error = k0_error;
      end
      2'd1: begin
        for (int unsigned lane = 0; lane < LANES; lane++) begin
          m_kulisch_deposits[lane*WIDTH_2 +: WIDTH_2] =
              {{(WIDTH_2-WIDTH_1){k1_deposits[lane*WIDTH_1 + WIDTH_1-1]}},
                  k1_deposits[lane*WIDTH_1 +: WIDTH_1]};
        end
        m_element_keep = k1_keep; m_finite = k1_finite; m_zero = k1_zero;
        m_zero_sign = k1_zero_sign; m_nan = k1_nan; m_positive_infinity = k1_pos_inf;
        m_negative_infinity = k1_neg_inf; m_deposit_overflow = k1_overflow;
        m_format_error = k1_error;
      end
      default: begin
        m_kulisch_deposits = k2_deposits;
        m_element_keep = k2_keep; m_finite = k2_finite; m_zero = k2_zero;
        m_zero_sign = k2_zero_sign; m_nan = k2_nan; m_positive_infinity = k2_pos_inf;
        m_negative_infinity = k2_neg_inf; m_deposit_overflow = k2_overflow;
        m_format_error = k2_error;
      end
    endcase
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      meta_reg <= '0;
      width_index_reg <= '0;
      meta_valid <= 1'b0;
    end else begin
      if (m_valid && m_ready) meta_valid <= 1'b0;
      if (s_valid && s_ready) begin
        meta_reg <= s_meta;
        width_index_reg <= s_width_index;
        meta_valid <= 1'b1;
      end
    end
  end

endmodule
