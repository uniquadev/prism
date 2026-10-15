//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_summary_scan.sv
// Module: prism_numbergroup_summary_scan
// Description: Parallel prefix and suffix scans over per-bank run summaries.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// One registered step per scan level: results appear scan_steps(BANKS)
// cycles after the inputs.
module prism_numbergroup_summary_scan #(
    parameter int unsigned BANKS = 4,
    parameter int unsigned BYTE_W = 12,
    parameter int unsigned COUNT_W = 7,
    localparam int unsigned SUMMARY_W = BYTE_W + COUNT_W + 22,
    localparam int unsigned STAGES = $clog2(BANKS)
) (
    input  logic                        clk,
    input  logic [BANKS*SUMMARY_W-1:0]  s_summaries,
    output logic [BANKS*SUMMARY_W-1:0]  m_prefix,
    output logic [BANKS*SUMMARY_W-1:0]  m_suffix,
    output logic [SUMMARY_W-1:0]        m_total
);

  typedef struct packed {
    logic present;
    logic [BYTE_W-1:0] cost;
    logic [7:0] first_format, last_format;
    logic [1:0] first_residue, last_residue;
    logic uniform_run;
    logic [COUNT_W-1:0] last_origin;
  } summary_t;

  // Two adjacent lane ranges share one group when the last run of the left
  // range and the first run of the right range have the same format.
  function automatic summary_t merge(input summary_t a, b);
    summary_t c;
    logic joined, pad_word;
    logic [2:0] residues;
    begin
      joined = a.last_format == b.first_format;
      residues = {1'b0, a.last_residue} + {1'b0, b.first_residue};
      pad_word = a.last_residue != 0 && b.first_residue != 0 && residues <= 3'd4;
      c.present = 1'b1;
      c.cost = a.cost + b.cost - (joined ? BYTE_W'(4) + BYTE_W'(pad_word) * BYTE_W'(4) : '0);
      c.first_format = a.first_format;
      c.last_format = b.last_format;
      c.uniform_run = a.uniform_run && b.uniform_run && joined;
      c.first_residue = a.uniform_run && joined
          ? a.first_residue + b.first_residue : a.first_residue;
      c.last_residue = b.uniform_run && joined
          ? a.last_residue + b.last_residue : b.last_residue;
      c.last_origin = b.uniform_run && joined ? a.last_origin : b.last_origin;
      if (!a.present) c = b;
      else if (!b.present) c = a;
      return c;
    end
  endfunction

  for (genvar stage = 0; stage <= STAGES; stage++) begin : gen_stage
    summary_t prefix [0:BANKS-1];
    summary_t suffix [0:BANKS-1];
    for (genvar bank = 0; bank < BANKS; bank++) begin : gen_bank
      if (stage == 0) begin : gen_input
        assign prefix[bank] = s_summaries[bank*SUMMARY_W +: SUMMARY_W];
        assign suffix[bank] = s_summaries[bank*SUMMARY_W +: SUMMARY_W];
      end else begin : gen_join
        summary_t next_prefix, next_suffix;
        if (bank >= (1 << (stage-1))) begin : gen_left
          assign next_prefix = merge(gen_stage[stage-1].prefix[bank-(1 << (stage-1))],
              gen_stage[stage-1].prefix[bank]);
        end else begin : gen_keep_prefix
          assign next_prefix = gen_stage[stage-1].prefix[bank];
        end
        if (bank + (1 << (stage-1)) < BANKS) begin : gen_right
          assign next_suffix = merge(gen_stage[stage-1].suffix[bank],
              gen_stage[stage-1].suffix[bank+(1 << (stage-1))]);
        end else begin : gen_keep_suffix
          assign next_suffix = gen_stage[stage-1].suffix[bank];
        end
        always_ff @(posedge clk) begin
          prefix[bank] <= next_prefix;
          suffix[bank] <= next_suffix;
        end
      end
      if (stage == STAGES) begin : gen_output
        assign m_prefix[bank*SUMMARY_W +: SUMMARY_W] = prefix[bank];
        assign m_suffix[bank*SUMMARY_W +: SUMMARY_W] = suffix[bank];
      end
    end
  end
  assign m_total = gen_stage[STAGES].prefix[BANKS-1];

endmodule
