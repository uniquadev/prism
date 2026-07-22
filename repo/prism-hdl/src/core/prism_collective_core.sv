//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_collective_core.sv
// Module: prism_collective_core
// Description: Composes the reusable PRISM collective datapath and control plane.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_collective_core #(
    parameter int unsigned DATA_W = prism_build_config_pkg::PRISM_DEFAULT_DATA_W,
    parameter int unsigned NUM_PORTS = prism_build_config_pkg::PRISM_DEFAULT_NUM_PORTS,
    parameter int unsigned USER_W = prism_build_config_pkg::PRISM_DEFAULT_USER_W,
    parameter int unsigned INGRESS_FIFO_DEPTH =
        prism_build_config_pkg::PRISM_DEFAULT_INGRESS_FIFO_DEPTH,
    parameter int unsigned EGRESS_FIFO_DEPTH =
        prism_build_config_pkg::PRISM_DEFAULT_EGRESS_FIFO_DEPTH,
    parameter int unsigned WORK_FIFO_DEPTH =
        prism_build_config_pkg::PRISM_DEFAULT_WORK_FIFO_DEPTH,
    parameter int unsigned SESSIONS = prism_build_config_pkg::PRISM_DEFAULT_SESSIONS,
    parameter int unsigned GROUPS = prism_build_config_pkg::PRISM_DEFAULT_GROUPS,
    parameter int unsigned OPERATION_CONTEXTS =
        prism_build_config_pkg::PRISM_DEFAULT_OPERATION_CONTEXTS,
    parameter int unsigned ACCUMULATOR_RANGES =
        prism_build_config_pkg::PRISM_DEFAULT_ACCUMULATOR_RANGES,
    parameter int unsigned CONTRIBUTORS = prism_build_config_pkg::PRISM_DEFAULT_CONTRIBUTORS,
    parameter int unsigned LANES = prism_build_config_pkg::PRISM_DEFAULT_ARITH_LANES,
    parameter int unsigned CONTROL_CONTEXTS =
        prism_build_config_pkg::PRISM_DEFAULT_CONTROL_CONTEXTS,
    parameter int unsigned CONTROL_BYTES = prism_build_config_pkg::PRISM_DEFAULT_CONTROL_BYTES,
    parameter int unsigned RESULT_SLOTS = prism_build_config_pkg::PRISM_DEFAULT_RESULT_SLOTS,
    parameter int unsigned RESULT_ROUTES =
        prism_build_config_pkg::PRISM_DEFAULT_RESULT_ROUTE_RANGES,
    parameter int unsigned REPLICATION_ENTRIES =
        prism_build_config_pkg::PRISM_DEFAULT_REPLICATION_GROUPS,
    parameter int unsigned WIDTH_COUNT =
        prism_build_config_pkg::PRISM_DEFAULT_KULISCH_WIDTH_COUNT,
    parameter int unsigned WIDTH_0 = prism_build_config_pkg::PRISM_DEFAULT_KULISCH_WIDTH_0,
    parameter int unsigned WIDTH_1 = prism_build_config_pkg::PRISM_DEFAULT_KULISCH_WIDTH_1,
    parameter int unsigned WIDTH_2 = prism_build_config_pkg::PRISM_DEFAULT_KULISCH_WIDTH_2,
    parameter logic [63:0] DEVICE_BOOT_ID =
        prism_build_config_pkg::PRISM_DEFAULT_DEVICE_BOOT_ID
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  logic                                      millisecond_tick,
    input  logic [NUM_PORTS*48-1:0]                   local_macs,
    input  logic                                      laboratory_extension_enabled,
    input  logic [DATA_W-1:0]                         s_axis_tdata [0:NUM_PORTS-1],
    input  logic [DATA_W/8-1:0]                       s_axis_tkeep [0:NUM_PORTS-1],
    input  logic [NUM_PORTS-1:0]                      s_axis_tlast,
    input  logic [USER_W-1:0]                         s_axis_tuser [0:NUM_PORTS-1],
    input  logic [NUM_PORTS-1:0]                      s_axis_tvalid,
    output logic [NUM_PORTS-1:0]                      s_axis_tready,
    output logic [DATA_W-1:0]                         m_axis_tdata [0:NUM_PORTS-1],
    output logic [DATA_W/8-1:0]                       m_axis_tkeep [0:NUM_PORTS-1],
    output logic [NUM_PORTS-1:0]                      m_axis_tlast,
    output logic [USER_W-1:0]                         m_axis_tuser [0:NUM_PORTS-1],
    output logic [NUM_PORTS-1:0]                      m_axis_tvalid,
    output logic [15:0]                               m_axis_frame_bytes [0:NUM_PORTS-1],
    input  logic [NUM_PORTS-1:0]                      m_axis_tready
);

  import prism_pkg::*;

  // ---------------------------------------------------------------------------
  // Derived configuration
  // ---------------------------------------------------------------------------

  localparam int unsigned LOOKUP_W = prism_clog2_safe(NUM_PORTS);
  localparam int unsigned TILE_W = $bits(prism_tile_meta_t) + LANES*32 + LANES;
  localparam int unsigned ARITH_BANKS = 2;
  localparam int unsigned BANK_RANGES = (((ACCUMULATOR_RANGES + ARITH_BANKS - 1)
      / ARITH_BANKS) < 2) ? 2 : ((ACCUMULATOR_RANGES + ARITH_BANKS - 1) / ARITH_BANKS);
  localparam int unsigned REDUCED_W = $bits(prism_tile_meta_t) + LANES*32 + LANES + 1;
  localparam int unsigned JOB_W = $bits(prism_result_packet_job_t);
  localparam int unsigned INGRESS_OCC_W = prism_clog2_safe(WORK_FIFO_DEPTH + 1);
  localparam int unsigned EGRESS_OCC_W = prism_clog2_safe(EGRESS_FIFO_DEPTH + 1);

  // ---------------------------------------------------------------------------
  // Per-port ingress and operation lookup
  // ---------------------------------------------------------------------------

  prism_frame_desc_t ingress_packet [0:NUM_PORTS-1];
  prism_packet_class_e ingress_class [0:NUM_PORTS-1];
  prism_status_e ingress_status [0:NUM_PORTS-1];
  prism_ingress_context_t ingress_context [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] ingress_packet_valid, ingress_packet_ready;
  logic [DATA_W-1:0] ingress_data [0:NUM_PORTS-1];
  logic [DATA_W/8-1:0] ingress_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] ingress_last, ingress_valid, ingress_ready;
  logic [USER_W-1:0] ingress_user [0:NUM_PORTS-1];
  prism_operation_key_t ingress_lookup_key [0:NUM_PORTS-1];
  logic [15:0] ingress_contributor_slot [0:NUM_PORTS-1];
  logic [15:0] ingress_contributor_id [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] lookup_request, lookup_grant;
  logic [LOOKUP_W-1:0] lookup_round_robin, lookup_selected;
  logic lookup_found;

  // ---------------------------------------------------------------------------
  // Validated packet-class streams
  // ---------------------------------------------------------------------------

  prism_frame_desc_t control_packet [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] control_packet_valid, control_packet_ready;
  logic [DATA_W-1:0] control_axis_data [0:NUM_PORTS-1];
  logic [DATA_W/8-1:0] control_axis_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] control_axis_last, control_axis_valid, control_axis_ready;
  logic [USER_W-1:0] control_axis_user [0:NUM_PORTS-1];
  prism_frame_desc_t data_packet [0:NUM_PORTS-1];
  prism_ingress_context_t data_context [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] data_packet_valid, data_packet_ready;
  logic [DATA_W-1:0] data_axis_data [0:NUM_PORTS-1];
  logic [DATA_W/8-1:0] data_axis_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] data_axis_last, data_axis_valid, data_axis_ready;
  logic [USER_W-1:0] data_axis_user [0:NUM_PORTS-1];

  // ---------------------------------------------------------------------------
  // Control-plane fragment streams
  // ---------------------------------------------------------------------------

  prism_control_header_t fragment_header [0:NUM_PORTS-1];
  logic [15:0] fragment_length [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] fragment_start_valid, fragment_start_ready;
  logic [7:0] fragment_byte [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] fragment_byte_last, fragment_byte_valid, fragment_byte_ready;

  // ---------------------------------------------------------------------------
  // Collective tile queues
  // ---------------------------------------------------------------------------

  prism_tile_meta_t depacketized_meta [0:NUM_PORTS-1];
  logic [LANES*32-1:0] depacketized_bits [0:NUM_PORTS-1];
  logic [LANES-1:0] depacketized_element_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] depacketized_valid, depacketized_ready;
  logic [TILE_W-1:0] tile_fifo_input [0:NUM_PORTS-1];
  logic [TILE_W-1:0] tile_fifo_output [0:NUM_PORTS-1];
  prism_tile_meta_t queued_meta [0:NUM_PORTS-1];
  logic [LANES*32-1:0] queued_bits [0:NUM_PORTS-1];
  logic [LANES-1:0] queued_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] queued_valid, queued_ready;

  // ---------------------------------------------------------------------------
  // Control-table lookup interface shared by ingress ports
  // ---------------------------------------------------------------------------

  logic operation_lookup_valid;
  logic [15:0] operation_lookup_slot;
  prism_operation_state_e operation_lookup_state;
  prism_operation_descriptor_t operation_lookup_descriptor;
  logic [15:0] operation_lookup_group_slot;
  logic [15:0] operation_lookup_expected_contributors;
  logic [15:0] operation_lookup_selected_width;
  logic [1:0] operation_lookup_width_index;
  logic operation_lookup_accumulation_inexact;
  logic contributor_lookup_valid;
  prism_contributor_binding_t contributor_lookup_binding;

  // ---------------------------------------------------------------------------
  // Reassembled control request and response pipeline
  // ---------------------------------------------------------------------------

  prism_control_header_t arbiter_header, reassembled_header;
  logic [15:0] arbiter_payload_length, reassembled_payload_length;
  logic arbiter_start_valid, arbiter_start_ready;
  logic [7:0] arbiter_byte, reassembled_byte;
  logic arbiter_byte_last, arbiter_byte_valid, arbiter_byte_ready;
  logic reassembled_header_valid, reassembled_header_ready;
  logic reassembled_byte_last, reassembled_byte_valid, reassembled_byte_ready;
  prism_status_e unused_reassembly_error_status;
  logic unused_reassembly_error_valid;

  prism_tlv_event_t tlv_event;
  logic tlv_event_valid, tlv_event_ready;
  prism_control_request_t control_request;
  prism_contributor_binding_t staged_contributors [0:CONTRIBUTORS-1];
  prism_replication_entry_t staged_replication [0:REPLICATION_ENTRIES-1];
  prism_result_route_t staged_routes [0:RESULT_ROUTES-1];
  logic control_request_valid, control_request_ready;
  prism_control_result_t control_result;
  logic control_result_valid, control_result_ready;

  prism_control_header_t response_header;
  logic [15:0] response_payload_length;
  logic response_header_valid, response_header_ready;
  logic [7:0] response_byte;
  logic response_byte_last, response_byte_valid, response_byte_ready;

  // ---------------------------------------------------------------------------
  // Typed reduction pipeline
  // ---------------------------------------------------------------------------

  logic [NUM_PORTS-1:0] bank_input_valid [0:ARITH_BANKS-1];
  logic [NUM_PORTS-1:0] bank_input_ready [0:ARITH_BANKS-1];
  prism_tile_meta_t bank_arbiter_meta [0:ARITH_BANKS-1];
  logic [LANES*32-1:0] bank_arbiter_bits [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_arbiter_keep [0:ARITH_BANKS-1];
  logic [ARITH_BANKS-1:0] bank_arbiter_valid, bank_arbiter_ready;
  prism_tile_meta_t bank_converted_meta [0:ARITH_BANKS-1];
  logic [LANES*32-1:0] bank_converted_fp32 [0:ARITH_BANKS-1];
  logic signed [LANES*WIDTH_2-1:0] bank_converted_deposits [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_keep [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_finite [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_zero [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_zero_sign [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_nan [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_pos_inf [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_neg_inf [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_converted_deposit_overflow [0:ARITH_BANKS-1];
  logic [ARITH_BANKS-1:0] bank_converted_format_error;
  logic [ARITH_BANKS-1:0] bank_converted_valid, bank_converted_ready;
  logic [1:0] bank_converted_width_index [0:ARITH_BANKS-1];
  prism_tile_meta_t bank_reduced_meta [0:ARITH_BANKS-1];
  logic [LANES*32-1:0] bank_reduced_fp32 [0:ARITH_BANKS-1];
  logic [LANES-1:0] bank_reduced_keep [0:ARITH_BANKS-1];
  logic [ARITH_BANKS-1:0] bank_reduced_warning;
  logic [ARITH_BANKS-1:0] bank_reduced_valid, bank_reduced_ready;
  logic [REDUCED_W-1:0] bank_reduced_fifo_input [0:ARITH_BANKS-1];
  logic [REDUCED_W-1:0] bank_reduced_fifo_output [0:ARITH_BANKS-1];
  prism_tile_meta_t queued_reduced_meta [0:ARITH_BANKS-1];
  logic [LANES*32-1:0] queued_reduced_fp32 [0:ARITH_BANKS-1];
  logic [LANES-1:0] queued_reduced_keep [0:ARITH_BANKS-1];
  logic [ARITH_BANKS-1:0] queued_reduced_warning;
  logic [ARITH_BANKS-1:0] queued_reduced_valid, queued_reduced_ready;
  logic [prism_clog2_safe(5)-1:0] unused_reduced_occupancy [0:ARITH_BANKS-1];
  prism_tile_meta_t reduced_meta, output_meta;
  logic [LANES*32-1:0] reduced_fp32, output_bits;
  logic [LANES-1:0] reduced_keep, output_keep;
  logic reduced_warning, reduced_valid, reduced_ready;
  logic output_warning, output_format_error, output_valid, output_ready;
  logic [LANES-1:0] unused_output_overflow;
  logic [LANES-1:0] unused_output_underflow;
  logic [LANES-1:0] unused_output_inexact;

  // ---------------------------------------------------------------------------
  // Result storage and routing
  // ---------------------------------------------------------------------------

  prism_result_chunk_meta_t ready_chunk_meta;
  logic [15:0] ready_chunk_slot;
  logic ready_chunk_valid, ready_chunk_ready;
  logic chunk_arm_valid;
  logic [15:0] chunk_arm_slot, chunk_arm_references;
  logic [NUM_PORTS-1:0] chunk_release_valid;
  logic [15:0] chunk_release_slot [0:NUM_PORTS-1];
  logic [15:0] chunk_read_slot [0:NUM_PORTS-1];
  logic [15:0] chunk_read_offset [0:NUM_PORTS-1];
  logic [511:0] chunk_read_data [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] chunk_read_armed;
  logic operation_complete_valid;
  logic [15:0] operation_complete_slot;

  logic [15:0] route_lookup_slot, route_lookup_index;
  logic route_lookup_valid;
  prism_result_route_t route_lookup_route;
  logic [15:0] replication_lookup_slot, replication_lookup_index;
  logic replication_lookup_valid;
  prism_replication_entry_t replication_lookup_entry;
  logic [15:0] replication_lookup_count;
  prism_result_packet_job_t routed_job;
  logic routed_job_valid, routed_job_ready;
  logic [JOB_W-1:0] job_fifo_input;
  logic [JOB_W-1:0] job_fifo_output [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] job_fifo_input_valid, job_fifo_input_ready;
  logic [NUM_PORTS-1:0] job_fifo_output_valid, job_fifo_output_ready;

  // ---------------------------------------------------------------------------
  // Per-port result and control egress
  // ---------------------------------------------------------------------------

  logic [DATA_W-1:0] result_axis_data [0:NUM_PORTS-1];
  logic [DATA_W/8-1:0] result_axis_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] result_axis_last, result_axis_valid, result_axis_ready;
  logic [USER_W-1:0] result_axis_user [0:NUM_PORTS-1];
  logic [15:0] control_egress_port;
  logic [DATA_W-1:0] control_tx_data;
  logic [DATA_W/8-1:0] control_tx_keep;
  logic control_tx_last, control_tx_valid, control_tx_ready;
  logic [USER_W-1:0] control_tx_user;

  logic [DATA_W-1:0] arbited_egress_data [0:NUM_PORTS-1];
  logic [DATA_W/8-1:0] arbited_egress_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] arbited_egress_last, arbited_egress_valid, arbited_egress_ready;
  logic [USER_W-1:0] arbited_egress_user [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] control_port_ready;
  logic [INGRESS_OCC_W-1:0] unused_tile_occupancy [0:NUM_PORTS-1];
  logic [INGRESS_OCC_W-1:0] unused_job_occupancy [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] unused_nonfinal_keep_error;
  logic [NUM_PORTS-1:0] unused_final_keep_error;
  logic [NUM_PORTS-1:0] unused_adapter_error;
  logic [EGRESS_OCC_W-1:0] unused_beat_occupancy [0:NUM_PORTS-1];
  logic [EGRESS_OCC_W-1:0] unused_completed_frames [0:NUM_PORTS-1];

  // ---------------------------------------------------------------------------
  // Elaboration checks and shared lookup arbitration
  // ---------------------------------------------------------------------------

  initial begin
    if ((DATA_W != 512) || (NUM_PORTS < 1) || (LANES < 1)
        || (CONTRIBUTORS < 1) || (CONTRIBUTORS > 16)
        || (WIDTH_COUNT < 1) || (WIDTH_COUNT > 3)) begin
      $fatal(1, "prism_collective_core parameters are illegal");
    end
  end

  always_comb begin
    lookup_found = 1'b0;
    lookup_selected = lookup_round_robin;
    for (int unsigned offset = 0; offset < NUM_PORTS; offset++) begin
      logic [LOOKUP_W-1:0] candidate;
      candidate = LOOKUP_W'((32'(lookup_round_robin) + offset) % NUM_PORTS);
      if (lookup_request[candidate] && !lookup_found) begin
        lookup_found = 1'b1;
        lookup_selected = candidate;
      end
    end
    lookup_grant = '0;
    if (lookup_found) lookup_grant[lookup_selected] = 1'b1;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) lookup_round_robin <= '0;
    else if (lookup_found) begin
      lookup_round_robin <= (lookup_selected == LOOKUP_W'(NUM_PORTS - 1))
          ? '0 : lookup_selected + LOOKUP_W'(1);
    end
  end

  // ---------------------------------------------------------------------------
  // Per-port ingress: AXI frame -> validated control or collective stream
  // ---------------------------------------------------------------------------

  for (genvar port = 0; port < NUM_PORTS; port++) begin : gen_ingress
    prism_ingress_port #(
        .DATA_W(DATA_W),
        .PORT_INDEX(port),
        .NUM_PORTS(NUM_PORTS),
        .FIFO_DEPTH(INGRESS_FIFO_DEPTH),
        .USER_W(USER_W)
    ) u_ingress_port (
        // Clock and reset
        .clk(clk),
        .rst_n(rst_n),

        // External ingress AXI stream
        .s_axis_tdata(s_axis_tdata[port]),
        .s_axis_tkeep(s_axis_tkeep[port]),
        .s_axis_tlast(s_axis_tlast[port]),
        .s_axis_tuser(s_axis_tuser[port]),
        .s_axis_tvalid(s_axis_tvalid[port]),
        .s_axis_tready(s_axis_tready[port]),

        // Runtime port configuration
        .local_macs(local_macs),
        .laboratory_extension_enabled(laboratory_extension_enabled),

        // Shared operation and contributor lookup
        .lookup_request(lookup_request[port]),
        .lookup_grant(lookup_grant[port]),
        .operation_lookup_key(ingress_lookup_key[port]),
        .operation_lookup_valid(operation_lookup_valid),
        .operation_lookup_state(operation_lookup_state),
        .operation_lookup_slot(operation_lookup_slot),
        .operation_lookup_descriptor(operation_lookup_descriptor),
        .operation_lookup_group_slot(operation_lookup_group_slot),
        .operation_lookup_expected_contributors(operation_lookup_expected_contributors),
        .operation_lookup_selected_width(operation_lookup_selected_width),
        .operation_lookup_width_index(operation_lookup_width_index),
        .operation_lookup_accumulation_inexact(operation_lookup_accumulation_inexact),
        .contributor_lookup_slot(ingress_contributor_slot[port]),
        .contributor_lookup_id(ingress_contributor_id[port]),
        .contributor_lookup_valid(contributor_lookup_valid),
        .contributor_lookup_binding(contributor_lookup_binding),

        // Validated framed output
        .m_packet(ingress_packet[port]),
        .m_packet_class(ingress_class[port]),
        .m_packet_status(ingress_status[port]),
        .m_packet_context(ingress_context[port]),
        .m_packet_valid(ingress_packet_valid[port]),
        .m_packet_ready(ingress_packet_ready[port]),
        .m_axis_tdata(ingress_data[port]),
        .m_axis_tkeep(ingress_keep[port]),
        .m_axis_tlast(ingress_last[port]),
        .m_axis_tuser(ingress_user[port]),
        .m_axis_tvalid(ingress_valid[port]),
        .m_axis_tready(ingress_ready[port])
    );

    prism_ingress_demux #(
        .DATA_W(DATA_W),
        .USER_W(USER_W)
    ) u_ingress_demux (
        .clk(clk),
        .rst_n(rst_n),
        .s_packet(ingress_packet[port]),
        .s_packet_class(ingress_class[port]),
        .s_packet_status(ingress_status[port]),
        .s_packet_context(ingress_context[port]),
        .s_packet_valid(ingress_packet_valid[port]),
        .s_packet_ready(ingress_packet_ready[port]),
        .s_axis_tdata(ingress_data[port]),
        .s_axis_tkeep(ingress_keep[port]),
        .s_axis_tlast(ingress_last[port]),
        .s_axis_tuser(ingress_user[port]),
        .s_axis_tvalid(ingress_valid[port]),
        .s_axis_tready(ingress_ready[port]),
        .m_control_packet(control_packet[port]),
        .m_control_packet_valid(control_packet_valid[port]),
        .m_control_packet_ready(control_packet_ready[port]),
        .m_control_axis_tdata(control_axis_data[port]),
        .m_control_axis_tkeep(control_axis_keep[port]),
        .m_control_axis_tlast(control_axis_last[port]),
        .m_control_axis_tuser(control_axis_user[port]),
        .m_control_axis_tvalid(control_axis_valid[port]),
        .m_control_axis_tready(control_axis_ready[port]),
        .m_data_packet(data_packet[port]),
        .m_data_context(data_context[port]),
        .m_data_packet_valid(data_packet_valid[port]),
        .m_data_packet_ready(data_packet_ready[port]),
        .m_data_axis_tdata(data_axis_data[port]),
        .m_data_axis_tkeep(data_axis_keep[port]),
        .m_data_axis_tlast(data_axis_last[port]),
        .m_data_axis_tuser(data_axis_user[port]),
        .m_data_axis_tvalid(data_axis_valid[port]),
        .m_data_axis_tready(data_axis_ready[port])
    );

    prism_control_depacketizer #(
        .DATA_W(DATA_W),
        .USER_W(USER_W)
    ) u_control_depacketizer (
        .clk(clk),
        .rst_n(rst_n),
        .s_packet(control_packet[port]),
        .s_packet_valid(control_packet_valid[port]),
        .s_packet_ready(control_packet_ready[port]),
        .s_axis_tdata(control_axis_data[port]),
        .s_axis_tkeep(control_axis_keep[port]),
        .s_axis_tlast(control_axis_last[port]),
        .s_axis_tuser(control_axis_user[port]),
        .s_axis_tvalid(control_axis_valid[port]),
        .s_axis_tready(control_axis_ready[port]),
        .m_header(fragment_header[port]),
        .m_payload_length(fragment_length[port]),
        .m_start_valid(fragment_start_valid[port]),
        .m_start_ready(fragment_start_ready[port]),
        .m_byte(fragment_byte[port]),
        .m_byte_last(fragment_byte_last[port]),
        .m_byte_valid(fragment_byte_valid[port]),
        .m_byte_ready(fragment_byte_ready[port])
    );

    prism_data_depacketizer #(
        .DATA_W(DATA_W),
        .USER_W(USER_W),
        .LANES(LANES)
    ) u_data_depacketizer (
        .clk(clk),
        .rst_n(rst_n),
        .s_packet(data_packet[port]),
        .s_context(data_context[port]),
        .s_packet_valid(data_packet_valid[port]),
        .s_packet_ready(data_packet_ready[port]),
        .s_axis_tdata(data_axis_data[port]),
        .s_axis_tkeep(data_axis_keep[port]),
        .s_axis_tlast(data_axis_last[port]),
        .s_axis_tuser(data_axis_user[port]),
        .s_axis_tvalid(data_axis_valid[port]),
        .s_axis_tready(data_axis_ready[port]),
        .m_tile_meta(depacketized_meta[port]),
        .m_element_bits(depacketized_bits[port]),
        .m_element_keep(depacketized_element_keep[port]),
        .m_tile_valid(depacketized_valid[port]),
        .m_tile_ready(depacketized_ready[port])
    );

    assign tile_fifo_input[port] = {
      depacketized_meta[port], depacketized_bits[port], depacketized_element_keep[port]
    };
    prism_elastic_fifo #(
        .WIDTH(TILE_W),
        .DEPTH(WORK_FIFO_DEPTH)
    ) u_tile_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .s_data(tile_fifo_input[port]),
        .s_valid(depacketized_valid[port]),
        .s_ready(depacketized_ready[port]),
        .m_data(tile_fifo_output[port]),
        .m_valid(queued_valid[port]),
        .m_ready(queued_ready[port]),
        .occupancy(unused_tile_occupancy[port])
    );
    assign {queued_meta[port], queued_bits[port], queued_keep[port]} = tile_fifo_output[port];
  end

  // ---------------------------------------------------------------------------
  // Control plane: arbitrate -> reassemble -> decode -> execute -> encode
  // ---------------------------------------------------------------------------

  prism_control_fragment_arbiter #(
      .PORTS(NUM_PORTS)
  ) u_control_arbiter (
      .clk(clk),
      .rst_n(rst_n),
      .s_header(fragment_header),
      .s_payload_length(fragment_length),
      .s_start_valid(fragment_start_valid),
      .s_start_ready(fragment_start_ready),
      .s_byte(fragment_byte),
      .s_byte_last(fragment_byte_last),
      .s_byte_valid(fragment_byte_valid),
      .s_byte_ready(fragment_byte_ready),
      .m_header(arbiter_header),
      .m_payload_length(arbiter_payload_length),
      .m_start_valid(arbiter_start_valid),
      .m_start_ready(arbiter_start_ready),
      .m_byte(arbiter_byte),
      .m_byte_last(arbiter_byte_last),
      .m_byte_valid(arbiter_byte_valid),
      .m_byte_ready(arbiter_byte_ready)
  );

  prism_control_reassembler #(
      .CONTEXTS(CONTROL_CONTEXTS),
      .CAPACITY_BYTES(CONTROL_BYTES)
  ) u_control_reassembler (
      .clk(clk),
      .rst_n(rst_n),
      .s_header(arbiter_header),
      .s_payload_length(arbiter_payload_length),
      .s_start_valid(arbiter_start_valid),
      .s_start_ready(arbiter_start_ready),
      .s_byte(arbiter_byte),
      .s_byte_last(arbiter_byte_last),
      .s_byte_valid(arbiter_byte_valid),
      .s_byte_ready(arbiter_byte_ready),
      .m_header(reassembled_header),
      .m_payload_length(reassembled_payload_length),
      .m_header_valid(reassembled_header_valid),
      .m_header_ready(reassembled_header_ready),
      .m_byte(reassembled_byte),
      .m_byte_last(reassembled_byte_last),
      .m_byte_valid(reassembled_byte_valid),
      .m_byte_ready(reassembled_byte_ready),
      .error_status(unused_reassembly_error_status),
      .error_valid(unused_reassembly_error_valid),
      .error_ready(1'b1)
  );

  prism_tlv_decoder u_tlv_decoder (
      .clk(clk),
      .rst_n(rst_n),
      .s_header(reassembled_header),
      .s_payload_length(reassembled_payload_length),
      .s_header_valid(reassembled_header_valid),
      .s_header_ready(reassembled_header_ready),
      .s_byte(reassembled_byte),
      .s_byte_last(reassembled_byte_last),
      .s_byte_valid(reassembled_byte_valid),
      .s_byte_ready(reassembled_byte_ready),
      .m_event(tlv_event),
      .m_event_valid(tlv_event_valid),
      .m_event_ready(tlv_event_ready)
  );

  prism_control_stager #(
      .MAX_CONTRIBUTORS(CONTRIBUTORS),
      .MAX_REPLICATION_ENTRIES(REPLICATION_ENTRIES),
      .MAX_RESULT_ROUTES(RESULT_ROUTES)
  ) u_control_stager (
      .clk(clk),
      .rst_n(rst_n),
      .s_event(tlv_event),
      .s_event_valid(tlv_event_valid),
      .s_event_ready(tlv_event_ready),
      .m_request(control_request),
      .m_contributors(staged_contributors),
      .m_replication_entries(staged_replication),
      .m_result_routes(staged_routes),
      .m_request_valid(control_request_valid),
      .m_request_ready(control_request_ready)
  );

  prism_control_executor #(
      .NUM_PORTS(NUM_PORTS),
      .SESSIONS(SESSIONS),
      .GROUPS(GROUPS),
      .OPERATIONS(OPERATION_CONTEXTS),
      .MAX_CONTRIBUTORS(CONTRIBUTORS),
      .MAX_REPLICATION_ENTRIES(REPLICATION_ENTRIES),
      .MAX_RESULT_ROUTES(RESULT_ROUTES),
      .WIDTH_COUNT(WIDTH_COUNT),
      .WIDTH_0(WIDTH_0),
      .WIDTH_1(WIDTH_1),
      .WIDTH_2(WIDTH_2),
      .DEVICE_BOOT_ID(DEVICE_BOOT_ID)
  ) u_control_executor (
      // Clock and control request stream
      .clk(clk),
      .rst_n(rst_n),
      .millisecond_tick(millisecond_tick),
      .s_request(control_request),
      .s_contributors(staged_contributors),
      .s_replication_entries(staged_replication),
      .s_result_routes(staged_routes),
      .s_request_valid(control_request_valid),
      .s_request_ready(control_request_ready),

      // Encodable control result stream
      .m_result(control_result),
      .m_result_valid(control_result_valid),
      .m_result_ready(control_result_ready),

      // Ingress operation and contributor lookup
      .operation_lookup_key(ingress_lookup_key[lookup_selected]),
      .operation_lookup_valid(operation_lookup_valid),
      .operation_lookup_slot(operation_lookup_slot),
      .operation_lookup_state(operation_lookup_state),
      .operation_lookup_descriptor(operation_lookup_descriptor),
      .operation_lookup_group_slot(operation_lookup_group_slot),
      .operation_lookup_expected_contributors(operation_lookup_expected_contributors),
      .operation_lookup_selected_width(operation_lookup_selected_width),
      .operation_lookup_width_index(operation_lookup_width_index),
      .operation_lookup_accumulation_inexact(operation_lookup_accumulation_inexact),
      .contributor_lookup_slot(ingress_contributor_slot[lookup_selected]),
      .contributor_lookup_id(ingress_contributor_id[lookup_selected]),
      .contributor_lookup_valid(contributor_lookup_valid),
      .contributor_lookup_binding(contributor_lookup_binding),

      // Result replication and route lookup
      .replication_lookup_slot(replication_lookup_slot),
      .replication_lookup_index(replication_lookup_index),
      .replication_lookup_valid(replication_lookup_valid),
      .replication_lookup_entry(replication_lookup_entry),
      .replication_lookup_count(replication_lookup_count),
      .route_lookup_slot(route_lookup_slot),
      .route_lookup_index(route_lookup_index),
      .route_lookup_valid(route_lookup_valid),
      .route_lookup_route(route_lookup_route),

      // Datapath completion feedback
      .complete_operation_valid(operation_complete_valid),
      .complete_operation_slot(operation_complete_slot)
  );

  prism_control_response_encoder #(
      .SESSIONS(SESSIONS),
      .GROUPS(GROUPS),
      .OPERATIONS(OPERATION_CONTEXTS),
      .ACCUMULATOR_RANGES(ACCUMULATOR_RANGES),
      .REPLAY_SLOTS(RESULT_SLOTS),
      .MAX_CONTRIBUTORS(CONTRIBUTORS),
      .MAX_REPLICATION_GROUPS(REPLICATION_ENTRIES),
      .MAX_DESTINATIONS_PER_GROUP(REPLICATION_ENTRIES),
      .MAX_RESULT_ROUTES(RESULT_ROUTES),
      .MANAGEMENT_BYTES(CONTROL_BYTES),
      .WIDTH_COUNT(WIDTH_COUNT),
      .WIDTH_0(WIDTH_0),
      .WIDTH_1(WIDTH_1),
      .WIDTH_2(WIDTH_2)
  ) u_response_encoder (
      .clk(clk),
      .rst_n(rst_n),
      .s_result(control_result),
      .s_result_valid(control_result_valid),
      .s_result_ready(control_result_ready),
      .m_header(response_header),
      .m_payload_length(response_payload_length),
      .m_header_valid(response_header_valid),
      .m_header_ready(response_header_ready),
      .m_byte(response_byte),
      .m_byte_last(response_byte_last),
      .m_byte_valid(response_byte_valid),
      .m_byte_ready(response_byte_ready)
  );

  // ---------------------------------------------------------------------------
  // Collective datapath: select -> convert -> reduce -> format -> store
  // ---------------------------------------------------------------------------

  always_comb begin
    for (int unsigned bank = 0; bank < ARITH_BANKS; bank++) begin
      bank_input_valid[bank] = '0;
    end
    for (int unsigned port = 0; port < NUM_PORTS; port++) begin
      logic selected_bank;
      selected_bank = 1'((queued_meta[port].first_element / LANES) % ARITH_BANKS);
      bank_input_valid[selected_bank][port] = queued_valid[port];
    end
  end

  always_comb begin
    queued_ready = '0;
    for (int unsigned port = 0; port < NUM_PORTS; port++) begin
      logic selected_bank;
      selected_bank = 1'((queued_meta[port].first_element / LANES) % ARITH_BANKS);
      queued_ready[port] = bank_input_ready[selected_bank][port];
    end
  end

  for (genvar bank = 0; bank < ARITH_BANKS; bank++) begin : gen_arithmetic_bank
    prism_tile_arbiter #(
        .PORTS(NUM_PORTS),
        .LANES(LANES)
    ) u_tile_arbiter (
        .clk(clk),
        .rst_n(rst_n),
        .s_meta(queued_meta),
        .s_element_bits(queued_bits),
        .s_element_keep(queued_keep),
        .s_valid(bank_input_valid[bank]),
        .s_ready(bank_input_ready[bank]),
        .m_meta(bank_arbiter_meta[bank]),
        .m_element_bits(bank_arbiter_bits[bank]),
        .m_element_keep(bank_arbiter_keep[bank]),
        .m_valid(bank_arbiter_valid[bank]),
        .m_ready(bank_arbiter_ready[bank])
    );

    prism_input_conversion_stage #(
        .LANES(LANES),
        .WIDTH_COUNT(WIDTH_COUNT),
        .WIDTH_0(WIDTH_0),
        .WIDTH_1(WIDTH_1),
        .WIDTH_2(WIDTH_2)
    ) u_input_conversion (
        .clk(clk),
        .rst_n(rst_n),
        .s_meta(bank_arbiter_meta[bank]),
        .s_element_bits(bank_arbiter_bits[bank]),
        .s_element_keep(bank_arbiter_keep[bank]),
        .s_width_index(bank_arbiter_meta[bank].selected_width_index),
        .s_valid(bank_arbiter_valid[bank]),
        .s_ready(bank_arbiter_ready[bank]),
        .m_meta(bank_converted_meta[bank]),
        .m_fp32_bits(bank_converted_fp32[bank]),
        .m_kulisch_deposits(bank_converted_deposits[bank]),
        .m_element_keep(bank_converted_keep[bank]),
        .m_finite(bank_converted_finite[bank]),
        .m_zero(bank_converted_zero[bank]),
        .m_zero_sign(bank_converted_zero_sign[bank]),
        .m_nan(bank_converted_nan[bank]),
        .m_positive_infinity(bank_converted_pos_inf[bank]),
        .m_negative_infinity(bank_converted_neg_inf[bank]),
        .m_deposit_overflow(bank_converted_deposit_overflow[bank]),
        .m_format_error(bank_converted_format_error[bank]),
        .m_width_index(bank_converted_width_index[bank]),
        .m_valid(bank_converted_valid[bank]),
        .m_ready(bank_converted_ready[bank])
    );

    prism_range_scheduler #(
        .LANES(LANES),
        .RANGES(BANK_RANGES),
        .CONTRIBUTORS(CONTRIBUTORS),
        .WIDTH_0(WIDTH_0),
        .WIDTH_1(WIDTH_1),
        .WIDTH_2(WIDTH_2)
    ) u_range_scheduler (
        .clk(clk),
        .rst_n(rst_n),
        .s_meta(bank_converted_meta[bank]),
        .s_fp32_bits(bank_converted_fp32[bank]),
        .s_kulisch_deposits(bank_converted_deposits[bank]),
        .s_element_keep(bank_converted_keep[bank]),
        .s_finite(bank_converted_finite[bank]),
        .s_zero(bank_converted_zero[bank]),
        .s_zero_sign(bank_converted_zero_sign[bank]),
        .s_nan(bank_converted_nan[bank]),
        .s_positive_infinity(bank_converted_pos_inf[bank]),
        .s_negative_infinity(bank_converted_neg_inf[bank]),
        .s_deposit_overflow(bank_converted_deposit_overflow[bank]),
        .s_width_index(bank_converted_width_index[bank]),
        .s_format_error(bank_converted_format_error[bank]),
        .s_valid(bank_converted_valid[bank]),
        .s_ready(bank_converted_ready[bank]),
        .m_meta(bank_reduced_meta[bank]),
        .m_fp32_bits(bank_reduced_fp32[bank]),
        .m_element_keep(bank_reduced_keep[bank]),
        .m_accumulation_inexact(bank_reduced_warning[bank]),
        .m_valid(bank_reduced_valid[bank]),
        .m_ready(bank_reduced_ready[bank])
    );

    assign bank_reduced_fifo_input[bank] = {
      bank_reduced_warning[bank], bank_reduced_meta[bank],
      bank_reduced_fp32[bank], bank_reduced_keep[bank]
    };

    prism_elastic_fifo #(
        .WIDTH(REDUCED_W),
        .DEPTH(4)
    ) u_reduced_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .s_data(bank_reduced_fifo_input[bank]),
        .s_valid(bank_reduced_valid[bank]),
        .s_ready(bank_reduced_ready[bank]),
        .m_data(bank_reduced_fifo_output[bank]),
        .m_valid(queued_reduced_valid[bank]),
        .m_ready(queued_reduced_ready[bank]),
        .occupancy(unused_reduced_occupancy[bank])
    );

    assign {queued_reduced_warning[bank], queued_reduced_meta[bank],
        queued_reduced_fp32[bank], queued_reduced_keep[bank]}
        = bank_reduced_fifo_output[bank];
  end

  prism_reduced_tile_arbiter #(
      .INPUTS(ARITH_BANKS),
      .LANES(LANES)
  ) u_reduced_tile_arbiter (
      .clk(clk),
      .rst_n(rst_n),
      .s_meta(queued_reduced_meta),
      .s_fp32_bits(queued_reduced_fp32),
      .s_element_keep(queued_reduced_keep),
      .s_warning(queued_reduced_warning),
      .s_valid(queued_reduced_valid),
      .s_ready(queued_reduced_ready),
      .m_meta(reduced_meta),
      .m_fp32_bits(reduced_fp32),
      .m_element_keep(reduced_keep),
      .m_warning(reduced_warning),
      .m_valid(reduced_valid),
      .m_ready(reduced_ready)
  );

  prism_result_conversion_stage #(
      .LANES(LANES)
  ) u_result_conversion (
      .clk(clk),
      .rst_n(rst_n),
      .s_meta(reduced_meta),
      .s_fp32_bits(reduced_fp32),
      .s_element_keep(reduced_keep),
      .s_accumulation_inexact(reduced_warning),
      .s_valid(reduced_valid),
      .s_ready(reduced_ready),
      .m_meta(output_meta),
      .m_element_bits(output_bits),
      .m_element_keep(output_keep),
      .m_accumulation_inexact(output_warning),
      .m_overflow(unused_output_overflow),
      .m_underflow(unused_output_underflow),
      .m_inexact(unused_output_inexact),
      .m_format_error(output_format_error),
      .m_valid(output_valid),
      .m_ready(output_ready)
  );

  prism_result_chunk_store #(
      .LANES(LANES),
      .SLOTS(RESULT_SLOTS),
      .READ_PORTS(NUM_PORTS),
      .OPERATION_CONTEXTS(OPERATION_CONTEXTS)
  ) u_result_store (
      .clk(clk),
      .rst_n(rst_n),
      .s_meta(output_meta),
      .s_element_bits(output_bits),
      .s_element_keep(output_keep),
      .s_accumulation_inexact(output_warning),
      .s_valid(output_valid && !output_format_error),
      .s_ready(output_ready),
      .m_chunk_meta(ready_chunk_meta),
      .m_chunk_slot(ready_chunk_slot),
      .m_chunk_valid(ready_chunk_valid),
      .m_chunk_ready(ready_chunk_ready),
      .arm_valid(chunk_arm_valid),
      .arm_slot(chunk_arm_slot),
      .arm_reference_count(chunk_arm_references),
      .release_valid(chunk_release_valid),
      .release_slot(chunk_release_slot),
      .read_slot(chunk_read_slot),
      .read_offset(chunk_read_offset),
      .read_data(chunk_read_data),
      .read_slot_armed(chunk_read_armed),
      .operation_complete_valid(operation_complete_valid),
      .operation_complete_slot(operation_complete_slot)
  );

  // ---------------------------------------------------------------------------
  // Result routing: stored chunk -> per-port packet job
  // ---------------------------------------------------------------------------

  prism_result_router u_result_router (
      .clk(clk),
      .rst_n(rst_n),
      .s_chunk_meta(ready_chunk_meta),
      .s_chunk_slot(ready_chunk_slot),
      .s_chunk_valid(ready_chunk_valid),
      .s_chunk_ready(ready_chunk_ready),
      .route_lookup_slot(route_lookup_slot),
      .route_lookup_index(route_lookup_index),
      .route_lookup_valid(route_lookup_valid),
      .route_lookup_route(route_lookup_route),
      .replication_lookup_slot(replication_lookup_slot),
      .replication_lookup_index(replication_lookup_index),
      .replication_lookup_valid(replication_lookup_valid),
      .replication_lookup_entry(replication_lookup_entry),
      .replication_lookup_count(replication_lookup_count),
      .m_job(routed_job),
      .m_job_valid(routed_job_valid),
      .m_job_ready(routed_job_ready),
      .arm_valid(chunk_arm_valid),
      .arm_slot(chunk_arm_slot),
      .arm_reference_count(chunk_arm_references)
  );

  assign job_fifo_input = routed_job;
  always_comb begin
    job_fifo_input_valid = '0;
    routed_job_ready = 1'b0;
    if (routed_job.egress_port < 16'(NUM_PORTS)) begin
      job_fifo_input_valid[LOOKUP_W'(routed_job.egress_port)] = routed_job_valid;
      routed_job_ready = job_fifo_input_ready[LOOKUP_W'(routed_job.egress_port)];
    end else begin
      routed_job_ready = 1'b1;
    end
  end

  // ---------------------------------------------------------------------------
  // Egress: packetize control/results -> arbitrate complete frames -> buffer
  // ---------------------------------------------------------------------------

  prism_control_packetizer #(
      .DATA_W(DATA_W),
      .USER_W(USER_W),
      .NUM_PORTS(NUM_PORTS)
  ) u_control_packetizer (
      .clk(clk),
      .rst_n(rst_n),
      .local_macs(local_macs),
      .s_header(response_header),
      .s_payload_length(response_payload_length),
      .s_header_valid(response_header_valid),
      .s_header_ready(response_header_ready),
      .s_byte(response_byte),
      .s_byte_last(response_byte_last),
      .s_byte_valid(response_byte_valid),
      .s_byte_ready(response_byte_ready),
      .m_egress_port(control_egress_port),
      .m_axis_tdata(control_tx_data),
      .m_axis_tkeep(control_tx_keep),
      .m_axis_tlast(control_tx_last),
      .m_axis_tuser(control_tx_user),
      .m_axis_tvalid(control_tx_valid),
      .m_axis_tready(control_tx_ready)
  );

  for (genvar port = 0; port < NUM_PORTS; port++) begin : gen_egress
    prism_elastic_fifo #(
        .WIDTH(JOB_W),
        .DEPTH(WORK_FIFO_DEPTH)
    ) u_job_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .s_data(job_fifo_input),
        .s_valid(job_fifo_input_valid[port]),
        .s_ready(job_fifo_input_ready[port]),
        .m_data(job_fifo_output[port]),
        .m_valid(job_fifo_output_valid[port]),
        .m_ready(job_fifo_output_ready[port]),
        .occupancy(unused_job_occupancy[port])
    );

    prism_result_packetizer #(
        .DATA_W(DATA_W),
        .USER_W(USER_W),
        .PORT_INDEX(port)
    ) u_result_packetizer (
        // Clock, reset, and local identity
        .clk(clk),
        .rst_n(rst_n),
        .local_mac(local_macs[port*48 +: 48]),

        // Routed packet job
        .s_job(prism_result_packet_job_t'(job_fifo_output[port])),
        .s_job_valid(job_fifo_output_valid[port]),
        .s_job_ready(job_fifo_output_ready[port]),

        // Shared result-chunk store read port
        .read_slot(chunk_read_slot[port]),
        .read_offset(chunk_read_offset[port]),
        .read_data(chunk_read_data[port]),
        .read_slot_armed(chunk_read_armed[port]),

        // Framed result output
        .m_axis_tdata(result_axis_data[port]),
        .m_axis_tkeep(result_axis_keep[port]),
        .m_axis_tlast(result_axis_last[port]),
        .m_axis_tuser(result_axis_user[port]),
        .m_axis_tvalid(result_axis_valid[port]),
        .m_axis_tready(result_axis_ready[port]),

        // Chunk lifetime feedback
        .release_valid(chunk_release_valid[port]),
        .release_slot(chunk_release_slot[port])
    );

    prism_axis_frame_arbiter #(
        .DATA_W(DATA_W),
        .USER_W(USER_W)
    ) u_egress_arbiter (
        .clk(clk),
        .rst_n(rst_n),
        .s0_axis_tdata(result_axis_data[port]),
        .s0_axis_tkeep(result_axis_keep[port]),
        .s0_axis_tlast(result_axis_last[port]),
        .s0_axis_tuser(result_axis_user[port]),
        .s0_axis_tvalid(result_axis_valid[port]),
        .s0_axis_tready(result_axis_ready[port]),
        .s1_axis_tdata(control_tx_data),
        .s1_axis_tkeep(control_tx_keep),
        .s1_axis_tlast(control_tx_last),
        .s1_axis_tuser(control_tx_user),
        .s1_axis_tvalid(control_tx_valid && (control_egress_port == 16'(port))),
        .s1_axis_tready(control_port_ready[port]),
        .m_axis_tdata(arbited_egress_data[port]),
        .m_axis_tkeep(arbited_egress_keep[port]),
        .m_axis_tlast(arbited_egress_last[port]),
        .m_axis_tuser(arbited_egress_user[port]),
        .m_axis_tvalid(arbited_egress_valid[port]),
        .m_axis_tready(arbited_egress_ready[port])
    );

    prism_axis_frame_fifo #(
        .DATA_W(DATA_W),
        .USER_W(USER_W),
        .DEPTH(EGRESS_FIFO_DEPTH),
        .MAX_FRAME_BEATS(24)
    ) u_egress_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .s_axis_tdata(arbited_egress_data[port]),
        .s_axis_tkeep(arbited_egress_keep[port]),
        .s_axis_tlast(arbited_egress_last[port]),
        .s_axis_tuser(arbited_egress_user[port]),
        .s_axis_tvalid(arbited_egress_valid[port]),
        .s_axis_tready(arbited_egress_ready[port]),
        .m_axis_tdata(m_axis_tdata[port]),
        .m_axis_tkeep(m_axis_tkeep[port]),
        .m_axis_tlast(m_axis_tlast[port]),
        .m_axis_tuser(m_axis_tuser[port]),
        .m_axis_tvalid(m_axis_tvalid[port]),
        .m_axis_tready(m_axis_tready[port]),
        .m_frame_bytes(m_axis_frame_bytes[port]),
        .m_nonfinal_keep_error(unused_nonfinal_keep_error[port]),
        .m_final_keep_error(unused_final_keep_error[port]),
        .m_adapter_error(unused_adapter_error[port]),
        .beat_occupancy(unused_beat_occupancy[port]),
        .completed_frames(unused_completed_frames[port])
    );
  end

  always_comb begin
    control_tx_ready = 1'b0;
    if (control_egress_port < 16'(NUM_PORTS)) begin
      control_tx_ready = control_port_ready[LOOKUP_W'(control_egress_port)];
    end
  end

endmodule
