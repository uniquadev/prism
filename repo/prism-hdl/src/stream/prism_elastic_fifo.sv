//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_elastic_fifo.sv
// Module: prism_elastic_fifo
// Description: Buffers generic ready/valid items and reports exact occupancy.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_elastic_fifo #(
    parameter int unsigned WIDTH = 8,
    parameter int unsigned DEPTH = 4
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic [WIDTH-1:0]           s_data,
    input  logic                       s_valid,
    output logic                       s_ready,
    output logic [WIDTH-1:0]           m_data,
    output logic                       m_valid,
    input  logic                       m_ready,
    output logic [$clog2(DEPTH+1)-1:0] occupancy
);

  localparam int unsigned PTR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
  localparam int unsigned COUNT_W = $clog2(DEPTH + 1);

  logic [WIDTH-1:0] memory [0:DEPTH-1];
  logic [PTR_W-1:0] write_pointer;
  logic [PTR_W-1:0] read_pointer;
  logic [COUNT_W-1:0] count;
  logic push;
  logic pop;

  assign s_ready = (count != COUNT_W'(DEPTH)) || (m_valid && m_ready);
  assign m_valid = (count != 0);
  assign m_data = memory[read_pointer];
  assign occupancy = count;
  assign push = s_valid && s_ready;
  assign pop = m_valid && m_ready;

  initial begin
    if (WIDTH == 0) begin
      $fatal(1, "prism_elastic_fifo WIDTH must be positive");
    end
    if (DEPTH < 2) begin
      $fatal(1, "prism_elastic_fifo DEPTH must be at least two");
    end
  end

  function automatic logic [PTR_W-1:0] next_pointer(input logic [PTR_W-1:0] pointer);
    if (pointer == PTR_W'(DEPTH - 1)) begin
      return '0;
    end
    return pointer + 1'b1;
  endfunction

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      write_pointer <= '0;
      read_pointer <= '0;
      count <= '0;
    end else begin
      if (push) begin
        memory[write_pointer] <= s_data;
        write_pointer <= next_pointer(write_pointer);
      end
      if (pop) begin
        read_pointer <= next_pointer(read_pointer);
      end
      case ({push, pop})
        2'b10: count <= count + 1'b1;
        2'b01: count <= count - 1'b1;
        default: count <= count;
      endcase
    end
  end

endmodule
