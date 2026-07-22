//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_stager.sv
// Module: prism_control_stager
// Description: Validates TLV events and builds one atomic typed control request.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_stager #(
    parameter int unsigned MAX_CONTRIBUTORS = 2,
    parameter int unsigned MAX_REPLICATION_ENTRIES = 2,
    parameter int unsigned MAX_RESULT_ROUTES = 2,
    parameter int unsigned MAX_RECORD_BYTES = 64
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_tlv_event_t               s_event,
    input  logic                                      s_event_valid,
    output logic                                      s_event_ready,
    output prism_pkg::prism_control_request_t         m_request,
    output prism_pkg::prism_contributor_binding_t     m_contributors [0:MAX_CONTRIBUTORS-1],
    output prism_pkg::prism_replication_entry_t       m_replication_entries [0:MAX_REPLICATION_ENTRIES-1],
    output prism_pkg::prism_result_route_t            m_result_routes [0:MAX_RESULT_ROUTES-1],
    output logic                                      m_request_valid,
    input  logic                                      m_request_ready
);

  import prism_pkg::*;

  localparam int unsigned CONTRIBUTOR_INDEX_WIDTH = prism_clog2_safe(MAX_CONTRIBUTORS);
  localparam int unsigned REPLICATION_INDEX_WIDTH = prism_clog2_safe(MAX_REPLICATION_ENTRIES);
  localparam int unsigned ROUTE_INDEX_WIDTH = prism_clog2_safe(MAX_RESULT_ROUTES);

  prism_control_request_t request_reg;
  prism_contributor_binding_t contributor_reg [0:MAX_CONTRIBUTORS-1];
  prism_replication_entry_t replication_reg [0:MAX_REPLICATION_ENTRIES-1];
  prism_result_route_t route_reg [0:MAX_RESULT_ROUTES-1];
  logic [7:0] record_bytes [0:MAX_RECORD_BYTES-1];
  logic [31:0] value_index;
  logic [15:0] current_type;
  logic [31:0] current_length;
  logic current_allowed;
  logic current_known;
  prism_status_e staging_status;

  function automatic logic [15:0] read_be16(input int unsigned offset);
    return {record_bytes[offset], record_bytes[offset + 1]};
  endfunction

  function automatic logic [23:0] read_be24(input int unsigned offset);
    return {record_bytes[offset], record_bytes[offset + 1], record_bytes[offset + 2]};
  endfunction

  function automatic logic [31:0] read_be32(input int unsigned offset);
    return {record_bytes[offset], record_bytes[offset + 1],
        record_bytes[offset + 2], record_bytes[offset + 3]};
  endfunction

  function automatic logic [47:0] read_be48(input int unsigned offset);
    return {record_bytes[offset], record_bytes[offset + 1],
        record_bytes[offset + 2], record_bytes[offset + 3],
        record_bytes[offset + 4], record_bytes[offset + 5]};
  endfunction

  function automatic logic [63:0] read_be64(input int unsigned offset);
    return {record_bytes[offset], record_bytes[offset + 1],
        record_bytes[offset + 2], record_bytes[offset + 3],
        record_bytes[offset + 4], record_bytes[offset + 5],
        record_bytes[offset + 6], record_bytes[offset + 7]};
  endfunction

  function automatic logic known_type(input logic [15:0] record_type);
    case (record_type)
      PRISM_TLV_JOB_ID,
      PRISM_TLV_DEVICE_BOOT_ID,
      PRISM_TLV_SESSION_COOKIE,
      PRISM_TLV_LEASE_MS,
      PRISM_TLV_LEASE_GRACE_MS,
      PRISM_TLV_SECURITY_PROFILE,
      PRISM_TLV_FEATURE_MASK,
      PRISM_TLV_PROTOCOL_VERSION_RANGE,
      PRISM_TLV_CAPABILITIES,
      PRISM_TLV_RESOURCE_SNAPSHOT_ID,
      PRISM_TLV_RESOURCE_SNAPSHOT,
      PRISM_TLV_RESOURCE_RESERVATION,
      PRISM_TLV_PAYLOAD_DIGEST,
      PRISM_TLV_ERROR_DETAIL,
      PRISM_TLV_RELEASED_RESOURCES,
      PRISM_TLV_AUTH_DATA,
      PRISM_TLV_SESSION_USAGE,
      PRISM_TLV_GROUP_HANDLE,
      PRISM_TLV_GROUP_DESCRIPTOR,
      PRISM_TLV_CONTRIBUTOR_BINDING,
      PRISM_TLV_UPSTREAM_ACTION,
      PRISM_TLV_REPLICATION_GROUP,
      PRISM_TLV_GROUP_STATUS,
      PRISM_TLV_OPERATION_HANDLE,
      PRISM_TLV_OPERATION_DESCRIPTOR,
      PRISM_TLV_RESULT_ROUTE_RANGE,
      PRISM_TLV_GRANTED_RESOURCES,
      PRISM_TLV_OPERATION_STATUS,
      PRISM_TLV_PHASE_BITMAP_SUMMARY,
      PRISM_TLV_RETRY_POLICY,
      PRISM_TLV_EVENT_DETAIL: return 1'b1;
      default: return 1'b0;
    endcase
  endfunction

  function automatic logic supported_request(input logic [15:0] command);
    case (command)
      PRISM_CMD_CAPS_QUERY,
      PRISM_CMD_RESOURCE_QUERY,
      PRISM_CMD_SESSION_OPEN,
      PRISM_CMD_SESSION_RENEW,
      PRISM_CMD_SESSION_CLOSE,
      PRISM_CMD_GROUP_STAGE,
      PRISM_CMD_GROUP_COMMIT,
      PRISM_CMD_GROUP_ABORT,
      PRISM_CMD_GROUP_STATUS,
      PRISM_CMD_GROUP_DESTROY,
      PRISM_CMD_OP_PREPARE,
      PRISM_CMD_OP_COMMIT,
      PRISM_CMD_OP_ABORT,
      PRISM_CMD_OP_STATUS,
      PRISM_CMD_OP_RELEASE,
      PRISM_CMD_EVENT_ACK: return 1'b1;
      default: return 1'b0;
    endcase
  endfunction

  function automatic logic record_allowed(
      input logic [15:0] command,
      input logic [15:0] record_type
  );
    case (command)
      PRISM_CMD_CAPS_QUERY:
        return record_type == PRISM_TLV_SECURITY_PROFILE;
      PRISM_CMD_RESOURCE_QUERY:
        return (record_type == PRISM_TLV_GROUP_HANDLE)
            || (record_type == PRISM_TLV_OPERATION_HANDLE);
      PRISM_CMD_SESSION_OPEN:
        return (record_type == PRISM_TLV_JOB_ID)
            || (record_type == PRISM_TLV_SECURITY_PROFILE)
            || (record_type == PRISM_TLV_AUTH_DATA)
            || (record_type == PRISM_TLV_LEASE_MS);
      PRISM_CMD_SESSION_RENEW:
        return (record_type == PRISM_TLV_LEASE_MS)
            || (record_type == PRISM_TLV_AUTH_DATA);
      PRISM_CMD_SESSION_CLOSE: return 1'b0;
      PRISM_CMD_GROUP_STAGE:
        return (record_type == PRISM_TLV_GROUP_HANDLE)
            || (record_type == PRISM_TLV_GROUP_DESCRIPTOR)
            || (record_type == PRISM_TLV_CONTRIBUTOR_BINDING)
            || (record_type == PRISM_TLV_UPSTREAM_ACTION)
            || (record_type == PRISM_TLV_REPLICATION_GROUP);
      PRISM_CMD_GROUP_COMMIT,
      PRISM_CMD_GROUP_ABORT,
      PRISM_CMD_GROUP_STATUS,
      PRISM_CMD_GROUP_DESTROY:
        return record_type == PRISM_TLV_GROUP_HANDLE;
      PRISM_CMD_OP_PREPARE:
        return (record_type == PRISM_TLV_GROUP_HANDLE)
            || (record_type == PRISM_TLV_OPERATION_HANDLE)
            || (record_type == PRISM_TLV_OPERATION_DESCRIPTOR)
            || (record_type == PRISM_TLV_RESULT_ROUTE_RANGE)
            || (record_type == PRISM_TLV_RETRY_POLICY);
      PRISM_CMD_OP_COMMIT,
      PRISM_CMD_OP_ABORT,
      PRISM_CMD_OP_STATUS,
      PRISM_CMD_OP_RELEASE:
        return record_type == PRISM_TLV_OPERATION_HANDLE;
      PRISM_CMD_EVENT_ACK: return record_type == PRISM_TLV_EVENT_DETAIL;
      default: return 1'b0;
    endcase
  endfunction

  function automatic logic repeatable_type(input logic [15:0] record_type);
    return (record_type == PRISM_TLV_CONTRIBUTOR_BINDING)
        || (record_type == PRISM_TLV_REPLICATION_GROUP)
        || (record_type == PRISM_TLV_RESULT_ROUTE_RANGE);
  endfunction

  function automatic logic already_present(
      input logic [31:0] present,
      input logic [15:0] record_type
  );
    case (record_type)
      PRISM_TLV_JOB_ID: return present[PRISM_PRESENT_JOB_ID];
      PRISM_TLV_SECURITY_PROFILE: return present[PRISM_PRESENT_SECURITY_PROFILE];
      PRISM_TLV_LEASE_MS: return present[PRISM_PRESENT_LEASE_MS];
      PRISM_TLV_GROUP_HANDLE: return present[PRISM_PRESENT_GROUP_HANDLE];
      PRISM_TLV_GROUP_DESCRIPTOR: return present[PRISM_PRESENT_GROUP_DESCRIPTOR];
      PRISM_TLV_UPSTREAM_ACTION: return present[PRISM_PRESENT_UPSTREAM_ACTION];
      PRISM_TLV_OPERATION_HANDLE: return present[PRISM_PRESENT_OPERATION_HANDLE];
      PRISM_TLV_OPERATION_DESCRIPTOR: return present[PRISM_PRESENT_OPERATION_DESCRIPTOR];
      default: return 1'b0;
    endcase
  endfunction

  function automatic logic mandatory_present(
      input logic [15:0] command,
      input logic [31:0] present
  );
    case (command)
      PRISM_CMD_CAPS_QUERY,
      PRISM_CMD_RESOURCE_QUERY,
      PRISM_CMD_SESSION_RENEW,
      PRISM_CMD_SESSION_CLOSE: return 1'b1;
      PRISM_CMD_SESSION_OPEN:
        return present[PRISM_PRESENT_JOB_ID]
            && present[PRISM_PRESENT_SECURITY_PROFILE];
      PRISM_CMD_GROUP_STAGE:
        return present[PRISM_PRESENT_GROUP_HANDLE]
            && present[PRISM_PRESENT_GROUP_DESCRIPTOR]
            && present[PRISM_PRESENT_UPSTREAM_ACTION];
      PRISM_CMD_GROUP_COMMIT,
      PRISM_CMD_GROUP_ABORT,
      PRISM_CMD_GROUP_STATUS,
      PRISM_CMD_GROUP_DESTROY:
        return present[PRISM_PRESENT_GROUP_HANDLE];
      PRISM_CMD_OP_PREPARE:
        return present[PRISM_PRESENT_GROUP_HANDLE]
            && present[PRISM_PRESENT_OPERATION_HANDLE]
            && present[PRISM_PRESENT_OPERATION_DESCRIPTOR];
      PRISM_CMD_OP_COMMIT,
      PRISM_CMD_OP_ABORT,
      PRISM_CMD_OP_STATUS,
      PRISM_CMD_OP_RELEASE:
        return present[PRISM_PRESENT_OPERATION_HANDLE];
      PRISM_CMD_EVENT_ACK: return 1'b1;
      default: return 1'b0;
    endcase
  endfunction

  initial begin
    if ((MAX_CONTRIBUTORS < 1) || (MAX_REPLICATION_ENTRIES < 1)
        || (MAX_RESULT_ROUTES < 1) || (MAX_RECORD_BYTES < 32)) begin
      $fatal(1, "prism_control_stager parameters are illegal");
    end
  end

  assign s_event_ready = !m_request_valid;
  assign m_request = request_reg;
  for (genvar contributor = 0; contributor < MAX_CONTRIBUTORS; contributor++) begin : gen_contributors
    assign m_contributors[contributor] = contributor_reg[contributor];
  end
  for (genvar entry = 0; entry < MAX_REPLICATION_ENTRIES; entry++) begin : gen_replication
    assign m_replication_entries[entry] = replication_reg[entry];
  end
  for (genvar route = 0; route < MAX_RESULT_ROUTES; route++) begin : gen_routes
    assign m_result_routes[route] = route_reg[route];
  end

  always_ff @(posedge clk) begin : stage_events
    if (!rst_n) begin
      request_reg <= '0;
      value_index <= '0;
      current_type <= '0;
      current_length <= '0;
      current_allowed <= 1'b0;
      current_known <= 1'b0;
      staging_status <= PRISM_STATUS_OK;
      m_request_valid <= 1'b0;
      for (int unsigned index = 0; index < MAX_CONTRIBUTORS; index++) begin
        contributor_reg[index] <= '0;
      end
      for (int unsigned index = 0; index < MAX_REPLICATION_ENTRIES; index++) begin
        replication_reg[index] <= '0;
      end
      for (int unsigned index = 0; index < MAX_RESULT_ROUTES; index++) begin
        route_reg[index] <= '0;
      end
    end else begin
      if (m_request_valid && m_request_ready) begin
        m_request_valid <= 1'b0;
      end

      if (s_event_valid && s_event_ready) begin
        case (s_event.kind)
          PRISM_TLV_EVENT_MESSAGE_START: begin
            request_reg <= '0;
            request_reg.header <= s_event.header;
            value_index <= '0;
            staging_status <= PRISM_STATUS_OK;
            if (!supported_request(s_event.header.command)) begin
              staging_status <= PRISM_STATUS_UNSUPPORTED_COMMAND;
            end else if ((s_event.header.flags & PRISM_CONTROL_FLAG_REQUEST) == 0
                || s_event.header.status != PRISM_STATUS_OK) begin
              staging_status <= PRISM_STATUS_INVALID_REQUEST;
            end
          end

          PRISM_TLV_EVENT_RECORD_START: begin
            current_type <= s_event.record_type;
            current_length <= s_event.record_length;
            current_known <= known_type(s_event.record_type);
            current_allowed <= record_allowed(request_reg.header.command, s_event.record_type);
            value_index <= '0;
            if ((!known_type(s_event.record_type)
                    || !record_allowed(request_reg.header.command, s_event.record_type))
                && ((s_event.record_flags & PRISM_TLV_FLAG_MANDATORY) != 0)) begin
              staging_status <= PRISM_STATUS_INVALID_RECORD;
            end else if (record_allowed(request_reg.header.command, s_event.record_type)
                && already_present(request_reg.present, s_event.record_type)
                && !repeatable_type(s_event.record_type)) begin
              staging_status <= PRISM_STATUS_INVALID_RECORD;
            end
          end

          PRISM_TLV_EVENT_VALUE_BYTE: begin
            if (value_index < MAX_RECORD_BYTES) begin
              record_bytes[value_index] <= s_event.value_byte;
            end else begin
              staging_status <= PRISM_STATUS_INVALID_RECORD;
            end
            if (s_event.value_last != (value_index == (current_length - 1'b1))) begin
              staging_status <= PRISM_STATUS_INVALID_RECORD;
            end
            value_index <= value_index + 1'b1;
          end

          PRISM_TLV_EVENT_RECORD_END: begin
            if (current_known && current_allowed) begin
              case (current_type)
                PRISM_TLV_JOB_ID: begin
                  if (current_length != 8) staging_status <= PRISM_STATUS_INVALID_RECORD;
                  else begin
                    request_reg.job_id <= read_be64(0);
                    request_reg.present[PRISM_PRESENT_JOB_ID] <= 1'b1;
                  end
                end
                PRISM_TLV_SECURITY_PROFILE: begin
                  if ((current_length != 8) || (read_be64(0) > 2)) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    request_reg.security_profile <= 8'(read_be64(0));
                    request_reg.present[PRISM_PRESENT_SECURITY_PROFILE] <= 1'b1;
                  end
                end
                PRISM_TLV_LEASE_MS: begin
                  if ((current_length != 8) || (read_be64(0) == 0)) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    request_reg.lease_ms <= read_be64(0);
                    request_reg.present[PRISM_PRESENT_LEASE_MS] <= 1'b1;
                  end
                end
                PRISM_TLV_GROUP_HANDLE: begin
                  if (current_length != 4) staging_status <= PRISM_STATUS_INVALID_RECORD;
                  else begin
                    request_reg.group_id <= read_be16(0);
                    request_reg.group_generation <= read_be16(2);
                    request_reg.present[PRISM_PRESENT_GROUP_HANDLE] <= 1'b1;
                  end
                end
                PRISM_TLV_GROUP_DESCRIPTOR: begin
                  if ((current_length != 8) || (record_bytes[1] != 0)
                      || (read_be32(4) != 0) || (read_be16(2) == 0)
                      || (record_bytes[0] == PRISM_ROLE_INVALID)) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    request_reg.group_descriptor.node_role <= prism_node_role_e'(record_bytes[0]);
                    request_reg.group_descriptor.expected_local_contributors <= read_be16(2);
                    request_reg.present[PRISM_PRESENT_GROUP_DESCRIPTOR] <= 1'b1;
                  end
                end
                PRISM_TLV_CONTRIBUTOR_BINDING: begin
                  if ((current_length != 12) || (read_be16(10) != 0)
                      || (request_reg.contributor_count >= 16'(MAX_CONTRIBUTORS))
                      || (read_be16(0) != request_reg.contributor_count)) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    contributor_reg[CONTRIBUTOR_INDEX_WIDTH'(request_reg.contributor_count)] <= '{
                      contributor_id: read_be16(0),
                      ingress_port: read_be16(2),
                      source_mac: read_be48(4)
                    };
                    request_reg.contributor_count <= request_reg.contributor_count + 1'b1;
                  end
                end
                PRISM_TLV_UPSTREAM_ACTION: begin
                  if ((current_length != 16) || (record_bytes[0] > 1)
                      || (record_bytes[1] != 0) || (read_be32(12) != 0)) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    request_reg.upstream_action <= '{
                      has_parent: record_bytes[0][0],
                      parent_contributor_id: read_be16(2),
                      egress_port: read_be16(4),
                      parent_mac: read_be48(6)
                    };
                    request_reg.present[PRISM_PRESENT_UPSTREAM_ACTION] <= 1'b1;
                  end
                end
                PRISM_TLV_REPLICATION_GROUP: begin
                  if ((current_length < 20) || (read_be16(2) == 0)
                      || (read_be32(4) != 0)
                      || (current_length != (32'd8 + (32'(read_be16(2)) * 32'd12)))
                      || (({1'b0, request_reg.replication_entry_count}
                          + {1'b0, read_be16(2)}) > 17'(MAX_REPLICATION_ENTRIES))) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    for (int unsigned item = 0; item < MAX_REPLICATION_ENTRIES; item++) begin
                      if (item < read_be16(2)) begin
                        if ((record_bytes[8 + item * 12 + 4] == 0)
                            || (record_bytes[8 + item * 12 + 5] != 0)) begin
                          staging_status <= PRISM_STATUS_INVALID_RECORD;
                        end
                        replication_reg[REPLICATION_INDEX_WIDTH'(
                            request_reg.replication_entry_count + 16'(item))] <= '{
                          replication_group_id: read_be16(0),
                          result_path_id: read_be16(8 + item * 12),
                          egress_port: read_be16(10 + item * 12),
                          next_hop_type: record_bytes[12 + item * 12],
                          destination_mac: read_be48(14 + item * 12)
                        };
                      end
                    end
                    request_reg.replication_entry_count <=
                        request_reg.replication_entry_count + read_be16(2);
                  end
                end
                PRISM_TLV_OPERATION_HANDLE: begin
                  if (current_length != 6) staging_status <= PRISM_STATUS_INVALID_RECORD;
                  else begin
                    request_reg.operation_id <= read_be16(0);
                    request_reg.operation_generation <= read_be32(2);
                    request_reg.present[PRISM_PRESENT_OPERATION_HANDLE] <= 1'b1;
                  end
                end
                PRISM_TLV_OPERATION_DESCRIPTOR: begin
                  if ((current_length != 32) || (record_bytes[7] != 0)
                      || (read_be32(28) != 0) || ((record_bytes[6] & 8'hFE) != 0)
                      || !((record_bytes[0] == PRISM_SEMANTIC_REDUCE)
                          || (record_bytes[0] == PRISM_SEMANTIC_ALLREDUCE))
                      || (record_bytes[1] != PRISM_REDUCTION_SUM)
                      || (prism_bytes_per_element(prism_wire_format_e'(record_bytes[2])) == 0)
                      || (record_bytes[3] < PRISM_ACC_FP32_ARRIVAL)
                      || (record_bytes[3] > PRISM_ACC_KULISCH_FP32)
                      || (record_bytes[4] != PRISM_FORMAT_FP32)
                      || (prism_bytes_per_element(prism_wire_format_e'(record_bytes[5])) == 0)
                      || (record_bytes[5] == PRISM_FORMAT_INT8)
                      || (read_be32(8) == 0) || (read_be32(12) == 0)
                      || (read_be32(16) == 0) || (read_be16(20) == 0)
                      || (read_be16(22) == 0)) begin
                    staging_status <= PRISM_STATUS_UNSUPPORTED_ARITHMETIC_CONFIGURATION;
                  end else begin
                    request_reg.operation_descriptor <= '{
                      semantic: prism_collective_semantic_e'(record_bytes[0]),
                      reduction_operator: prism_reduction_operator_e'(record_bytes[1]),
                      input_format: prism_wire_format_e'(record_bytes[2]),
                      accumulator_profile: prism_accumulator_profile_e'(record_bytes[3]),
                      partial_format: prism_wire_format_e'(record_bytes[4]),
                      output_format: prism_wire_format_e'(record_bytes[5]),
                      result_delivery_role: record_bytes[6][0],
                      element_count: read_be32(8),
                      maximum_reduction_terms: read_be32(12),
                      timeout_ms: read_be32(16),
                      requested_window_chunks: read_be16(20),
                      requested_replay_slots: read_be16(22),
                      result_route_count: read_be16(24),
                      retry_limit: read_be16(26)
                    };
                    request_reg.present[PRISM_PRESENT_OPERATION_DESCRIPTOR] <= 1'b1;
                  end
                end
                PRISM_TLV_RESULT_ROUTE_RANGE: begin
                  if ((current_length != 8)
                      || (request_reg.result_route_count >= 16'(MAX_RESULT_ROUTES))
                      || (read_be24(0) > read_be24(3))) begin
                    staging_status <= PRISM_STATUS_INVALID_RECORD;
                  end else begin
                    route_reg[ROUTE_INDEX_WIDTH'(request_reg.result_route_count)] <= '{
                      chunk_first: read_be24(0),
                      chunk_last: read_be24(3),
                      replication_group_id: read_be16(6)
                    };
                    request_reg.result_route_count <= request_reg.result_route_count + 1'b1;
                  end
                end
                default: begin end
              endcase
            end
          end

          PRISM_TLV_EVENT_MESSAGE_END: begin
            if (s_event.status != PRISM_STATUS_OK) begin
              request_reg.decode_status <= s_event.status;
            end else if (staging_status != PRISM_STATUS_OK) begin
              request_reg.decode_status <= staging_status;
            end else if (!mandatory_present(request_reg.header.command, request_reg.present)) begin
              request_reg.decode_status <= PRISM_STATUS_INVALID_REQUEST;
            end else if (request_reg.present[PRISM_PRESENT_GROUP_DESCRIPTOR]
                && (request_reg.group_descriptor.expected_local_contributors
                    != request_reg.contributor_count)) begin
              request_reg.decode_status <= PRISM_STATUS_INVALID_RECORD;
            end else if (request_reg.present[PRISM_PRESENT_OPERATION_DESCRIPTOR]
                && (request_reg.operation_descriptor.result_route_count
                    != request_reg.result_route_count)) begin
              request_reg.decode_status <= PRISM_STATUS_INVALID_RECORD;
            end else begin
              request_reg.decode_status <= PRISM_STATUS_OK;
            end
            m_request_valid <= 1'b1;
          end

          default: begin end
        endcase
      end
    end
  end

endmodule
