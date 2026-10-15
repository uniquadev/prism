//-
// Copyright (c) 2026 Lorenzo Cipolletti
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
    parameter int unsigned DEPTH = 4,
    parameter bit READY_ON_POP = 1'b1,
    parameter bit REGISTER_READY = 1'b0,
    parameter bit PREWRITE_FREE_SLOT = 1'b0
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
  logic [COUNT_W-1:0] next_count;
  logic ready_reg;
  logic push;
  logic pop;

  assign s_ready = REGISTER_READY ? ready_reg
      : ((count != COUNT_W'(DEPTH)) || (READY_ON_POP && m_valid && m_ready));
  assign m_valid = (count != 0);
  assign m_data = memory[read_pointer];
  assign occupancy = count;
  assign push = s_valid && s_ready;
  assign pop = m_valid && m_ready;

  always_comb begin
    next_count = count;
    case ({push, pop})
      2'b10: next_count = count + 1'b1;
      2'b01: next_count = count - 1'b1;
      default: ;
    endcase
  end

  initial begin
    if (WIDTH == 0) begin
      $fatal(1, "prism_elastic_fifo WIDTH must be positive");
    end
    if (DEPTH < 2) begin
      $fatal(1, "prism_elastic_fifo DEPTH must be at least two");
    end
    if (REGISTER_READY && READY_ON_POP) begin
      $fatal(1, "prism_elastic_fifo registered ready requires READY_ON_POP=0");
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
      ready_reg <= 1'b1;
    end else begin
      if (push) begin
        write_pointer <= next_pointer(write_pointer);
      end
      if (pop) begin
        read_pointer <= next_pointer(read_pointer);
      end
      count <= next_count;
      ready_reg <= (next_count != COUNT_W'(DEPTH));
    end
  end

  // The memory holds data only: its write does not depend on reset, so the
  // reset does not reach every memory cell.
  always_ff @(posedge clk) begin
    if (push || (PREWRITE_FREE_SLOT && s_ready)) begin
      memory[write_pointer] <= s_data;
    end
  end

endmodule
