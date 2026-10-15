//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_header_parser_harness.sv
// Module: prism_numbergroup_header_parser_harness
// Description: NumberGroup fixed-header parser probe for cycle-accurate codec tests.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_header_parser_harness (
    input  logic [511:0] s_tdata,
    input  logic [63:0]  s_tkeep,
    input  logic         s_valid,
    output logic         s_ready,
    input  logic         m_ready,
    output logic         m_valid,
    output logic         fixed_header_valid,
    output logic [47:0]  destination_mac,
    output logic [47:0]  source_mac,
    output logic [15:0]  ethertype,
    output logic [7:0]   version,
    output logic [7:0]   packet_class,
    output logic [63:0]  job_id,
    output logic [15:0]  group_id,
    output logic [15:0]  group_generation,
    output logic [15:0]  operation_id,
    output logic [31:0]  operation_generation,
    output logic [15:0]  source_endpoint,
    output logic [15:0]  destination_endpoint,
    output logic [31:0]  packet_id,
    output logic [31:0]  first_element,
    output logic [15:0]  element_count,
    output logic [7:0]   group_count,
    output logic [7:0]   flags,
    output logic [15:0]  body_bytes,
    output logic [15:0]  stream_id,
    output logic [15:0]  reserved,
    output logic [15:0]  ingress_port
);

  prism_pkg::prism_numbergroup_header_t header;

  prism_numbergroup_header_parser #(
      .PORT_INDEX(7)
  ) u_parser (
      .s_tdata(s_tdata),
      .s_tkeep(s_tkeep),
      .s_valid(s_valid),
      .s_ready(s_ready),
      .m_header(header),
      .m_valid(m_valid),
      .m_ready(m_ready)
  );

  assign fixed_header_valid = header.fixed_header_valid;
  assign destination_mac = header.destination_mac;
  assign source_mac = header.source_mac;
  assign ethertype = header.ethertype;
  assign version = header.version;
  assign packet_class = header.packet_class;
  assign job_id = header.key.job_id;
  assign group_id = header.key.group_id;
  assign group_generation = header.key.group_generation;
  assign operation_id = header.key.operation_id;
  assign operation_generation = header.key.operation_generation;
  assign source_endpoint = header.source_endpoint;
  assign destination_endpoint = header.destination_endpoint;
  assign packet_id = header.packet_id;
  assign first_element = header.first_element;
  assign element_count = header.element_count;
  assign group_count = header.group_count;
  assign flags = header.flags;
  assign body_bytes = header.body_bytes;
  assign stream_id = header.stream_id;
  assign reserved = header.reserved;
  assign ingress_port = header.ingress_port;

endmodule
