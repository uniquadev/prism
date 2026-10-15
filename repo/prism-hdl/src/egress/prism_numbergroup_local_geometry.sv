//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_local_geometry.sv
// Module: prism_numbergroup_local_geometry
// Description: Computes NumberGroup run geometry independently for each 16-lane bank.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Results appear RUN_GEOMETRY_STEPS cycles after the inputs.
module prism_numbergroup_local_geometry #(
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
    input  logic                        clk,
    input  logic [LANES*8-1:0]          s_formats,
    input  logic [LANES-1:0]            s_keep,
    input  logic [15:0]                 s_kulisch_bits,
    output logic [GEO_W-1:0]            m_geometry,
    output logic [BANKS*SUMMARY_W-1:0]  m_active_summaries
);

  logic [LANES*BYTE_W-1:0] costs;
  logic [LANES*COUNT_W-1:0] origins;
  logic [LANES*2-1:0] pads, end_pads;
  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_bank
    localparam int unsigned BASE = bank * BANK_LANES;
    localparam int unsigned SIZE = (LANES - BASE) < BANK_LANES ? LANES - BASE : BANK_LANES;
    wire [SIZE*(BYTE_W+COUNT_W+4)-1:0] geometry;
    prism_numbergroup_run_geometry #(
        .LANES(SIZE), .BYTE_W(BYTE_W), .COUNT_W(COUNT_W), .BASE(BASE)
    ) u_local (
        .clk(clk),
        .s_formats(s_formats[BASE*8 +: SIZE*8]), .s_keep(s_keep[BASE +: SIZE]),
        .s_kulisch_bits(s_kulisch_bits), .m_geometry(geometry),
        .m_active_summary(m_active_summaries[bank*SUMMARY_W +: SUMMARY_W])
    );
    assign {costs[BASE*BYTE_W +: SIZE*BYTE_W], origins[BASE*COUNT_W +: SIZE*COUNT_W],
        pads[BASE*2 +: SIZE*2], end_pads[BASE*2 +: SIZE*2]} = geometry;
  end
  assign m_geometry = {costs, origins, pads, end_pads};

endmodule
