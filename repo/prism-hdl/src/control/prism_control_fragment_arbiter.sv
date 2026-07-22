//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_fragment_arbiter.sv
// Module: prism_control_fragment_arbiter
// Description: Arbitrates complete per-port CONTROL fragments without byte interleaving.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_fragment_arbiter #(
    parameter int unsigned PORTS = 2
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_control_header_t          s_header [0:PORTS-1],
    input  logic [15:0]                               s_payload_length [0:PORTS-1],
    input  logic [PORTS-1:0]                          s_start_valid,
    output logic [PORTS-1:0]                          s_start_ready,
    input  logic [7:0]                                s_byte [0:PORTS-1],
    input  logic [PORTS-1:0]                          s_byte_last,
    input  logic [PORTS-1:0]                          s_byte_valid,
    output logic [PORTS-1:0]                          s_byte_ready,
    output prism_pkg::prism_control_header_t          m_header,
    output logic [15:0]                               m_payload_length,
    output logic                                      m_start_valid,
    input  logic                                      m_start_ready,
    output logic [7:0]                                m_byte,
    output logic                                      m_byte_last,
    output logic                                      m_byte_valid,
    input  logic                                      m_byte_ready
);

  import prism_pkg::*;

  localparam int unsigned PORT_W = prism_clog2_safe(PORTS);
  logic locked;
  logic [PORT_W-1:0] selected_port;
  logic [PORT_W-1:0] round_robin;
  logic candidate_found;
  logic [PORT_W-1:0] candidate_port;

  initial begin
    if (PORTS < 1) $fatal(1, "prism_control_fragment_arbiter PORTS must be positive");
  end

  always_comb begin
    candidate_found = 1'b0;
    candidate_port = round_robin;
    for (int unsigned offset = 0; offset < PORTS; offset++) begin
      if (s_start_valid[(32'(round_robin) + offset) % PORTS] && !candidate_found) begin
        candidate_found = 1'b1;
        candidate_port = PORT_W'((32'(round_robin) + offset) % PORTS);
      end
    end
  end

  always_comb begin
    s_start_ready = '0;
    s_byte_ready = '0;
    m_header = s_header[candidate_port];
    m_payload_length = s_payload_length[candidate_port];
    m_start_valid = !locked && candidate_found;
    m_byte = s_byte[selected_port];
    m_byte_last = s_byte_last[selected_port];
    m_byte_valid = locked && s_byte_valid[selected_port];
    if (!locked && candidate_found) begin
      s_start_ready[candidate_port] = m_start_ready;
    end
    if (locked) begin
      s_byte_ready[selected_port] = m_byte_ready;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      locked <= 1'b0;
      selected_port <= '0;
      round_robin <= '0;
    end else begin
      if (m_start_valid && m_start_ready) begin
        selected_port <= candidate_port;
        if (m_payload_length != 0) begin
          locked <= 1'b1;
        end else begin
          round_robin <= (candidate_port == PORT_W'(PORTS - 1))
              ? '0 : candidate_port + 1'b1;
        end
      end
      if (m_byte_valid && m_byte_ready && m_byte_last) begin
        locked <= 1'b0;
        round_robin <= (selected_port == PORT_W'(PORTS - 1))
            ? '0 : selected_port + 1'b1;
      end
    end
  end

endmodule
