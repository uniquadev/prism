//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_executor.sv
// Module: prism_control_executor
// Description: Dispatches typed requests to session, group, or operation state owners.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_executor #(
    parameter int unsigned NUM_PORTS = 2,
    parameter int unsigned SESSIONS = 4,
    parameter int unsigned GROUPS = 8,
    parameter int unsigned OPERATIONS = 8,
    parameter int unsigned MAX_CONTRIBUTORS = 2,
    parameter int unsigned MAX_REPLICATION_ENTRIES = 2,
    parameter int unsigned MAX_RESULT_ROUTES = 2,
    parameter int unsigned WIDTH_COUNT = 3,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320,
    parameter logic [63:0] DEVICE_BOOT_ID = 64'h5052_4953_4D00_0001
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  logic                                      millisecond_tick,
    input  prism_pkg::prism_control_request_t         s_request,
    input  prism_pkg::prism_contributor_binding_t     s_contributors [0:MAX_CONTRIBUTORS-1],
    input  prism_pkg::prism_replication_entry_t       s_replication_entries [0:MAX_REPLICATION_ENTRIES-1],
    input  prism_pkg::prism_result_route_t            s_result_routes [0:MAX_RESULT_ROUTES-1],
    input  logic                                      s_request_valid,
    output logic                                      s_request_ready,
    output prism_pkg::prism_control_result_t          m_result,
    output logic                                      m_result_valid,
    input  logic                                      m_result_ready,
    input  prism_pkg::prism_operation_key_t           operation_lookup_key,
    output logic                                      operation_lookup_valid,
    output logic [15:0]                               operation_lookup_slot,
    output prism_pkg::prism_operation_state_e         operation_lookup_state,
    output prism_pkg::prism_operation_descriptor_t    operation_lookup_descriptor,
    output logic [15:0]                               operation_lookup_group_slot,
    output logic [15:0]                               operation_lookup_expected_contributors,
    output logic [15:0]                               operation_lookup_selected_width,
    output logic [1:0]                                operation_lookup_width_index,
    output logic                                      operation_lookup_accumulation_inexact,
    input  logic [15:0]                               contributor_lookup_slot,
    input  logic [15:0]                               contributor_lookup_id,
    output logic                                      contributor_lookup_valid,
    output prism_pkg::prism_contributor_binding_t     contributor_lookup_binding,
    input  logic [15:0]                               replication_lookup_slot,
    input  logic [15:0]                               replication_lookup_index,
    output logic                                      replication_lookup_valid,
    output prism_pkg::prism_replication_entry_t       replication_lookup_entry,
    output logic [15:0]                               replication_lookup_count,
    input  logic [15:0]                               route_lookup_slot,
    input  logic [15:0]                               route_lookup_index,
    output logic                                      route_lookup_valid,
    output prism_pkg::prism_result_route_t            route_lookup_route,
    input  logic                                      complete_operation_valid,
    input  logic [15:0]                               complete_operation_slot
);

  import prism_pkg::*;

  typedef enum logic [1:0] {TARGET_IMMEDIATE, TARGET_SESSION, TARGET_GROUP, TARGET_OPERATION} target_e;
  target_e request_target;

  logic session_request_ready;
  logic session_result_valid;
  logic session_result_ready;
  prism_control_result_t session_result;
  logic session_lookup_valid;
  logic [63:0] session_lookup_job_id;
  prism_session_state_e session_lookup_state;

  logic group_request_ready;
  logic group_result_valid;
  logic group_result_ready;
  prism_control_result_t group_result;
  logic session_has_groups;
  logic request_group_lookup_valid;
  logic [15:0] request_group_lookup_slot;
  prism_group_state_e request_group_lookup_state;
  prism_group_descriptor_t request_group_lookup_descriptor;
  // Operation admission needs only the contributor count from the canonical group descriptor.
  logic unused_request_group_descriptor_fields;
  assign unused_request_group_descriptor_fields = ^request_group_lookup_descriptor;

  logic operation_request_ready;
  logic operation_result_valid;
  logic operation_result_ready;
  prism_control_result_t operation_result;
  logic request_group_has_operations;

  logic immediate_valid;
  prism_control_result_t immediate_result;
  logic immediate_ready;
  prism_control_result_t selected_result;
  logic selected_valid;
  logic [15:0] response_command;

  function automatic logic [15:0] response_for(input logic [15:0] command);
    case (command)
      PRISM_CMD_CAPS_QUERY: return PRISM_CMD_CAPS_RESPONSE;
      PRISM_CMD_RESOURCE_QUERY: return PRISM_CMD_RESOURCE_RESPONSE;
      PRISM_CMD_SESSION_OPEN: return PRISM_CMD_SESSION_OPEN_RESPONSE;
      PRISM_CMD_SESSION_RENEW: return PRISM_CMD_SESSION_RENEW_RESPONSE;
      PRISM_CMD_SESSION_CLOSE: return PRISM_CMD_SESSION_CLOSE_RESPONSE;
      PRISM_CMD_GROUP_STAGE: return PRISM_CMD_GROUP_STAGE_RESPONSE;
      PRISM_CMD_GROUP_COMMIT: return PRISM_CMD_GROUP_COMMIT_RESPONSE;
      PRISM_CMD_GROUP_ABORT: return PRISM_CMD_GROUP_ABORT_RESPONSE;
      PRISM_CMD_GROUP_STATUS: return PRISM_CMD_GROUP_STATUS_RESPONSE;
      PRISM_CMD_GROUP_DESTROY: return PRISM_CMD_GROUP_DESTROY_RESPONSE;
      PRISM_CMD_OP_PREPARE: return PRISM_CMD_OP_PREPARE_RESPONSE;
      PRISM_CMD_OP_COMMIT: return PRISM_CMD_OP_COMMIT_RESPONSE;
      PRISM_CMD_OP_ABORT: return PRISM_CMD_OP_ABORT_RESPONSE;
      PRISM_CMD_OP_STATUS: return PRISM_CMD_OP_STATUS_RESPONSE;
      PRISM_CMD_OP_RELEASE: return PRISM_CMD_OP_RELEASE_RESPONSE;
      default: return PRISM_CMD_INVALID;
    endcase
  endfunction

  // ---------------------------------------------------------------------------
  // Command routing
  // ---------------------------------------------------------------------------

  always_comb begin
    case (s_request.header.command)
      PRISM_CMD_SESSION_OPEN,
      PRISM_CMD_SESSION_RENEW,
      PRISM_CMD_SESSION_CLOSE: request_target = TARGET_SESSION;
      PRISM_CMD_GROUP_STAGE,
      PRISM_CMD_GROUP_COMMIT,
      PRISM_CMD_GROUP_ABORT,
      PRISM_CMD_GROUP_STATUS,
      PRISM_CMD_GROUP_DESTROY: request_target = TARGET_GROUP;
      PRISM_CMD_OP_PREPARE,
      PRISM_CMD_OP_COMMIT,
      PRISM_CMD_OP_ABORT,
      PRISM_CMD_OP_STATUS,
      PRISM_CMD_OP_RELEASE: request_target = TARGET_OPERATION;
      default: request_target = TARGET_IMMEDIATE;
    endcase
  end

  // ---------------------------------------------------------------------------
  // Authoritative lifecycle tables
  // ---------------------------------------------------------------------------

  prism_session_table #(
      .SESSIONS(SESSIONS),
      .DEVICE_BOOT_ID(DEVICE_BOOT_ID)
  ) u_session_table (
      .clk(clk),
      .rst_n(rst_n),
      .millisecond_tick(millisecond_tick),
      .s_request(s_request),
      .s_request_valid(s_request_valid && (request_target == TARGET_SESSION)),
      .s_request_ready(session_request_ready),
      .request_session_has_groups(session_has_groups),
      .m_result(session_result),
      .m_result_valid(session_result_valid),
      .m_result_ready(session_result_ready),
      .lookup_cookie(s_request.header.session_cookie),
      .lookup_valid(session_lookup_valid),
      .lookup_job_id(session_lookup_job_id),
      .lookup_state(session_lookup_state)
  );

  prism_group_table #(
      .GROUPS(GROUPS),
      .NUM_PORTS(NUM_PORTS),
      .MAX_CONTRIBUTORS(MAX_CONTRIBUTORS),
      .MAX_REPLICATION_ENTRIES(MAX_REPLICATION_ENTRIES)
  ) u_group_table (
      .clk(clk),
      .rst_n(rst_n),
      .s_request(s_request),
      .s_contributors(s_contributors),
      .s_replication_entries(s_replication_entries),
      .s_request_valid(s_request_valid && (request_target == TARGET_GROUP)),
      .s_request_ready(group_request_ready),
      .request_session_valid(session_lookup_valid && (session_lookup_state == PRISM_SESSION_OPEN)),
      .request_session_job_id(session_lookup_job_id),
      .request_group_has_operations(request_group_has_operations),
      .m_result(group_result),
      .m_result_valid(group_result_valid),
      .m_result_ready(group_result_ready),
      .session_query_cookie(s_request.header.session_cookie),
      .session_has_groups(session_has_groups),
      .lookup_job_id(session_lookup_job_id),
      .lookup_group_id(s_request.group_id),
      .lookup_group_generation(s_request.group_generation),
      .lookup_valid(request_group_lookup_valid),
      .lookup_slot(request_group_lookup_slot),
      .lookup_state(request_group_lookup_state),
      .lookup_descriptor(request_group_lookup_descriptor),
      .contributor_lookup_slot(contributor_lookup_slot),
      .contributor_lookup_id(contributor_lookup_id),
      .contributor_lookup_valid(contributor_lookup_valid),
      .contributor_lookup_binding(contributor_lookup_binding),
      .replication_lookup_slot(replication_lookup_slot),
      .replication_lookup_index(replication_lookup_index),
      .replication_lookup_valid(replication_lookup_valid),
      .replication_lookup_entry(replication_lookup_entry),
      .replication_lookup_count(replication_lookup_count)
  );

  prism_operation_table #(
      .OPERATIONS(OPERATIONS),
      .MAX_RESULT_ROUTES(MAX_RESULT_ROUTES),
      .WIDTH_COUNT(WIDTH_COUNT),
      .WIDTH_0(WIDTH_0),
      .WIDTH_1(WIDTH_1),
      .WIDTH_2(WIDTH_2)
  ) u_operation_table (
      .clk(clk),
      .rst_n(rst_n),
      .s_request(s_request),
      .s_result_routes(s_result_routes),
      .s_request_valid(s_request_valid && (request_target == TARGET_OPERATION)),
      .s_request_ready(operation_request_ready),
      .request_session_valid(session_lookup_valid && (session_lookup_state == PRISM_SESSION_OPEN)),
      .request_session_job_id(session_lookup_job_id),
      .request_group_valid(request_group_lookup_valid),
      .request_group_slot(request_group_lookup_slot),
      .request_group_state(request_group_lookup_state),
      .request_group_expected_contributors(
          request_group_lookup_descriptor.expected_local_contributors),
      .m_result(operation_result),
      .m_result_valid(operation_result_valid),
      .m_result_ready(operation_result_ready),
      .group_query_slot(request_group_lookup_slot),
      .group_has_operations(request_group_has_operations),
      .lookup_key(operation_lookup_key),
      .lookup_valid(operation_lookup_valid),
      .lookup_slot(operation_lookup_slot),
      .lookup_state(operation_lookup_state),
      .lookup_descriptor(operation_lookup_descriptor),
      .lookup_group_slot(operation_lookup_group_slot),
      .lookup_expected_contributors(operation_lookup_expected_contributors),
      .lookup_selected_width(operation_lookup_selected_width),
      .lookup_width_index(operation_lookup_width_index),
      .lookup_accumulation_inexact(operation_lookup_accumulation_inexact),
      .route_lookup_slot(route_lookup_slot),
      .route_lookup_index(route_lookup_index),
      .route_lookup_valid(route_lookup_valid),
      .route_lookup_route(route_lookup_route),
      .complete_operation_valid(complete_operation_valid),
      .complete_operation_slot(complete_operation_slot)
  );

  // ---------------------------------------------------------------------------
  // Immediate commands and result arbitration
  // ---------------------------------------------------------------------------

  always_comb begin
    case (request_target)
      TARGET_SESSION: s_request_ready = session_request_ready;
      TARGET_GROUP: s_request_ready = group_request_ready;
      TARGET_OPERATION: s_request_ready = operation_request_ready;
      default: s_request_ready = !immediate_valid;
    endcase
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      immediate_valid <= 1'b0;
      immediate_result <= '0;
    end else begin
      if (immediate_valid && immediate_ready) immediate_valid <= 1'b0;
      if (s_request_valid && s_request_ready && (request_target == TARGET_IMMEDIATE)) begin
        immediate_result <= '0;
        immediate_result.header <= s_request.header;
        immediate_result.status <= s_request.decode_status;
        immediate_result.session_cookie <= s_request.header.session_cookie;
        immediate_result.device_boot_id <= DEVICE_BOOT_ID;
        if (s_request.decode_status == PRISM_STATUS_OK) begin
          case (s_request.header.command)
            PRISM_CMD_CAPS_QUERY: immediate_result.status <= PRISM_STATUS_OK;
            PRISM_CMD_RESOURCE_QUERY: begin
              if (!session_lookup_valid || (session_lookup_state != PRISM_SESSION_OPEN)) begin
                immediate_result.status <= PRISM_STATUS_STALE_SESSION;
              end
            end
            default: immediate_result.status <= PRISM_STATUS_UNSUPPORTED_COMMAND;
          endcase
        end
        immediate_valid <= 1'b1;
      end
    end
  end

  always_comb begin
    selected_result = '0;
    selected_valid = 1'b0;
    session_result_ready = 1'b0;
    group_result_ready = 1'b0;
    operation_result_ready = 1'b0;
    immediate_ready = 1'b0;
    if (session_result_valid) begin
      selected_result = session_result;
      selected_valid = 1'b1;
      session_result_ready = m_result_ready;
    end else if (group_result_valid) begin
      selected_result = group_result;
      selected_valid = 1'b1;
      group_result_ready = m_result_ready;
    end else if (operation_result_valid) begin
      selected_result = operation_result;
      selected_valid = 1'b1;
      operation_result_ready = m_result_ready;
    end else if (immediate_valid) begin
      selected_result = immediate_result;
      selected_valid = 1'b1;
      immediate_ready = m_result_ready;
    end

    response_command = response_for(selected_result.header.command);
    m_result = selected_result;
    m_result.header.command = response_command;
    m_result.header.flags = PRISM_CONTROL_FLAG_RESPONSE;
    m_result.header.status = selected_result.status;
    m_result.header.fragment_index = 0;
    m_result.header.fragment_count = 1;
    if ((selected_result.header.command == PRISM_CMD_SESSION_OPEN)
        && (selected_result.status == PRISM_STATUS_OK)) begin
      m_result.header.session_cookie = selected_result.session_cookie;
    end
    m_result_valid = selected_valid;
  end

endmodule
