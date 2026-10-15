//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_auto_wire_scalar.sv
// Module: prism_auto_wire_scalar
// Description: Lossless scalar Auto wire selection from an exact SUM state.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_auto_wire_scalar #(
    parameter int unsigned KULISCH_W = 279
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         s_valid,
    output logic                         s_ready,
    input  logic                         s_mode_wide,
    input  logic [31:0]                  s_fp32_bits,
    input  logic [7:0]                   s_kulisch_tag,
    input  logic signed [KULISCH_W-1:0]  s_kulisch_integer,
    output logic                         m_valid,
    input  logic                         m_ready,
    output logic [7:0]                   m_format,
    output logic [31:0]                  m_native_bits,
    output logic [31:0]                  m_fp32_bits,
    output logic                         m_fp32_exact,
    output logic [7:0]                   m_kulisch_tag,
    output logic signed [KULISCH_W-1:0]  m_kulisch_integer,
    output logic                         m_error
);

  import prism_pkg::*;

  localparam int unsigned BIT_INDEX_W = $clog2(KULISCH_W);
  localparam int unsigned BIT_LEAVES = 1 << BIT_INDEX_W;

  initial begin
    if (KULISCH_W < 278 || KULISCH_W > 320)
      $fatal(1, "Auto wire classifier requires an FP32-compatible Kulisch width");
  end

  // The selection takes four registered steps: the magnitude of the value,
  // the positions of its highest and lowest set bits, the bit fields each
  // native format would carry, and the choice among the candidates. Every
  // step keeps its own valid flag and load decision next to its data.
  (* dont_touch = "true" *) logic magnitude_valid, search_valid, extract_valid, choice_valid;
  (* dont_touch = "true" *) logic magnitude_load, search_load, extract_load, choice_load;
  logic magnitude_ready, search_ready, extract_ready, choice_ready;

  assign choice_ready = !choice_valid || m_ready;
  assign extract_ready = !extract_valid || choice_ready;
  assign search_ready = !search_valid || extract_ready;
  assign magnitude_ready = !magnitude_valid || search_ready;
  assign s_ready = magnitude_ready;
  assign m_valid = choice_valid;
  assign magnitude_load = s_valid && magnitude_ready;
  assign search_load = magnitude_valid && search_ready;
  assign extract_load = search_valid && extract_ready;
  assign choice_load = extract_valid && choice_ready;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      magnitude_valid <= 1'b0;
      search_valid <= 1'b0;
      extract_valid <= 1'b0;
      choice_valid <= 1'b0;
    end else begin
      if (magnitude_ready) magnitude_valid <= s_valid;
      if (search_ready) search_valid <= magnitude_valid;
      if (extract_ready) extract_valid <= search_valid;
      if (choice_ready) choice_valid <= extract_valid;
    end
  end

  // Step 1: select the exact value and take its magnitude.
  logic signed [KULISCH_W-1:0] native_integer;
  logic native_zero, native_zero_sign, native_nan;
  logic native_positive_infinity, native_negative_infinity;
  logic native_finite, native_overflow, native_format_error;
  logic signed [KULISCH_W-1:0] selected_integer;
  logic [7:0] selected_tag;

  prism_float_to_kulisch #(.ACC_W(KULISCH_W)) u_native_to_exact (
      .input_bits(s_fp32_bits),
      .input_format(PRISM_FORMAT_FP32),
      .deposit(native_integer), .magnitude_bits(), .negate(),
      .finite(native_finite),
      .zero(native_zero),
      .zero_sign(native_zero_sign),
      .nan(native_nan),
      .positive_infinity(native_positive_infinity),
      .negative_infinity(native_negative_infinity),
      .overflow(native_overflow),
      .format_error(native_format_error)
  );

  always_comb begin
    selected_integer = s_mode_wide ? s_kulisch_integer : native_integer;
    if (s_mode_wide) begin
      selected_tag = s_kulisch_tag;
    end else if (native_nan) begin
      selected_tag = 8'd1;
    end else if (native_positive_infinity) begin
      selected_tag = 8'd2;
    end else if (native_negative_infinity) begin
      selected_tag = 8'd3;
    end else if (native_zero) begin
      selected_tag = native_zero_sign ? 8'd5 : 8'd4;
    end else begin
      selected_tag = 8'd0;
    end
  end

  logic signed [KULISCH_W-1:0] magnitude_integer;
  logic [KULISCH_W-1:0] magnitude_bits;
  logic [7:0] magnitude_tag;
  logic magnitude_negative, magnitude_mode_wide, magnitude_native_error;
  always_ff @(posedge clk) begin
    if (magnitude_load) begin
      magnitude_integer <= selected_integer;
      magnitude_bits <= selected_integer[KULISCH_W-1] ? -selected_integer : selected_integer;
      magnitude_tag <= selected_tag;
      magnitude_negative <= selected_integer[KULISCH_W-1];
      magnitude_mode_wide <= s_mode_wide;
      magnitude_native_error <= native_overflow || native_format_error;
    end
  end

  // Step 2: balanced priority trees keep the search depth logarithmic. Zero
  // padding permits non-power-of-two widths without changing bit indices.
  logic [2*BIT_LEAVES-1:1] bit_present;
  logic [BIT_INDEX_W-1:0] highest_bit [1:2*BIT_LEAVES-1];
  logic [BIT_INDEX_W-1:0] lowest_bit [1:2*BIT_LEAVES-1];
  for (genvar bit_index = 0; bit_index < BIT_LEAVES; bit_index++) begin : gen_bit_leaf
    if (bit_index < KULISCH_W) begin : gen_present
      assign bit_present[BIT_LEAVES+bit_index] = magnitude_bits[bit_index];
    end else begin : gen_padding
      assign bit_present[BIT_LEAVES+bit_index] = 1'b0;
    end
    assign highest_bit[BIT_LEAVES+bit_index] = BIT_INDEX_W'(bit_index);
    assign lowest_bit[BIT_LEAVES+bit_index] = BIT_INDEX_W'(bit_index);
  end
  for (genvar node = 1; node < BIT_LEAVES; node++) begin : gen_bit_priority
    assign bit_present[node] = bit_present[2*node] | bit_present[2*node+1];
    assign highest_bit[node] = bit_present[2*node+1]
        ? highest_bit[2*node+1] : highest_bit[2*node];
    assign lowest_bit[node] = bit_present[2*node]
        ? lowest_bit[2*node] : lowest_bit[2*node+1];
  end

  logic signed [KULISCH_W-1:0] search_integer;
  logic [KULISCH_W-1:0] search_bits;
  logic [7:0] search_tag;
  logic search_negative, search_mode_wide, search_native_error, search_nonzero;
  logic [BIT_INDEX_W-1:0] search_highest, search_lowest;
  always_ff @(posedge clk) begin
    if (search_load) begin
      search_integer <= magnitude_integer;
      search_bits <= magnitude_bits;
      search_tag <= magnitude_tag;
      search_negative <= magnitude_negative;
      search_mode_wide <= magnitude_mode_wide;
      search_native_error <= magnitude_native_error;
      search_nonzero <= bit_present[1];
      search_highest <= highest_bit[1];
      search_lowest <= lowest_bit[1];
    end
  end

  // Step 3: one aligned 24-bit significand serves every normal native format.
  // Subnormal encodings use fixed slices of the magnitude.
  logic signed [KULISCH_W-1:0] extract_integer;
  logic [7:0] extract_tag;
  logic extract_negative, extract_mode_wide, extract_native_error, extract_nonzero;
  logic [BIT_INDEX_W-1:0] extract_highest, extract_lowest;
  logic [23:0] extract_significand;
  logic [7:0] extract_units;
  logic [9:0] extract_half_subnormal;
  logic [22:0] extract_low;
  always_ff @(posedge clk) begin
    if (extract_load) begin
      extract_integer <= search_integer;
      extract_tag <= search_tag;
      extract_negative <= search_negative;
      extract_mode_wide <= search_mode_wide;
      extract_native_error <= search_native_error;
      extract_nonzero <= search_nonzero;
      extract_highest <= search_highest;
      extract_lowest <= search_lowest;
      extract_significand <= search_nonzero && search_highest >= BIT_INDEX_W'(23)
          ? 24'(search_bits >> (search_highest - BIT_INDEX_W'(23))) : '0;
      extract_units <= search_bits[156:149];
      extract_half_subnormal <= search_bits[134:125];
      extract_low <= search_bits[22:0];
    end
  end

  // Step 4: build each candidate and choose the narrowest lossless format.
  integer highest, lowest;
  logic [32:0] int8_candidate, fp16_candidate, bf16_candidate, fp32_candidate;
  logic [7:0] chosen_format;
  logic [31:0] chosen_bits;
  logic chosen_error;
  assign highest = extract_nonzero ? int'(extract_highest) : -1;
  assign lowest = extract_nonzero ? int'(extract_lowest) : int'(KULISCH_W);

  always_comb begin
    int8_candidate = '0;
    if (lowest >= 149 && highest <= 156 && highest >= 0) begin
      if ((!extract_negative && extract_units <= 8'd127)
          || (extract_negative && extract_units <= 8'd128))
        int8_candidate = {1'b1, 24'd0,
            (extract_negative ? -extract_units : extract_units)};
    end
    fp16_candidate = '0;
    if (highest >= 135 && highest <= 164 && lowest >= highest - 10)
      fp16_candidate = {1'b1, 16'd0, extract_negative, 5'(highest - 134),
          extract_significand[22:13]};
    else if (highest >= 0 && highest < 135 && lowest >= 125)
      fp16_candidate = {1'b1, 16'd0, extract_negative, 5'd0, extract_half_subnormal};
    bf16_candidate = '0;
    if (highest >= 23 && highest <= 276 && lowest >= highest - 7)
      bf16_candidate = {1'b1, 16'd0, extract_negative, 8'(highest - 22),
          extract_significand[22:16]};
    else if (highest >= 0 && highest < 23 && lowest >= 16)
      bf16_candidate = {1'b1, 16'd0, extract_negative, 8'd0, extract_low[22:16]};
    fp32_candidate = '0;
    if (highest >= 23 && highest <= 276 && lowest >= highest - 23)
      fp32_candidate = {1'b1, extract_negative, 8'(highest - 22),
          extract_significand[22:0]};
    else if (highest >= 0 && highest < 23 && lowest >= 0)
      fp32_candidate = {1'b1, extract_negative, 8'd0, extract_low};

    chosen_format = PRISM_FORMAT_KULISCH;
    chosen_bits = '0;
    chosen_error = 1'b0;
    case (extract_tag)
      8'd0: begin
        if (!extract_nonzero) begin
          chosen_error = 1'b1;
        end else if (int8_candidate[32]) begin
          chosen_format = PRISM_FORMAT_INT8;
          chosen_bits = int8_candidate[31:0];
        end else if (fp16_candidate[32]) begin
          chosen_format = PRISM_FORMAT_FP16;
          chosen_bits = fp16_candidate[31:0];
        end else if (bf16_candidate[32]) begin
          chosen_format = PRISM_FORMAT_BF16;
          chosen_bits = bf16_candidate[31:0];
        end else if (fp32_candidate[32]) begin
          chosen_format = PRISM_FORMAT_FP32;
          chosen_bits = fp32_candidate[31:0];
        end
      end
      8'd1: begin
        chosen_format = PRISM_FORMAT_FP16;
        chosen_bits = 32'h0000_7e00;
      end
      8'd2, 8'd3: begin
        chosen_format = PRISM_FORMAT_FP16;
        chosen_bits = extract_tag == 8'd2 ? 32'h0000_7c00 : 32'h0000_fc00;
      end
      8'd4: begin
        chosen_format = PRISM_FORMAT_INT8;
      end
      8'd5: begin
        chosen_format = PRISM_FORMAT_FP16;
        chosen_bits = 32'h0000_8000;
      end
      default: chosen_error = 1'b1;
    endcase
    if (extract_mode_wide && extract_tag != 0 && extract_nonzero)
      chosen_error = 1'b1;
    if (!extract_mode_wide && extract_native_error)
      chosen_error = 1'b1;
  end

  always_ff @(posedge clk) begin
    if (choice_load) begin
      m_format <= chosen_format;
      m_native_bits <= chosen_bits;
      m_fp32_bits <= fp32_candidate[31:0];
      m_fp32_exact <= extract_tag == 0 && extract_nonzero
          && fp32_candidate[32] && !chosen_error;
      m_kulisch_tag <= extract_tag;
      m_kulisch_integer <= extract_integer;
      m_error <= chosen_error;
    end
  end

  logic unused_native_finite;
  assign unused_native_finite = native_finite;

endmodule
