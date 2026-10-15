//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_stage_receiver.sv
// Module: prism_single_stage_receiver
// Description: Complete CONTROL frame through trusted-source and SINGLE context checks.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_stage_receiver #(
    parameter int unsigned PORT_INDEX = 1,
    parameter logic [3:0] SUPPORTED_POLICY_BITS = 4'b1101,
    parameter int unsigned MAX_MTU = 1500,
    parameter int unsigned MAX_ELEMENTS = 64,
    parameter int unsigned MAX_CHILDREN = 8,
    parameter int unsigned MAX_ORIGINAL_TERMS = 16,
    parameter int unsigned MAX_KULISCH_BITS = 320,
    parameter int unsigned MAX_WINDOW_INTERVALS = 16,
    parameter int unsigned MAX_WINDOW_BYTES = 65536
) (
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
    input  logic [15:0]  s_control_endpoint,
    input  logic [15:0]  s_link_mtu,
    input  logic [15:0]  s_usable_port_mask,
    input  logic         s_shared_port_demux,
    output prism_pkg::prism_operation_key_t m_operation,
    output logic [31:0]  m_transaction_id,
    output logic [15:0]  m_source_endpoint,
    output logic [15:0]  m_destination_endpoint,
    output logic [7:0]   m_command,
    output logic         m_command_valid,
    input  logic         m_command_ready,
    output logic [7:0]   m_child_count,
    output logic [7:0]   m_result_count,
    output logic [31:0]  m_original_terms,
    output logic [31:0]  m_maximum_original_terms,
    output logic [31:0]  m_element_count,
    output logic [15:0]  m_kulisch_bits,
    output logic [15:0]  m_mtu,
    output logic [15:0]  m_window_intervals,
    output logic [31:0]  m_window_bytes,
    output logic [7:0]   m_accumulator,
    output logic [7:0]   m_partial_wire,
    output logic [7:0]   m_output_format,
    output logic [7:0]   m_accepted_mask,
    output logic [7:0]   m_rank_mask,
    output logic [7:0]   m_collective_kind,
    output logic [127:0] m_local_endpoints,
    output logic [127:0] m_peer_endpoints,
    output logic [127:0] m_local_ports,
    output logic [127:0] m_rank_ids,
    output logic [383:0] m_peer_macs,
    output logic [63:0]  m_native_masks,
    output logic [7:0]   m_result_enabled,
    output logic         m_stage_accept,
    output logic [2:0]   m_stage_error,
    output logic         m_stage_valid,
    input  logic         m_stage_ready
);

  prism_pkg::prism_control_frame_header_t header;
  logic [15:0] frame_bytes;
  logic [15:0] effective_link_mtu;
  logic frame_valid, frame_accept, frame_ready;
  logic [2:0] frame_error;
  logic [15:0] read_address, fixed_read_address, binding_read_address;
  logic [7:0] read_data;
  logic context_s_ready, context_valid, context_accept;
  logic [2:0] context_error;
  logic binding_s_ready, binding_valid, binding_accept;
  logic [2:0] binding_error;
  logic trusted_frame, trusted_stage;
  typedef enum logic [2:0] {
    ADMIT_IDLE, ADMIT_FIXED, ADMIT_BINDING_START, ADMIT_BINDINGS
  } admission_state_t;
  admission_state_t admission_state;
  logic unused_fields;
  assign unused_fields = ^{frame_error, binding_s_ready};
  assign m_operation = header.key;
  assign m_transaction_id = header.transaction_id;
  assign m_source_endpoint = header.source_endpoint;
  assign m_destination_endpoint = header.destination_endpoint;
  assign m_command = header.command;
  assign effective_link_mtu = s_link_mtu < 16'(MAX_MTU)
      ? s_link_mtu : 16'(MAX_MTU);

  assign read_address = (admission_state == ADMIT_BINDING_START
          || admission_state == ADMIT_BINDINGS)
          ? binding_read_address : fixed_read_address;

  prism_control_frame_validator #(
      .MAX_MTU(MAX_MTU), .PORT_INDEX(PORT_INDEX)
  ) u_frame (
      .clk(clk), .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast), .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
      .s_mtu(effective_link_mtu), .m_header(header), .m_frame_bytes(frame_bytes),
      .m_accept(frame_accept), .m_error_code(frame_error),
      .m_valid(frame_valid), .m_ready(frame_ready),
      .m_read_address(read_address), .m_read_data(read_data)
  );

  assign trusted_frame = header.status == 0 && header.source_mac == s_manager_mac
      && header.destination_mac == s_local_mac
      && header.ingress_port == s_manager_port
      && header.source_endpoint == s_control_endpoint
      && header.destination_endpoint == s_control_endpoint;
  assign trusted_stage = trusted_frame && header.command == 8'd1;
  assign m_command_valid = admission_state == ADMIT_IDLE && frame_valid
      && frame_accept && trusted_frame && header.command != 8'd1;
  assign frame_ready = frame_valid && (!frame_accept || !trusted_frame
      || (m_stage_valid && m_stage_ready)
      || (m_command_valid && m_command_ready));

  prism_control_context_fixed_parser #(
      .MAX_CHILDREN(MAX_CHILDREN),
      .SUPPORTED_POLICY_BITS(SUPPORTED_POLICY_BITS)
  ) u_context (
      .clk(clk), .rst_n(rst_n),
      .s_body_bytes(header.body_bytes),
      .s_manager_mac(s_manager_mac), .s_manager_port(s_manager_port),
      .s_link_mtu(effective_link_mtu), .s_max_elements(32'(MAX_ELEMENTS)),
      .s_max_original_terms(32'(MAX_ORIGINAL_TERMS)),
      .s_max_kulisch_bits(16'(MAX_KULISCH_BITS)),
      .s_max_window_intervals(16'(MAX_WINDOW_INTERVALS)),
      .s_max_window_bytes(32'(MAX_WINDOW_BYTES)),
      .s_valid(frame_valid && frame_accept && trusted_stage
          && admission_state == ADMIT_IDLE),
      .s_ready(context_s_ready),
      .m_read_address(fixed_read_address), .m_read_data(read_data),
      .m_child_count(m_child_count), .m_result_count(m_result_count),
      .m_original_terms(m_original_terms),
      .m_maximum_original_terms(m_maximum_original_terms),
      .m_element_count(m_element_count), .m_kulisch_bits(m_kulisch_bits),
      .m_mtu(m_mtu), .m_window_intervals(m_window_intervals),
      .m_window_bytes(m_window_bytes),
      .m_accumulator(m_accumulator), .m_partial_wire(m_partial_wire),
      .m_output_format(m_output_format),
      .m_accepted_mask(m_accepted_mask),
      .m_rank_mask(m_rank_mask),
      .m_collective_kind(m_collective_kind),
      .m_accept(context_accept), .m_error_code(context_error),
      .m_valid(context_valid),
      .m_ready(admission_state == ADMIT_FIXED && context_valid
          && (context_accept || m_stage_ready))
  );

  prism_control_single_bindings_parser u_bindings (
      .clk(clk), .rst_n(rst_n),
      .s_child_count(m_child_count), .s_result_count(m_result_count),
      .s_rank_mask(m_rank_mask),
      .s_accepted_mask(m_accepted_mask), .s_manager_mac(s_manager_mac),
      .s_local_mac(s_local_mac), .s_supported_ports(s_usable_port_mask),
      .s_shared_port_demux(s_shared_port_demux),
      .s_valid(admission_state == ADMIT_BINDING_START),
      .s_ready(binding_s_ready),
      .m_read_address(binding_read_address), .m_read_data(read_data),
      .m_local_endpoints(m_local_endpoints),
      .m_peer_endpoints(m_peer_endpoints),
      .m_local_ports(m_local_ports), .m_rank_ids(m_rank_ids),
      .m_peer_macs(m_peer_macs),
      .m_native_masks(m_native_masks),
      .m_result_enabled(m_result_enabled),
      .m_accept(binding_accept), .m_error_code(binding_error),
      .m_valid(binding_valid),
      .m_ready(admission_state == ADMIT_BINDINGS && m_stage_ready)
  );

  assign m_stage_valid = (admission_state == ADMIT_FIXED && context_valid
      && !context_accept)
      || (admission_state == ADMIT_BINDINGS && binding_valid);
  assign m_stage_accept = admission_state == ADMIT_BINDINGS && binding_accept;
  assign m_stage_error = admission_state == ADMIT_FIXED
      ? context_error : binding_error;

  always_ff @(posedge clk) begin
    if (!rst_n) admission_state <= ADMIT_IDLE;
    else begin
      case (admission_state)
        ADMIT_IDLE: begin
          if (frame_valid && frame_accept && trusted_stage && context_s_ready)
            admission_state <= ADMIT_FIXED;
        end
        ADMIT_FIXED: begin
          if (context_valid) begin
            if (context_accept) admission_state <= ADMIT_BINDING_START;
            else if (m_stage_ready) admission_state <= ADMIT_IDLE;
          end
        end
        ADMIT_BINDING_START: begin
          if (binding_s_ready) admission_state <= ADMIT_BINDINGS;
        end
        ADMIT_BINDINGS: begin
          if (binding_valid && m_stage_ready) admission_state <= ADMIT_IDLE;
        end
        default: admission_state <= ADMIT_IDLE;
      endcase
    end
  end

endmodule
