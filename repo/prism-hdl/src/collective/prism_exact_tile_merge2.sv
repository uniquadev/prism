//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_tile_merge2.sv
// Module: prism_exact_tile_merge2
// Description: Pipelined exact merge of two independently written lane banks.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_exact_tile_merge2 #(
    parameter int unsigned LANES = 16,
    parameter int unsigned KULISCH_W = 320
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic [7:0]                   s_slot,
    input  logic [LANES-1:0]             s_present0,
    input  logic [LANES*8-1:0]           s_tags0,
    input  logic [LANES*KULISCH_W-1:0]   s_integers0,
    input  logic [LANES-1:0]             s_present1,
    input  logic [LANES*8-1:0]           s_tags1,
    input  logic [LANES*KULISCH_W-1:0]   s_integers1,
    input  logic                         s_valid,
    output logic                         s_ready,
    output logic [7:0]                   m_slot,
    output logic [LANES-1:0]             m_present,
    output logic [LANES*8-1:0]           m_tags,
    output logic [LANES*KULISCH_W-1:0]   m_integers,
    output logic                         m_error,
    output logic                         m_valid,
    input  logic                         m_ready
);

  localparam int unsigned HALF_W = KULISCH_W / 2;
  // Four register steps: the two tiles as they arrive, the sum of the lower
  // halves, the sum of the upper halves with the carry, and the tag with the
  // sum it allows. The registers of the values carry data only; the valid
  // flags say which of them belong to a tile.
  logic advance, stage0_valid, stage1_valid, stage2_valid, stage3_valid;
  logic [7:0] stage0_slot, stage1_slot, stage2_slot, stage3_slot;
  logic [LANES-1:0] stage0_present0, stage0_present1;
  logic [LANES-1:0] stage1_present0, stage1_present1;
  logic [LANES-1:0] stage2_present0, stage2_present1;
  logic [LANES-1:0] stage3_present;
  logic [LANES*8-1:0] stage0_tags0, stage0_tags1;
  logic [LANES*8-1:0] stage1_tags0, stage1_tags1;
  logic [LANES*8-1:0] stage2_tags0, stage2_tags1;
  logic [LANES*KULISCH_W-1:0] stage0_integers0, stage0_integers1;
  logic [HALF_W-1:0] stage1_low [0:LANES-1];
  logic [HALF_W-1:0] stage1_high0 [0:LANES-1];
  logic [HALF_W-1:0] stage1_high1 [0:LANES-1];
  logic [LANES-1:0] stage1_carry;
  logic [HALF_W-1:0] stage2_low [0:LANES-1];
  // The upper sum keeps one more bit, which tells an overflow.
  logic [HALF_W:0] stage2_high [0:LANES-1];
  logic [LANES-1:0] stage2_low_nonzero;
  logic [LANES*8-1:0] stage3_tags;
  logic [LANES*KULISCH_W-1:0] stage3_integers;
  logic [LANES-1:0] stage3_errors;

  function automatic logic [7:0] combined_tag(
      input logic [7:0] left_tag,
      input logic [7:0] right_tag,
      input logic nonzero_sum
  );
    if (left_tag == 8'd1 || right_tag == 8'd1
        || ((left_tag == 8'd2 || right_tag == 8'd2)
            && (left_tag == 8'd3 || right_tag == 8'd3))) return 8'd1;
    if (left_tag == 8'd2 || right_tag == 8'd2) return 8'd2;
    if (left_tag == 8'd3 || right_tag == 8'd3) return 8'd3;
    if (nonzero_sum) return 8'd0;
    return (left_tag == 8'd5 && right_tag == 8'd5) ? 8'd5 : 8'd4;
  endfunction

  initial begin
    if ((LANES != 16 && LANES != 64 && LANES != 128)
        || KULISCH_W < 278 || KULISCH_W > 320
        || (KULISCH_W & 1) != 0)
      $fatal(1, "Exact tile merge requires bounded even-width lanes");
  end

  assign advance = !stage3_valid || m_ready;
  assign s_ready = advance;
  assign m_slot = stage3_slot;
  assign m_present = stage3_present;
  assign m_tags = stage3_tags;
  assign m_integers = stage3_integers;
  assign m_error = |stage3_errors;
  assign m_valid = stage3_valid;

  for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
    logic [HALF_W:0] low_sum, high_sum;
    logic [KULISCH_W-1:0] summed_integer;
    logic [7:0] merged_tag;
    logic [7:0] left_tag, right_tag;
    logic nonzero_sum;

    assign low_sum = {1'b0, stage0_integers0[lane*KULISCH_W +: HALF_W]}
        + {1'b0, stage0_integers1[lane*KULISCH_W +: HALF_W]};
    assign high_sum = {stage1_high0[lane][HALF_W-1], stage1_high0[lane]}
        + {stage1_high1[lane][HALF_W-1], stage1_high1[lane]}
        + {{HALF_W{1'b0}}, stage1_carry[lane]};
    assign summed_integer = {stage2_high[lane][HALF_W-1:0], stage2_low[lane]};
    assign nonzero_sum = stage2_low_nonzero[lane] || stage2_high[lane][HALF_W-1:0] != 0;
    assign left_tag = stage2_tags0[lane*8 +: 8];
    assign right_tag = stage2_tags1[lane*8 +: 8];
    assign merged_tag = !stage2_present0[lane] ? right_tag
        : !stage2_present1[lane] ? left_tag
            : combined_tag(left_tag, right_tag, nonzero_sum);

    always_ff @(posedge clk) begin
      if (advance) begin
        stage1_low[lane] <= low_sum[HALF_W-1:0];
        stage1_high0[lane]
            <= stage0_integers0[lane*KULISCH_W+HALF_W +: HALF_W];
        stage1_high1[lane]
            <= stage0_integers1[lane*KULISCH_W+HALF_W +: HALF_W];
        stage1_carry[lane] <= low_sum[HALF_W];
        stage2_low[lane] <= stage1_low[lane];
        stage2_low_nonzero[lane] <= stage1_low[lane] != 0;
        stage2_high[lane] <= high_sum;
        stage3_tags[lane*8 +: 8] <= merged_tag;
        stage3_integers[lane*KULISCH_W +: KULISCH_W]
            <= merged_tag == 8'd0 ? summed_integer : '0;
        stage3_errors[lane] <= stage2_present0[lane] && stage2_present1[lane]
            && stage2_high[lane][HALF_W] != stage2_high[lane][HALF_W-1];
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      stage0_valid <= 1'b0;
      stage1_valid <= 1'b0;
      stage2_valid <= 1'b0;
      stage3_valid <= 1'b0;
    end else if (advance) begin
      stage0_valid <= s_valid;
      stage1_valid <= stage0_valid;
      stage2_valid <= stage1_valid;
      stage3_valid <= stage2_valid;
    end
  end

  always_ff @(posedge clk) begin
    if (advance) begin
      if (s_valid) begin
        stage0_slot <= s_slot;
        stage0_present0 <= s_present0;
        stage0_present1 <= s_present1;
        stage0_tags0 <= s_tags0;
        stage0_tags1 <= s_tags1;
        for (integer lane = 0; lane < LANES; lane++) begin
          stage0_integers0[lane*KULISCH_W +: KULISCH_W]
              <= s_present0[lane]
                  ? s_integers0[lane*KULISCH_W +: KULISCH_W] : '0;
          stage0_integers1[lane*KULISCH_W +: KULISCH_W]
              <= s_present1[lane]
                  ? s_integers1[lane*KULISCH_W +: KULISCH_W] : '0;
        end
      end
      stage1_slot <= stage0_slot;
      stage1_present0 <= stage0_present0;
      stage1_present1 <= stage0_present1;
      stage1_tags0 <= stage0_tags0;
      stage1_tags1 <= stage0_tags1;
      stage2_slot <= stage1_slot;
      stage2_present0 <= stage1_present0;
      stage2_present1 <= stage1_present1;
      stage2_tags0 <= stage1_tags0;
      stage2_tags1 <= stage1_tags1;
      stage3_slot <= stage2_slot;
      stage3_present <= stage2_present0 | stage2_present1;
    end
  end

endmodule
