//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_elastic_register.sv
// Module: prism_elastic_register
// Description: One registered ready/valid stage with a combinational ready.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_elastic_register #(
    parameter int unsigned WIDTH = 8,
    // Data bits served by one copy of the valid flag and of the load decision.
    parameter int unsigned CONTROL_BITS = 256
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic [WIDTH-1:0] s_data,
    input  logic             s_valid,
    output logic             s_ready,
    output logic [WIDTH-1:0] m_data,
    output logic             m_valid,
    input  logic             m_ready
);

  localparam int unsigned COPIES = (WIDTH + CONTROL_BITS - 1) / CONTROL_BITS;

  initial begin
    if (WIDTH == 0 || CONTROL_BITS == 0) begin
      $fatal(1, "prism_elastic_register WIDTH and CONTROL_BITS must be positive");
    end
  end

  // Every copy sees the same handshake inputs and holds the same state;
  // copy 0 drives the interface.
  for (genvar copy = 0; copy < COPIES; copy++) begin : control_copy
    localparam int unsigned LOW = copy * CONTROL_BITS;
    localparam int unsigned SIZE = (WIDTH - LOW) < CONTROL_BITS ? WIDTH - LOW : CONTROL_BITS;
    logic [SIZE-1:0] data;
    (* dont_touch = "true" *) logic valid;
    (* dont_touch = "true" *) logic load;
    logic ready;

    assign m_data[LOW +: SIZE] = data;
    assign ready = !valid || m_ready;
    assign load = s_valid && ready;

    always_ff @(posedge clk) begin
      if (!rst_n) valid <= 1'b0;
      else if (ready) valid <= s_valid;
    end

    always_ff @(posedge clk) begin
      if (load) data <= s_data[LOW +: SIZE];
    end
  end

  assign m_valid = control_copy[0].valid;
  assign s_ready = control_copy[0].ready;

endmodule
