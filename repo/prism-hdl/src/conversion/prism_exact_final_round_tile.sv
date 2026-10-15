//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_final_round_tile.sv
// Module: prism_exact_final_round_tile
// Description: Registered sixteen-lane final rounding of an exact tile.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Sixteen values are rounded side by side in seven steps that never stall.
// The rounded tiles wait in a short queue for the consumer, and a tile is
// accepted only while the steps and the queue together hold fewer tiles than
// the queue can store, so no ready signal runs back through the rounding.
//
// A tile is registered twice before the rounding and the release of a place
// in the queue is registered before it is counted. The handshake, the count
// and the first tile register form the entry, an instance of its own, so
// that the entry can stay with the source of the tiles while the rounding
// and its queue lie elsewhere: only registers face each other.
//
// The two conditions of the operation that qualify a rounded tile, whether
// results leave on this path and whether the operation has failed, are
// registered here once more for the same reason. Both are settled before
// the first tile of an operation is rounded.
//
// A flush empties the entry, the steps and the queue. It is held for several
// cycles, and the rounding and its queue see it one register later.
module prism_exact_final_round_tile #(
    parameter int unsigned LANES = 16,
    parameter int unsigned KULISCH_W = 320,
    // Rounded tiles the queue holds.
    parameter int unsigned DEPTH = 32,
    // Places kept for tiles that have been asked for and are on their way.
    parameter int unsigned RESERVE = 8
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic [31:0]                s_first_element,
    input  logic [LANES-1:0]           s_element_keep,
    input  logic [LANES*8-1:0]         s_kulisch_tags,
    input  logic [LANES*KULISCH_W-1:0] s_kulisch_integers,
    input  logic [7:0]                 s_output_format,
    input  logic                       s_valid,
    output logic                       s_ready,
    // Up while a tile may still be asked for from a source without a ready.
    output logic                       m_request_ready,
    // Results leave on this path.
    input  logic                       s_enable,
    // The operation has failed: every tile leaves with its error flag.
    input  logic                       s_fault,
    // Drop every tile inside.
    input  logic                       s_flush,
    output logic [31:0]                m_first_element,
    output logic [LANES-1:0]           m_element_keep,
    output logic [511:0]               m_element_bits,
    output logic                       m_error,
    output logic                       m_valid,
    input  logic                       m_ready
);

  localparam int unsigned ROUND_STEPS = 7;
  localparam int unsigned RESULT_W = 32 + LANES + 512 + 1;

  logic input_valid, second_valid, taken;
  logic [31:0] input_first, second_first, rounded_first;
  logic [LANES-1:0] input_keep, second_keep, rounded_keep;
  logic [LANES*8-1:0] input_tags, second_tags;
  logic [LANES*KULISCH_W-1:0] input_integers, second_integers;
  logic [7:0] input_format, second_format;
  logic [LANES-1:0] lane_valid, lane_error;
  logic [511:0] lane_bits;
  logic [7:0] lane_format [0:LANES-1];
  logic unused_lane_formats, unused_queue_ready;
  logic enable, fault, queue_valid, queue_ready, queue_error;
  logic round_rst_n;

  initial begin
    if (LANES != 16 || KULISCH_W < 278 || KULISCH_W > 320 || DEPTH < 2
        || RESERVE >= DEPTH)
      $fatal(1, "Exact final tile rounder needs sixteen bounded lanes");
  end

  prism_exact_final_round_entry #(
      .LANES(LANES), .KULISCH_W(KULISCH_W), .DEPTH(DEPTH), .RESERVE(RESERVE)
  ) u_entry (
      .clk(clk), .rst_n(rst_n && !s_flush),
      .s_first_element(s_first_element), .s_element_keep(s_element_keep),
      .s_kulisch_tags(s_kulisch_tags), .s_kulisch_integers(s_kulisch_integers),
      .s_output_format(s_output_format), .s_valid(s_valid), .s_ready(s_ready),
      .m_request_ready(m_request_ready), .s_taken(taken),
      .m_first_element(input_first), .m_element_keep(input_keep),
      .m_kulisch_tags(input_tags), .m_kulisch_integers(input_integers),
      .m_output_format(input_format), .m_valid(input_valid)
  );
  always_ff @(posedge clk) round_rst_n <= rst_n && !s_flush;
  always_ff @(posedge clk) begin
    if (!round_rst_n) begin
      second_valid <= 1'b0;
      taken <= 1'b0;
    end else begin
      second_valid <= input_valid;
      taken <= m_valid && m_ready;
    end
  end
  always_ff @(posedge clk) begin
    enable <= s_enable;
    fault <= s_fault;
  end
  assign m_valid = queue_valid && enable;
  assign queue_ready = m_ready && enable;
  assign m_error = queue_error || fault;
  always_ff @(posedge clk) begin
    second_first <= input_first;
    second_keep <= input_keep;
    second_tags <= input_tags;
    second_integers <= input_integers;
    second_format <= input_format;
  end

  for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
    prism_exact_final_round_scalar #(.KULISCH_W(KULISCH_W)) u_round (
        .clk(clk), .rst_n(round_rst_n),
        .s_valid(second_valid),
        .s_mode_wide(1'b1), .s_fp32_bits(32'd0),
        .s_kulisch_tag(second_keep[lane]
            ? second_tags[lane*8 +: 8] : 8'd4),
        .s_kulisch_integer(second_keep[lane]
            ? $signed(second_integers[lane*KULISCH_W +: KULISCH_W]) : '0),
        .s_output_format(second_format), .m_valid(lane_valid[lane]),
        .m_format(lane_format[lane]),
        .m_bits(lane_bits[lane*32 +: 32]), .m_error(lane_error[lane])
    );
  end
  prism_delay_line #(.WIDTH(32 + LANES), .STEPS(ROUND_STEPS)) u_context (
      .clk(clk), .s_data({second_first, second_keep}), .m_data({rounded_first, rounded_keep})
  );

  always_comb begin
    unused_lane_formats = 1'b0;
    for (integer lane = 0; lane < LANES; lane++)
      unused_lane_formats |= ^lane_format[lane];
  end

  prism_elastic_fifo #(
      .WIDTH(RESULT_W), .DEPTH(DEPTH), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
  ) u_results (
      .clk(clk), .rst_n(round_rst_n),
      .s_data({rounded_first, rounded_keep, lane_bits, |(lane_error & rounded_keep)}),
      .s_valid(lane_valid[0]), .s_ready(unused_queue_ready),
      .m_data({m_first_element, m_element_keep, m_element_bits, queue_error}),
      .m_valid(queue_valid), .m_ready(queue_ready), .occupancy()
  );

  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (round_rst_n) begin
      assert (!(lane_valid[0] && !unused_queue_ready));
      assert (lane_valid == {LANES{lane_valid[0]}});
    end
  end
  // synthesis translate_on

endmodule
