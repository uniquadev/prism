//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_accumulate_tile.sv
// Module: prism_fp32_accumulate_tile
// Description: Seed or increment FP32 lanes with matched elastic metadata.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_accumulate_tile #(
    parameter int unsigned LANES = 16,
    parameter int unsigned TAG_W = 8
) (
    input logic clk,
    input logic rst_n,
    input logic [LANES*32-1:0] s_sum,
    input logic [LANES*32-1:0] s_bits,
    input logic [LANES-1:0] s_present,
    input logic [LANES-1:0] s_keep,
    input logic [TAG_W-1:0] s_tag,
    input logic s_valid,
    output logic s_ready,
    output logic [LANES*32-1:0] m_bits,
    output logic [TAG_W-1:0] m_tag,
    output logic m_valid,
    input logic m_ready
);

  // Match the five elastic stages of prism_fp32_add. Bypass only lanes with
  // no incoming contribution or no previous sum; never seed by adding +0.
  logic [4:0] valid_pipe, ready_pipe;
  logic [TAG_W-1:0] tag_pipe [0:4];
  logic [LANES*32-1:0] bypass_pipe [0:4];
  logic [LANES-1:0] add_pipe [0:4];
  logic [LANES-1:0] add_ready, add_valid;
  logic [LANES*32-1:0] added, bypass_bits;

  for (genvar stage = 0; stage < 5; stage++) begin : gen_ready
    assign ready_pipe[stage] = !(&valid_pipe[4:stage]) || m_ready;
  end
  assign s_ready = ready_pipe[0];
  assign m_valid = valid_pipe[4];
  assign m_tag = tag_pipe[4];

  for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
    logic [4:0] unused_exceptions;
    assign bypass_bits[lane*32 +: 32] = s_keep[lane]
        ? s_bits[lane*32 +: 32] : s_sum[lane*32 +: 32];
    prism_fp32_add u_add (
        .clk(clk), .rst_n(rst_n),
        .s_left(s_sum[lane*32 +: 32]), .s_right(s_bits[lane*32 +: 32]),
        .s_valid(s_valid), .s_ready(add_ready[lane]),
        .m_result(added[lane*32 +: 32]), .m_exceptions(unused_exceptions),
        .m_valid(add_valid[lane]), .m_ready(m_ready)
    );
    assign m_bits[lane*32 +: 32] = add_pipe[4][lane]
        ? added[lane*32 +: 32] : bypass_pipe[4][lane*32 +: 32];
  end

  always_ff @(posedge clk) begin
    if (!rst_n) valid_pipe <= '0;
    else begin
      if (ready_pipe[0]) begin
        valid_pipe[0] <= s_valid;
        if (s_valid) begin
          tag_pipe[0] <= s_tag;
          bypass_pipe[0] <= bypass_bits;
          add_pipe[0] <= s_present & s_keep;
        end
      end
      for (integer stage = 1; stage < 5; stage++) begin
        if (ready_pipe[stage]) begin
          valid_pipe[stage] <= valid_pipe[stage-1];
          if (valid_pipe[stage-1]) begin
            tag_pipe[stage] <= tag_pipe[stage-1];
            bypass_pipe[stage] <= bypass_pipe[stage-1];
            add_pipe[stage] <= add_pipe[stage-1];
          end
        end
      end
    end
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (rst_n && (add_ready != {LANES{s_ready}}
        || add_valid != {LANES{m_valid}}))
      $fatal(1, "FP32 accumulation metadata lost lane lockstep");
  end
`endif
endmodule
