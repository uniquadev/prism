//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_elastic_split_buffer.sv
// Module: prism_elastic_split_buffer
// Description: Buffers a wide item with registered control and shallow payload storage.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_elastic_split_buffer #(
    parameter int unsigned WIDTH = 16,
    parameter int unsigned REGISTERED_WIDTH = 8,
    parameter bit PREWRITE_PAYLOAD_FREE_SLOT = 1'b0,
    parameter bit SKID_CONTROL = 1'b0
) (
    input  logic                        clk,
    input  logic                        rst_n,
    input  logic [WIDTH-1:0]            s_data,
    input  logic                        s_valid,
    output logic                        s_ready,
    output logic [WIDTH-1:0]            m_data,
    output logic                        m_valid,
    input  logic                        m_ready
);

  localparam int unsigned PAYLOAD_WIDTH = WIDTH - REGISTERED_WIDTH;

  logic [PAYLOAD_WIDTH-1:0] payload_data;
  logic [REGISTERED_WIDTH-1:0] control_data;
  logic payload_s_ready, payload_m_valid;
  logic control_s_ready, control_m_valid;
  logic paired_push, paired_pop;
  logic [1:0] unused_payload_occupancy;

  initial begin
    if ((REGISTERED_WIDTH < 1) || (REGISTERED_WIDTH >= WIDTH)) begin
      $fatal(1, "prism_elastic_split_buffer parameters are illegal");
    end
  end

  assign s_ready = payload_s_ready && control_s_ready;
  assign paired_push = s_valid && s_ready;
  assign m_valid = payload_m_valid && control_m_valid;
  assign paired_pop = m_valid && m_ready;
  assign m_data = {payload_data, control_data};

  // Both halves use the same two-entry acceptance policy. Gating push and pop
  // with their combined handshake keeps their occupancies exactly aligned.
  prism_elastic_fifo #(
      .WIDTH(PAYLOAD_WIDTH),
      .DEPTH(2),
      .READY_ON_POP(1'b0),
      .PREWRITE_FREE_SLOT(PREWRITE_PAYLOAD_FREE_SLOT)
  ) u_payload_fifo (
      .clk(clk),
      .rst_n(rst_n),
      .s_data(s_data[WIDTH-1:REGISTERED_WIDTH]),
      .s_valid(paired_push),
      .s_ready(payload_s_ready),
      .m_data(payload_data),
      .m_valid(payload_m_valid),
      .m_ready(paired_pop),
      .occupancy(unused_payload_occupancy)
  );

  if (SKID_CONTROL) begin : gen_skid_control
    // A two-register skid buffer cuts the downstream ready path before it can
    // return through the control-memory address. Payload storage advances with
    // the same paired handshakes.
    prism_elastic_skid_buffer #(
        .WIDTH(REGISTERED_WIDTH)
    ) u_control_buffer (
        .clk(clk),
        .rst_n(rst_n),
        .s_data(s_data[REGISTERED_WIDTH-1:0]),
        .s_valid(paired_push),
        .s_ready(control_s_ready),
        .m_data(control_data),
        .m_valid(control_m_valid),
        .m_ready(paired_pop)
    );
  end else begin : gen_fifo_control
    logic [1:0] unused_control_occupancy;

    // A circular FIFO keeps control words stationary until their slots are
    // reused. Downstream arbitration therefore advances only a read pointer
    // and cannot feed back through every control-data register.
    prism_elastic_fifo #(
        .WIDTH(REGISTERED_WIDTH),
        .DEPTH(2),
        .READY_ON_POP(1'b0),
        .PREWRITE_FREE_SLOT(1'b1)
    ) u_control_buffer (
        .clk(clk),
        .rst_n(rst_n),
        .s_data(s_data[REGISTERED_WIDTH-1:0]),
        .s_valid(paired_push),
        .s_ready(control_s_ready),
        .m_data(control_data),
        .m_valid(control_m_valid),
        .m_ready(paired_pop),
        .occupancy(unused_control_occupancy)
    );
  end

endmodule
