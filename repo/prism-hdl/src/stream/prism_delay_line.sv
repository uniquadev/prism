//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_delay_line.sv
// Module: prism_delay_line
// Description: Delays a value by a fixed number of clock cycles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_delay_line #(
    parameter int unsigned WIDTH = 8,
    // Zero connects the output to the input.
    parameter int unsigned STEPS = 1
) (
    input  logic             clk,
    input  logic [WIDTH-1:0] s_data,
    output logic [WIDTH-1:0] m_data
);

  if (STEPS == 0) begin : gen_wire
    assign m_data = s_data;
  end else begin : gen_delay
    logic [WIDTH-1:0] stage [0:STEPS-1];
    always_ff @(posedge clk) begin
      stage[0] <= s_data;
      for (int step = 1; step < STEPS; step++) stage[step] <= stage[step-1];
    end
    assign m_data = stage[STEPS-1];
  end

endmodule
