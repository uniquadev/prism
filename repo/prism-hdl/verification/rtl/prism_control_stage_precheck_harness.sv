//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_stage_precheck_harness.sv
// Module: prism_control_stage_precheck_harness
// Description: Fixed SINGLE capacity and port binding for CONTROL receiver tests.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_stage_precheck_harness (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [511:0] s_axis_tdata,
    input  logic [63:0]  s_axis_tkeep,
    input  logic         s_axis_tlast,
    input  logic         s_axis_tuser,
    input  logic         s_axis_tvalid,
    output logic         s_axis_tready,
    input  logic [47:0]  s_local_mac,
    input  logic [47:0]  s_manager_mac,
    input  logic [15:0]  s_manager_port,
    output logic [7:0]   m_command,
    output logic         m_command_valid,
    input  logic         m_command_ready,
    output logic [7:0]   m_child_count,
    output logic [7:0]   m_result_count,
    output logic [31:0]  m_element_count,
    output logic [15:0]  m_kulisch_bits,
    output logic [7:0]   m_accumulator,
    output logic [7:0]   m_partial_wire,
    output logic [127:0] m_local_endpoints,
    output logic [127:0] m_local_ports,
    output logic [127:0] m_rank_ids,
    output logic [7:0]   m_result_enabled,
    output logic         m_stage_accept,
    output logic [2:0]   m_stage_error,
    output logic         m_stage_valid,
    input  logic         m_stage_ready
);

  prism_pkg::prism_operation_key_t unused_operation;
  logic [31:0] unused_transaction_id;
  logic [15:0] unused_source_endpoint, unused_destination_endpoint;
  logic [31:0] unused_original_terms, unused_maximum_terms;
  logic [15:0] unused_mtu, unused_window_intervals;
  logic [31:0] unused_window_bytes;
  logic [7:0] unused_output_format, unused_accepted_mask;
  logic [7:0] unused_rank_mask, unused_kind;
  logic [127:0] unused_peer_endpoints;
  logic [383:0] unused_peer_macs;
  logic [63:0] unused_native_masks;
  logic unused_outputs;
  assign unused_outputs = ^{unused_operation, unused_transaction_id,
      unused_source_endpoint, unused_destination_endpoint,
      unused_original_terms, unused_maximum_terms, unused_mtu,
      unused_window_intervals, unused_window_bytes, unused_output_format,
      unused_accepted_mask, unused_rank_mask, unused_kind,
      unused_peer_endpoints, unused_peer_macs, unused_native_masks};

  prism_single_stage_receiver u_receiver (
      .clk(clk), .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast), .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
      .s_local_mac(s_local_mac), .s_manager_mac(s_manager_mac),
      .s_manager_port(s_manager_port), .s_control_endpoint(16'hfffe),
      .s_link_mtu(16'd1500),
      .s_usable_port_mask(16'h000e), .s_shared_port_demux(1'b0),
      .m_operation(unused_operation),
      .m_transaction_id(unused_transaction_id),
      .m_source_endpoint(unused_source_endpoint),
      .m_destination_endpoint(unused_destination_endpoint),
      .m_command(m_command), .m_command_valid(m_command_valid),
      .m_command_ready(m_command_ready),
      .m_child_count(m_child_count), .m_result_count(m_result_count),
      .m_original_terms(unused_original_terms),
      .m_maximum_original_terms(unused_maximum_terms),
      .m_element_count(m_element_count), .m_kulisch_bits(m_kulisch_bits),
      .m_mtu(unused_mtu), .m_window_intervals(unused_window_intervals),
      .m_window_bytes(unused_window_bytes),
      .m_accumulator(m_accumulator), .m_partial_wire(m_partial_wire),
      .m_output_format(unused_output_format),
      .m_accepted_mask(unused_accepted_mask),
      .m_rank_mask(unused_rank_mask), .m_collective_kind(unused_kind),
      .m_local_endpoints(m_local_endpoints), .m_local_ports(m_local_ports),
      .m_rank_ids(m_rank_ids), .m_result_enabled(m_result_enabled),
      .m_peer_endpoints(unused_peer_endpoints),
      .m_peer_macs(unused_peer_macs),
      .m_native_masks(unused_native_masks),
      .m_stage_accept(m_stage_accept), .m_stage_error(m_stage_error),
      .m_stage_valid(m_stage_valid), .m_stage_ready(m_stage_ready)
  );

endmodule
