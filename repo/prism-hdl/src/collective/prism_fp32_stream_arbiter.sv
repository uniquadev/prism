//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_stream_arbiter.sv
// Module: prism_fp32_stream_arbiter
// Description: Local arbitration for the online FP32 path.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_stream_arbiter #(
    parameter int unsigned PORTS = 2,
    parameter int unsigned WIDTH = 512,
    localparam int unsigned PORT_W = PORTS > 1 ? $clog2(PORTS) : 1
) (
    input logic clk,
    input logic rst_n,
    input logic [WIDTH-1:0] s_data [0:PORTS-1],
    input logic [PORTS-1:0] s_valid,
    output logic [PORTS-1:0] s_ready,
    output logic [WIDTH-1:0] m_data,
    output logic m_valid,
    input logic m_ready
);
  logic [PORT_W-1:0] next_port, selected, held_port;
  logic found, held;
  always_comb begin
    found = held;
    selected = held ? held_port : next_port;
    for (integer offset = 0; offset < PORTS; offset++) begin
      if (!found && s_valid[(int'(next_port)+offset) % PORTS]) begin
        selected = PORT_W'((int'(next_port)+offset) % PORTS);
        found = 1'b1;
      end
    end
  end
  assign m_valid = found;
  assign m_data = s_data[selected];
  always_comb begin
    s_ready = '0;
    if (found) s_ready[selected] = m_ready;
  end
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      next_port <= '0;
      held_port <= '0;
      held <= 1'b0;
    end else if (m_valid && m_ready) begin
      held <= 1'b0;
      next_port <= selected == PORT_W'(PORTS-1) ? '0 : selected + 1'b1;
    end else if (m_valid) begin
      held <= 1'b1;
      held_port <= selected;
    end
  end
`ifndef SYNTHESIS
  always_ff @(posedge clk)
    if (rst_n && held && !s_valid[held_port])
      $fatal(1, "FP32 source withdrew a stalled transaction");
`endif
endmodule
