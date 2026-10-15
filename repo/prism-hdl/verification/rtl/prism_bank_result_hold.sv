//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_bank_result_hold.sv
// Module: prism_bank_result_hold
// Description: Holds bank results for a consumer with a ready, for test harnesses.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// A bank returns each result for one cycle and expects its consumer to have a
// place for it. This module is such a consumer for a harness whose next block
// has a ready: it grants a read only while it has a place for the result, and
// hands the results on in order.
module prism_bank_result_hold #(
    parameter int unsigned WIDTH = 8,
    parameter int unsigned DEPTH = 4
) (
    input  logic             clk,
    input  logic             rst_n,
    // A read may be granted; a read was granted.
    output logic             m_request_ready,
    input  logic             s_request_fire,
    input  logic [WIDTH-1:0] s_data,
    input  logic             s_valid,
    output logic [WIDTH-1:0] m_data,
    output logic             m_valid,
    input  logic             m_ready
);

  // Results asked for and not yet handed on.
  logic [$clog2(DEPTH+1)-1:0] claimed;
  logic queue_ready;

  assign m_request_ready = int'(claimed) < DEPTH;

  prism_elastic_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH)) u_queue (
      .clk(clk), .rst_n(rst_n),
      .s_data(s_data), .s_valid(s_valid), .s_ready(queue_ready),
      .m_data(m_data), .m_valid(m_valid), .m_ready(m_ready), .occupancy()
  );

  always_ff @(posedge clk) begin
    if (!rst_n) claimed <= '0;
    else begin
      case ({s_request_fire, m_valid && m_ready})
        2'b10: claimed <= claimed + 1'b1;
        2'b01: claimed <= claimed - 1'b1;
        default: ;
      endcase
      if (s_valid && !queue_ready) $fatal(1, "A bank result arrived without a place");
    end
  end

endmodule
