//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_elastic_skid_buffer.sv
// Module: prism_elastic_skid_buffer
// Description: Breaks a generic ready path with two registered storage slots.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_elastic_skid_buffer #(
    parameter int unsigned WIDTH = 8,
    // Data bits served by one copy of the handshake state. A wide word gets
    // several identical copies, so that no enable net spans the whole word.
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
      $fatal(1, "prism_elastic_skid_buffer WIDTH and CONTROL_BITS must be positive");
    end
  end

  // Every copy sees the same handshake inputs and therefore holds the same
  // state; copy 0 drives the interface.
  for (genvar copy = 0; copy < COPIES; copy++) begin : control_copy
    localparam int unsigned LOW = copy * CONTROL_BITS;
    localparam int unsigned SIZE = (WIDTH - LOW) < CONTROL_BITS ? WIDTH - LOW : CONTROL_BITS;

    logic [SIZE-1:0] primary_data;
    logic [SIZE-1:0] skid_data;
    (* dont_touch = "true" *) logic primary_valid;
    (* dont_touch = "true" *) logic skid_valid;
    // The three decisions below are kept as nets of this copy, so the
    // handshake inputs reach a few gates per copy, not every data bit.
    (* dont_touch = "true" *) logic take_skid;
    (* dont_touch = "true" *) logic load_primary;
    (* dont_touch = "true" *) logic load_skid;
    logic input_fire;
    logic output_fire;

    assign m_data[LOW +: SIZE] = primary_data;
    assign input_fire = s_valid && !skid_valid;
    assign output_fire = primary_valid && m_ready;
    // An input can fire only while the skid slot is empty.
    assign take_skid = skid_valid && output_fire;
    assign load_primary = take_skid || (input_fire && (!primary_valid || output_fire));
    assign load_skid = input_fire && primary_valid && !output_fire;

    always_ff @(posedge clk) begin
      if (!rst_n) begin
        primary_valid <= 1'b0;
        skid_valid <= 1'b0;
      end else begin
        primary_valid <= input_fire || (primary_valid && !(output_fire && !skid_valid));
        if (load_skid) skid_valid <= 1'b1;
        else if (take_skid) skid_valid <= 1'b0;
      end
    end

    always_ff @(posedge clk) begin
      if (load_primary) primary_data <= take_skid ? skid_data : s_data[LOW +: SIZE];
      if (load_skid) skid_data <= s_data[LOW +: SIZE];
    end
  end
  assign s_ready = !control_copy[0].skid_valid;
  assign m_valid = control_copy[0].primary_valid;

endmodule
