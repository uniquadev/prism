//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_auto_wire_tile16.sv
// Module: prism_auto_wire_tile16
// Description: Lossless Auto classification for parallel exact or rounded tiles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Every lane picks the narrowest wire format that represents its value
// exactly. The tile leaves with the values in that format and as FP32; a
// tile whose kept values are all exact in FP32 is marked eligible, and the
// segment scheduler decides whether one FP32 group is cheaper on the wire.
module prism_auto_wire_tile16 #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned LANES = 16,
    // With lane valid input every lane classifier starts from its own copy
    // of s_valid, given in s_lane_valid.
    parameter bit LANE_VALID_INPUT = 1'b0
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic [31:0]                     s_first_element,
    input  logic [LANES-1:0]                s_keep,
    input  logic                            s_mode_wide,
    input  logic [LANES*32-1:0]             s_fp32_bits,
    input  logic [LANES*8-1:0]              s_tags,
    input  logic [LANES*KULISCH_W-1:0]      s_integers,
    input  logic                            s_valid,
    input  logic [LANES-1:0]                s_lane_valid,
    output logic                            s_ready,
    output logic [31:0]                     m_first_element,
    output logic [LANES-1:0]               m_keep,
    output logic [LANES*8-1:0]             m_formats,
    output logic [LANES*32-1:0]            m_native_bits,
    output logic [LANES*32-1:0]            m_fp32_bits,
    output logic                            m_fp32_eligible,
    output logic [LANES*8-1:0]             m_tags,
    output logic [LANES*KULISCH_W-1:0]     m_integers,
    output logic                            m_valid,
    // The valid flag of every lane classifier: copies of m_valid.
    output logic [LANES-1:0]               m_lane_valid,
    input  logic                            m_ready,
    output logic                            m_error
);

  logic [LANES-1:0] lane_valid, lane_ready, lane_error, lane_fp32_exact, eligible;
  logic [LANES*32-1:0] lane_fp32_bits;
  logic bad_keep;

  assign s_ready = lane_ready[0];
  assign m_valid = lane_valid[0];
  assign m_lane_valid = lane_valid;
  assign m_error = bad_keep || |(lane_error & m_keep);
  assign m_fp32_eligible = &eligible;

  for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
    assign eligible[lane] = !m_keep[lane]
        || (lane_fp32_exact[lane] && m_tags[lane*8 +: 8] == 0);
    // Only kept lanes change form when the tile is grouped as FP32.
    assign m_fp32_bits[lane*32 +: 32] = m_keep[lane]
        ? lane_fp32_bits[lane*32 +: 32] : m_native_bits[lane*32 +: 32];
    prism_auto_wire_scalar #(.KULISCH_W(KULISCH_W)) u_classifier (
        .clk(clk), .rst_n(rst_n),
        .s_valid(LANE_VALID_INPUT ? s_lane_valid[lane] : s_valid), .s_ready(lane_ready[lane]),
        .s_mode_wide(s_mode_wide), .s_fp32_bits(s_fp32_bits[lane*32 +: 32]),
        .s_kulisch_tag(s_tags[lane*8 +: 8]),
        .s_kulisch_integer(s_integers[lane*KULISCH_W +: KULISCH_W]),
        .m_valid(lane_valid[lane]), .m_ready(m_ready),
        .m_format(m_formats[lane*8 +: 8]),
        .m_native_bits(m_native_bits[lane*32 +: 32]),
        .m_fp32_bits(lane_fp32_bits[lane*32 +: 32]),
        .m_fp32_exact(lane_fp32_exact[lane]),
        .m_kulisch_tag(m_tags[lane*8 +: 8]),
        .m_kulisch_integer(m_integers[lane*KULISCH_W +: KULISCH_W]),
        .m_error(lane_error[lane])
    );
  end

  // The tile sideband passes through the same four ready/valid steps as the
  // lane classifiers, so it arrives together with their results.
  localparam int unsigned CLASSIFIER_STEPS = 4;
  localparam int unsigned SIDEBAND_W = 32 + LANES + 1;
  logic [SIDEBAND_W-1:0] sideband [0:CLASSIFIER_STEPS];
  logic [CLASSIFIER_STEPS:0] sideband_valid, sideband_ready;
  assign sideband[0] = {s_first_element, s_keep,
      s_keep == 0 || (s_keep & (s_keep + {{(LANES-1){1'b0}},1'b1})) != 0};
  assign sideband_valid[0] = s_valid;
  assign sideband_ready[CLASSIFIER_STEPS] = m_ready;
  for (genvar step = 0; step < CLASSIFIER_STEPS; step++) begin : gen_sideband
    prism_elastic_register #(.WIDTH(SIDEBAND_W)) u_step (
        .clk(clk), .rst_n(rst_n),
        .s_data(sideband[step]), .s_valid(sideband_valid[step]),
        .s_ready(sideband_ready[step]),
        .m_data(sideband[step+1]), .m_valid(sideband_valid[step+1]),
        .m_ready(sideband_ready[step+1])
    );
  end
  assign {m_first_element, m_keep, bad_keep} = sideband[CLASSIFIER_STEPS];

endmodule
