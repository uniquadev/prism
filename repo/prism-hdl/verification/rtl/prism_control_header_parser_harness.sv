//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_header_parser_harness.sv
// Module: prism_control_header_parser_harness
// Description: Protocol 2.0 CONTROL first-beat header probe.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_header_parser_harness (
    input  logic [511:0] s_tdata,
    input  logic [63:0]  s_tkeep,
    input  logic         s_valid,
    output logic         s_ready,
    output logic         m_valid,
    input  logic         m_ready,
    output logic [63:0]  m_job_id,
    output logic [15:0]  m_group_id,
    output logic [15:0]  m_group_generation,
    output logic [15:0]  m_operation_id,
    output logic [31:0]  m_operation_generation,
    output logic [31:0]  m_transaction_id,
    output logic [15:0]  m_source_endpoint,
    output logic [15:0]  m_destination_endpoint,
    output logic [7:0]   m_command,
    output logic [7:0]   m_status,
    output logic [15:0]  m_body_bytes,
    output logic [7:0]   m_fragment_index,
    output logic [7:0]   m_fragment_count,
    output logic [15:0]  m_ingress_port,
    output logic         m_fixed_header_valid
);

  prism_pkg::prism_control_frame_header_t header;
  logic unused_header_bits;
  assign unused_header_bits = ^header;

  prism_control_header_parser #(.PORT_INDEX(7)) u_parser (
      .s_tdata(s_tdata),
      .s_tkeep(s_tkeep),
      .s_valid(s_valid),
      .s_ready(s_ready),
      .m_header(header),
      .m_valid(m_valid),
      .m_ready(m_ready)
  );

  assign m_job_id = header.key.job_id;
  assign m_group_id = header.key.group_id;
  assign m_group_generation = header.key.group_generation;
  assign m_operation_id = header.key.operation_id;
  assign m_operation_generation = header.key.operation_generation;
  assign m_transaction_id = header.transaction_id;
  assign m_source_endpoint = header.source_endpoint;
  assign m_destination_endpoint = header.destination_endpoint;
  assign m_command = header.command;
  assign m_status = header.status;
  assign m_body_bytes = header.body_bytes;
  assign m_fragment_index = header.fragment_index;
  assign m_fragment_count = header.fragment_count;
  assign m_ingress_port = header.ingress_port;
  assign m_fixed_header_valid = header.fixed_header_valid;

endmodule
