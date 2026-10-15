//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_join_geometry.sv
// Module: prism_numbergroup_join_geometry
// Description: Joins per-bank run geometry into tile-wide costs, origins and padding.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// A run that continues across a bank boundary is one group on the wire: the
// lanes of the right bank lose the descriptor and the padding that the bank
// counted for itself. Results appear join_steps(BANKS) cycles after the
// inputs.
module prism_numbergroup_join_geometry #(
    parameter int unsigned KULISCH_W = 280,
    parameter int unsigned LANES = 64,
    parameter int unsigned BANK_LANES = 16,
    localparam int unsigned BANKS = (LANES + BANK_LANES - 1) / BANK_LANES,
    localparam int unsigned BYTE_W
        = prism_numbergroup_geometry_pkg::byte_width(KULISCH_W, LANES),
    localparam int unsigned COUNT_W = $clog2(LANES + 1),
    localparam int unsigned GEO_W = LANES * (BYTE_W + COUNT_W + 4),
    localparam int unsigned SUMMARY_W = BYTE_W + COUNT_W + 22
) (
    input  logic                clk,
    input  logic [LANES*8-1:0]  s_formats,
    input  logic [GEO_W-1:0]    s_geometry,
    output logic [GEO_W-1:0]    m_geometry
);

  localparam int unsigned SCAN_STEPS = $clog2(BANKS);

  typedef struct packed {
    logic present;
    logic [BYTE_W-1:0] cost;
    logic [7:0] first_format, last_format;
    logic [1:0] first_residue, last_residue;
    logic uniform_run;
    logic [COUNT_W-1:0] last_origin;
  } summary_t;

  // Summaries of whole banks, scanned from both ends.
  logic [LANES*BYTE_W-1:0] input_cost;
  logic [LANES*COUNT_W-1:0] input_origin;
  logic [LANES*2-1:0] input_pad, input_end;
  logic [BANKS*SUMMARY_W-1:0] summaries, prefix, suffix;
  assign {input_cost, input_origin, input_pad, input_end} = s_geometry;
  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_summary
    localparam int unsigned BASE = bank * BANK_LANES;
    localparam int unsigned SIZE = (LANES - BASE) < BANK_LANES ? LANES - BASE : BANK_LANES;
    localparam int unsigned LAST = BASE + SIZE - 1;
    summary_t own;
    assign own = {1'b1, input_cost[LAST*BYTE_W +: BYTE_W], s_formats[BASE*8 +: 8],
        s_formats[LAST*8 +: 8], 2'(2'b00 - input_end[BASE*2 +: 2]),
        2'(2'b00 - input_end[LAST*2 +: 2]), input_origin[LAST*COUNT_W +: COUNT_W] == 0,
        COUNT_W'(BASE) + input_origin[LAST*COUNT_W +: COUNT_W]};
    assign summaries[bank*SUMMARY_W +: SUMMARY_W] = own;
  end
  prism_numbergroup_summary_scan #(
      .BANKS(BANKS), .BYTE_W(BYTE_W), .COUNT_W(COUNT_W)
  ) u_boundaries (
      .clk(clk), .s_summaries(summaries), .m_prefix(prefix), .m_suffix(suffix), .m_total()
  );

  // The bank geometry and the boundary formats wait for the scan.
  logic [GEO_W-1:0] scanned_geometry;
  logic [LANES*8-1:0] scanned_formats;
  prism_delay_line #(.WIDTH(GEO_W + LANES*8), .STEPS(SCAN_STEPS)) u_wait (
      .clk(clk), .s_data({s_geometry, s_formats}),
      .m_data({scanned_geometry, scanned_formats})
  );
  // Step 1: what each bank inherits from its neighbours.
  logic [BANKS-1:0] join_left;
  logic [BANKS*2-1:0] left_residue, right_residue;
  logic [BANKS*BYTE_W-1:0] left_cost;
  logic [BANKS*COUNT_W-1:0] left_origin;
  logic [GEO_W-1:0] geometry_1;
  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_neighbours
    localparam int unsigned BASE = bank * BANK_LANES;
    localparam int unsigned SIZE = (LANES - BASE) < BANK_LANES ? LANES - BASE : BANK_LANES;
    localparam int unsigned LAST = BASE + SIZE - 1;
    summary_t left_summary, right_summary;
    logic left_joined, right_joined;
    if (bank == 0) begin : gen_first
      assign left_summary = '0;
    end else begin : gen_left
      assign left_summary = prefix[(bank-1)*SUMMARY_W +: SUMMARY_W];
    end
    if (bank + 1 == BANKS) begin : gen_last
      assign right_summary = '0;
    end else begin : gen_right
      assign right_summary = suffix[(bank+1)*SUMMARY_W +: SUMMARY_W];
    end
    assign left_joined = left_summary.present
        && left_summary.last_format == scanned_formats[BASE*8 +: 8];
    assign right_joined = right_summary.present
        && scanned_formats[LAST*8 +: 8] == right_summary.first_format;
    always_ff @(posedge clk) begin
      join_left[bank] <= left_joined;
      left_residue[bank*2 +: 2] <= left_joined ? left_summary.last_residue : 2'b00;
      right_residue[bank*2 +: 2] <= right_joined ? right_summary.first_residue : 2'b00;
      left_cost[bank*BYTE_W +: BYTE_W] <= left_summary.cost;
      left_origin[bank*COUNT_W +: COUNT_W] <= left_summary.last_origin;
    end
  end
  always_ff @(posedge clk) geometry_1 <= scanned_geometry;

  // Step 2: per-lane corrections. Step 3: the corrected cost.
  logic [LANES*BYTE_W-1:0] local_cost, uncorrected, correction, cost;
  logic [LANES*COUNT_W-1:0] local_origin, origin, origin_2;
  logic [LANES*2-1:0] local_pad, local_end, pad, end_pad, pad_2, end_pad_2;
  assign {local_cost, local_origin, local_pad, local_end} = geometry_1;
  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_bank
    localparam int unsigned BASE = bank * BANK_LANES;
    localparam int unsigned SIZE = (LANES - BASE) < BANK_LANES ? LANES - BASE : BANK_LANES;
    localparam int unsigned LAST = BASE + SIZE - 1;
    logic [1:0] own_first_residue;
    assign own_first_residue = 2'b00 - local_end[BASE*2 +: 2];
    for (genvar offset = 0; offset < SIZE; offset++) begin : gen_lane
      localparam int unsigned LANE = BASE + offset;
      logic first_run, last_run, pad_word;
      logic [1:0] prefix_residue;
      logic [2:0] residues;
      assign first_run = local_origin[LANE*COUNT_W +: COUNT_W] == 0;
      assign last_run = local_origin[LANE*COUNT_W +: COUNT_W]
          == local_origin[LAST*COUNT_W +: COUNT_W];
      assign prefix_residue = first_run ? 2'b00 - local_pad[LANE*2 +: 2] : own_first_residue;
      assign residues = {1'b0, left_residue[bank*2 +: 2]} + {1'b0, prefix_residue};
      assign pad_word = left_residue[bank*2 +: 2] != 0 && prefix_residue != 0
          && residues <= 3'd4;
      assign origin[LANE*COUNT_W +: COUNT_W] = join_left[bank] && first_run
          ? left_origin[bank*COUNT_W +: COUNT_W]
          : COUNT_W'(BASE) + local_origin[LANE*COUNT_W +: COUNT_W];
      assign pad[LANE*2 +: 2] = local_pad[LANE*2 +: 2]
          - (first_run ? left_residue[bank*2 +: 2] : 2'b00);
      assign end_pad[LANE*2 +: 2] = local_end[LANE*2 +: 2]
          - (first_run ? left_residue[bank*2 +: 2] : 2'b00)
          - (last_run ? right_residue[bank*2 +: 2] : 2'b00);
      always_ff @(posedge clk) begin
        uncorrected[LANE*BYTE_W +: BYTE_W] <= left_cost[bank*BYTE_W +: BYTE_W]
            + local_cost[LANE*BYTE_W +: BYTE_W];
        correction[LANE*BYTE_W +: BYTE_W] <= join_left[bank]
            ? BYTE_W'(4) + BYTE_W'(pad_word) * BYTE_W'(4) : '0;
      end
      assign cost[LANE*BYTE_W +: BYTE_W] = uncorrected[LANE*BYTE_W +: BYTE_W]
          - correction[LANE*BYTE_W +: BYTE_W];
    end
  end
  always_ff @(posedge clk) begin
    origin_2 <= origin;
    pad_2 <= pad;
    end_pad_2 <= end_pad;
    m_geometry <= {cost, origin_2, pad_2, end_pad_2};
  end

endmodule
