//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_control_plane.sv
// Module: prism_single_control_plane
// Description: In-band SINGLE configuration and lifecycle responses.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_control_plane #(
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
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic [511:0]                      s_axis_tdata,
    input  logic [63:0]                       s_axis_tkeep,
    input  logic                              s_axis_tlast,
    input  logic                              s_axis_tuser,
    input  logic                              s_axis_tvalid,
    output logic                              s_axis_tready,
    input  logic [47:0]                       s_local_mac,
    input  logic [47:0]                       s_manager_mac,
    input  logic [15:0]                       s_manager_port,
    input  logic [15:0]                       s_control_endpoint,
    input  logic [15:0]                       s_link_mtu,
    input  logic [15:0]                       s_usable_port_mask,
    input  logic                              s_shared_port_demux,
    input  prism_pkg::prism_operation_key_t   s_complete_operation,
    input  logic                              s_complete_valid,
    output logic                              m_context_installed,
    output logic                              m_context_active,
    output logic                              m_context_complete,
    output prism_pkg::prism_operation_key_t   m_context_operation,
    output logic [1279:0]                     m_context,
    output logic                              m_stage_pulse,
    output logic                              m_commit_pulse,
    output logic                              m_release_pulse,
    output logic [511:0]                      m_axis_tdata,
    output logic [63:0]                       m_axis_tkeep,
    output logic                              m_axis_tlast,
    output logic                              m_axis_tuser,
    output logic [15:0]                       m_frame_bytes,
    output logic                              m_axis_tvalid,
    input  logic                              m_axis_tready
);

  import prism_pkg::*;

  typedef enum logic [2:0] {
    IDLE, APPLY, WAIT_STATUS, EMIT
  } state_t;
  state_t state;
  prism_operation_key_t operation, ack_operation, lifecycle_ack_operation;
  logic [31:0] transaction_id, ack_transaction_id, lifecycle_ack_transaction;
  logic [15:0] source_endpoint, destination_endpoint;
  logic [15:0] ack_source_endpoint, ack_destination_endpoint;
  logic [7:0] command, ack_status, lifecycle_ack_status;
  logic command_valid, command_ready;
  logic stage_valid, stage_ready, stage_accept;
  logic [2:0] stage_error;
  logic [7:0] child_count, result_count, accumulator, partial_wire;
  logic [7:0] output_format, accepted_mask, rank_mask, collective_kind;
  logic [31:0] original_terms, maximum_terms, element_count, window_bytes;
  logic [15:0] kulisch_bits, mtu, window_intervals;
  logic [127:0] local_endpoints, peer_endpoints, local_ports, rank_ids;
  logic [383:0] peer_macs;
  logic [63:0] native_masks;
  logic [7:0] result_enabled;
  logic [1279:0] context_data;
  logic event_valid, consume_event;
  logic lifecycle_ready, lifecycle_ack_valid, lifecycle_ack_ready;
  logic encoder_ready;
  logic [511:0] ack_frame_data;
  logic [63:0] ack_frame_keep;
  logic ack_frame_valid, ack_frame_last, ack_frame_user;
  logic [15:0] ack_frame_bytes;
  logic unused_ack_meta;
  assign unused_ack_meta = ^{lifecycle_ack_operation, lifecycle_ack_transaction};

  assign event_valid = stage_valid || command_valid;
  assign consume_event = state == WAIT_STATUS && lifecycle_ack_valid;
  assign stage_ready = consume_event;
  assign command_ready = consume_event;
  assign context_data = {72'b0, child_count, result_count, original_terms,
      maximum_terms, element_count, kulisch_bits, mtu, window_intervals,
      window_bytes, accumulator, partial_wire, output_format, accepted_mask,
      rank_mask, collective_kind, local_endpoints, peer_endpoints, local_ports,
      rank_ids, peer_macs, native_masks, result_enabled};

  prism_single_stage_receiver #(
      .PORT_INDEX(PORT_INDEX),
      .SUPPORTED_POLICY_BITS(SUPPORTED_POLICY_BITS), .MAX_MTU(MAX_MTU),
      .MAX_ELEMENTS(MAX_ELEMENTS),
      .MAX_CHILDREN(MAX_CHILDREN),
      .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS),
      .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .MAX_WINDOW_INTERVALS(MAX_WINDOW_INTERVALS),
      .MAX_WINDOW_BYTES(MAX_WINDOW_BYTES)
  ) u_receiver (
      .clk(clk), .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast), .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
      .s_local_mac(s_local_mac), .s_manager_mac(s_manager_mac),
      .s_manager_port(s_manager_port),
      .s_control_endpoint(s_control_endpoint), .s_link_mtu(s_link_mtu),
      .s_usable_port_mask(s_usable_port_mask),
      .s_shared_port_demux(s_shared_port_demux),
      .m_operation(operation), .m_transaction_id(transaction_id),
      .m_source_endpoint(source_endpoint),
      .m_destination_endpoint(destination_endpoint),
      .m_command(command), .m_command_valid(command_valid),
      .m_command_ready(command_ready),
      .m_child_count(child_count), .m_result_count(result_count),
      .m_original_terms(original_terms),
      .m_maximum_original_terms(maximum_terms),
      .m_element_count(element_count), .m_kulisch_bits(kulisch_bits),
      .m_mtu(mtu), .m_window_intervals(window_intervals),
      .m_window_bytes(window_bytes),
      .m_accumulator(accumulator), .m_partial_wire(partial_wire),
      .m_output_format(output_format), .m_accepted_mask(accepted_mask),
      .m_rank_mask(rank_mask), .m_collective_kind(collective_kind),
      .m_local_endpoints(local_endpoints), .m_peer_endpoints(peer_endpoints),
      .m_local_ports(local_ports), .m_rank_ids(rank_ids),
      .m_peer_macs(peer_macs), .m_native_masks(native_masks),
      .m_result_enabled(result_enabled),
      .m_stage_accept(stage_accept), .m_stage_error(stage_error),
      .m_stage_valid(stage_valid), .m_stage_ready(stage_ready)
  );

  prism_single_lifecycle #(.CONTEXT_W(1280)) u_lifecycle (
      .clk(clk), .rst_n(rst_n),
      .s_operation(operation), .s_transaction_id(transaction_id),
      .s_command(command),
      .s_precheck_status(stage_valid && !stage_accept
          ? {5'b0, stage_error} : 8'd0),
      .s_context(context_data),
      .s_valid(state == APPLY), .s_ready(lifecycle_ready),
      .s_complete_operation(s_complete_operation),
      .s_complete_valid(s_complete_valid),
      .m_context_installed(m_context_installed),
      .m_context_active(m_context_active),
      .m_context_complete(m_context_complete),
      .m_context_operation(m_context_operation), .m_context(m_context),
      .m_stage_pulse(m_stage_pulse), .m_commit_pulse(m_commit_pulse),
      .m_release_pulse(m_release_pulse),
      .m_ack_operation(lifecycle_ack_operation),
      .m_ack_transaction_id(lifecycle_ack_transaction),
      .m_ack_status(lifecycle_ack_status),
      .m_ack_valid(lifecycle_ack_valid),
      .m_ack_ready(lifecycle_ack_ready)
  );

  assign lifecycle_ack_ready = state == WAIT_STATUS;

  prism_control_ack_encoder u_encoder (
      .clk(clk), .rst_n(rst_n),
      .s_operation(ack_operation), .s_transaction_id(ack_transaction_id),
      .s_source_endpoint(ack_destination_endpoint),
      .s_destination_endpoint(ack_source_endpoint),
      .s_source_mac(s_local_mac), .s_destination_mac(s_manager_mac),
      .s_status(ack_status), .s_valid(state == EMIT), .s_ready(encoder_ready),
      .m_axis_tdata(ack_frame_data), .m_axis_tkeep(ack_frame_keep),
      .m_axis_tlast(ack_frame_last), .m_axis_tuser(ack_frame_user),
      .m_frame_bytes(ack_frame_bytes),
      .m_axis_tvalid(ack_frame_valid), .m_axis_tready(m_axis_tready)
  );
  assign m_axis_tdata = ack_frame_data;
  assign m_axis_tkeep = ack_frame_keep;
  assign m_axis_tlast = ack_frame_last;
  assign m_axis_tuser = ack_frame_user;
  assign m_frame_bytes = ack_frame_bytes;
  assign m_axis_tvalid = ack_frame_valid;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE;
      ack_operation <= '0;
      ack_transaction_id <= '0;
      ack_source_endpoint <= '0;
      ack_destination_endpoint <= '0;
      ack_status <= '0;
    end else begin
      case (state)
        IDLE: begin
          // The fields of the answer follow the receiver while idle, so an
          // event decides only the state.
          ack_operation <= operation;
          ack_transaction_id <= transaction_id;
          ack_source_endpoint <= source_endpoint;
          ack_destination_endpoint <= destination_endpoint;
          if (event_valid) state <= APPLY;
        end
        APPLY: begin
          if (lifecycle_ready) state <= WAIT_STATUS;
        end
        WAIT_STATUS: begin
          if (lifecycle_ack_valid) begin
            ack_status <= lifecycle_ack_status;
            state <= EMIT;
          end
        end
        EMIT: begin
          if (encoder_ready) state <= IDLE;
        end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
