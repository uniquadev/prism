//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_header_parser.sv
// Module: prism_numbergroup_header_parser
// Description: Extracts the fixed NumberGroup DATA/RESULT header from AXI beat zero.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_header_parser #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned PORT_INDEX = 0
) (
    input  logic [DATA_W-1:0]                     s_tdata,
    input  logic [DATA_W/8-1:0]                   s_tkeep,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output prism_pkg::prism_numbergroup_header_t  m_header,
    output logic                                  m_valid,
    input  logic                                  m_ready
);

  import prism_pkg::*;

  logic unused_payload_keep;
  assign unused_payload_keep = ^s_tkeep[DATA_W/8-1:56];

  function automatic logic [15:0] read_be16(input int unsigned byte_offset);
    return {s_tdata[(byte_offset+0)*8 +: 8], s_tdata[(byte_offset+1)*8 +: 8]};
  endfunction

  function automatic logic [31:0] read_be32(input int unsigned byte_offset);
    logic [31:0] result;
    for (int unsigned index = 0; index < 4; index++) begin
      result[(3-index)*8 +: 8] = s_tdata[(byte_offset+index)*8 +: 8];
    end
    return result;
  endfunction

  function automatic logic [47:0] read_be48(input int unsigned byte_offset);
    logic [47:0] result;
    for (int unsigned index = 0; index < 6; index++) begin
      result[(5-index)*8 +: 8] = s_tdata[(byte_offset+index)*8 +: 8];
    end
    return result;
  endfunction

  function automatic logic [63:0] read_be64(input int unsigned byte_offset);
    logic [63:0] result;
    for (int unsigned index = 0; index < 8; index++) begin
      result[(7-index)*8 +: 8] = s_tdata[(byte_offset+index)*8 +: 8];
    end
    return result;
  endfunction

  initial begin
    if ((DATA_W < 512) || ((DATA_W % 8) != 0)) begin
      $fatal(1, "NumberGroup parser requires a 512-bit or wider first AXI beat");
    end
    if (PORT_INDEX >= 65536) begin
      $fatal(1, "PORT_INDEX exceeds the local physical-port field");
    end
  end

  assign s_ready = m_ready;
  assign m_valid = s_valid;

  always_comb begin
    m_header = '0;
    m_header.destination_mac = read_be48(0);
    m_header.source_mac = read_be48(6);
    m_header.ethertype = read_be16(12);
    m_header.version = s_tdata[14*8 +: 8];
    m_header.packet_class = prism_opcode_e'(s_tdata[15*8 +: 8]);
    m_header.key.job_id = read_be64(16);
    m_header.key.group_id = read_be16(24);
    m_header.key.group_generation = read_be16(26);
    m_header.key.operation_id = read_be16(28);
    m_header.key.operation_generation = read_be32(30);
    m_header.source_endpoint = read_be16(34);
    m_header.destination_endpoint = read_be16(36);
    m_header.packet_id = read_be32(38);
    m_header.first_element = read_be32(42);
    m_header.element_count = read_be16(46);
    m_header.group_count = s_tdata[48*8 +: 8];
    m_header.flags = s_tdata[49*8 +: 8];
    m_header.body_bytes = read_be16(50);
    m_header.stream_id = read_be16(52);
    m_header.reserved = read_be16(54);
    m_header.ingress_port = 16'(PORT_INDEX);
    m_header.fixed_header_valid = &s_tkeep[55:0];
  end

endmodule
