//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_response_encoder.sv
// Module: prism_control_response_encoder
// Description: Encodes control results, capabilities, and resource snapshots as TLVs.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_response_encoder #(
    parameter int unsigned RESPONSE_BYTES = 1400,
    parameter int unsigned SESSIONS = 4,
    parameter int unsigned GROUPS = 8,
    parameter int unsigned OPERATIONS = 8,
    parameter int unsigned ACCUMULATOR_RANGES = 64,
    parameter int unsigned REPLAY_SLOTS = 64,
    parameter int unsigned MAX_CONTRIBUTORS = 2,
    parameter int unsigned MAX_REPLICATION_GROUPS = 2,
    parameter int unsigned MAX_DESTINATIONS_PER_GROUP = 2,
    parameter int unsigned MAX_RESULT_ROUTES = 2,
    parameter int unsigned MANAGEMENT_BYTES = 8192,
    parameter int unsigned WIDTH_COUNT = 3,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_control_result_t      s_result,
    input  logic                                  s_result_valid,
    output logic                                  s_result_ready,
    output prism_pkg::prism_control_header_t      m_header,
    output logic [15:0]                           m_payload_length,
    output logic                                  m_header_valid,
    input  logic                                  m_header_ready,
    output logic [7:0]                            m_byte,
    output logic                                  m_byte_last,
    output logic                                  m_byte_valid,
    input  logic                                  m_byte_ready
);

  import prism_pkg::*;

  logic [7:0] response_memory [0:RESPONSE_BYTES-1];
  prism_control_header_t header_reg;
  logic [15:0] payload_length_reg;
  logic [15:0] byte_index;
  logic active;
  logic header_sent;
  logic [63:0] snapshot_id;
  // Each command consumes a subset of the canonical result envelope.
  logic unused_result_fields;
  assign unused_result_fields = ^s_result;

  task automatic put_byte(inout integer cursor, input logic [7:0] value);
    response_memory[cursor] <= value;
    cursor = cursor + 1;
  endtask

  task automatic put_be16(inout integer cursor, input logic [15:0] value);
    put_byte(cursor, value[15:8]);
    put_byte(cursor, value[7:0]);
  endtask

  task automatic put_be32(inout integer cursor, input logic [31:0] value);
    put_byte(cursor, value[31:24]);
    put_byte(cursor, value[23:16]);
    put_byte(cursor, value[15:8]);
    put_byte(cursor, value[7:0]);
  endtask

  task automatic put_be64(inout integer cursor, input logic [63:0] value);
    put_be32(cursor, value[63:32]);
    put_be32(cursor, value[31:0]);
  endtask

  task automatic begin_tlv(
      inout integer cursor,
      input logic [15:0] record_type,
      input logic [31:0] value_length
  );
    put_be16(cursor, record_type);
    put_be16(cursor, PRISM_TLV_FLAG_MANDATORY);
    put_be32(cursor, value_length);
  endtask

  task automatic pad_tlv(inout integer cursor, input integer value_length);
    integer padding;
    padding = (-value_length) & 7;
    for (integer index = 0; index < 8; index = index + 1) begin
      if (index < padding) put_byte(cursor, 8'b0);
    end
  endtask

  task automatic append_u64_tlv(
      inout integer cursor,
      input logic [15:0] record_type,
      input logic [63:0] value
  );
    begin_tlv(cursor, record_type, 32'd8);
    put_be64(cursor, value);
  endtask

  task automatic append_group_handle(
      inout integer cursor,
      input logic [15:0] group_id,
      input logic [15:0] group_generation
  );
    begin_tlv(cursor, PRISM_TLV_GROUP_HANDLE, 32'd4);
    put_be16(cursor, group_id);
    put_be16(cursor, group_generation);
    pad_tlv(cursor, 4);
  endtask

  task automatic append_operation_handle(
      inout integer cursor,
      input logic [15:0] operation_id,
      input logic [31:0] operation_generation
  );
    begin_tlv(cursor, PRISM_TLV_OPERATION_HANDLE, 32'd6);
    put_be16(cursor, operation_id);
    put_be32(cursor, operation_generation);
    pad_tlv(cursor, 6);
  endtask

  task automatic append_entry(
      inout integer cursor,
      input logic [15:0] entry_key,
      input logic [63:0] entry_value
  );
    put_be16(cursor, entry_key);
    put_be16(cursor, 16'b0);
    put_be64(cursor, entry_value);
    put_be32(cursor, 32'b0);
  endtask

  task automatic append_capabilities(inout integer cursor);
    integer width_index_value;
    integer capability_entries;
    logic [63:0] profile_value;
    logic [15:0] width_value;
    capability_entries = 29 + 2 + WIDTH_COUNT;
    begin_tlv(cursor, PRISM_TLV_CAPABILITIES, 32'(capability_entries * 16));
    append_entry(cursor, PRISM_CAP_MAX_SESSIONS, 64'(SESSIONS));
    append_entry(cursor, PRISM_CAP_MAX_INSTALLED_GROUPS, 64'(GROUPS));
    append_entry(cursor, PRISM_CAP_MAX_OPERATION_CONTEXTS, 64'(OPERATIONS));
    append_entry(cursor, PRISM_CAP_MAX_ACTIVE_OPERATIONS_GLOBAL, 64'(OPERATIONS));
    append_entry(cursor, PRISM_CAP_MAX_ACTIVE_OPERATIONS_PER_GROUP, 64'(OPERATIONS));
    append_entry(cursor, PRISM_CAP_MAX_CHUNKS_PER_DIRECT_STREAM, 64'(PRISM_MAX_CHUNKS));
    append_entry(cursor, PRISM_CAP_MAX_BITMAP_BYTES_PER_OPERATION,
        64'(PRISM_MAX_CHUNKS / 4));
    append_entry(cursor, PRISM_CAP_TOTAL_PHASE_BITMAP_POOL_BYTES,
        64'(OPERATIONS) * (64'(PRISM_MAX_CHUNKS) / 64'd4));
    append_entry(cursor, PRISM_CAP_MAX_ACTIVE_ACCUMULATOR_RANGES_GLOBAL,
        64'(ACCUMULATOR_RANGES));
    append_entry(cursor, PRISM_CAP_MAX_ACTIVE_ACCUMULATOR_RANGES_PER_OP,
        64'(ACCUMULATOR_RANGES));
    append_entry(cursor, PRISM_CAP_TOTAL_REPLAY_OUTPUT_SLOTS, 64'(REPLAY_SLOTS));
    append_entry(cursor, PRISM_CAP_MAX_LOCAL_CONTRIBUTORS, 64'(MAX_CONTRIBUTORS));
    append_entry(cursor, PRISM_CAP_MAX_REPLICATION_GROUPS, 64'(MAX_REPLICATION_GROUPS));
    append_entry(cursor, PRISM_CAP_MAX_RESULT_DESTINATIONS_PER_GROUP,
        64'(MAX_DESTINATIONS_PER_GROUP));
    append_entry(cursor, PRISM_CAP_MAX_OPERATION_RESULT_ROUTE_RANGES,
        64'(MAX_RESULT_ROUTES));
    append_entry(cursor, PRISM_CAP_MAX_MANAGEMENT_STAGING_BYTES, 64'(MANAGEMENT_BYTES));
    append_entry(cursor, PRISM_CAP_MAX_SELECTIVE_ACK_WINDOW, 64'd64);
    append_entry(cursor, PRISM_CAP_SUPPORTED_COLLECTIVE_SEMANTICS,
        64'h0000_0000_0000_0006);
    append_entry(cursor, PRISM_CAP_SUPPORTED_REDUCTION_OPERATORS,
        64'h0000_0000_0000_0002);
    append_entry(cursor, PRISM_CAP_SUPPORTED_INPUT_FORMATS, 64'h0000_0000_0000_001E);
    append_entry(cursor, PRISM_CAP_SUPPORTED_ACCUMULATOR_PROFILES,
        64'h0000_0000_0000_000E);
    append_entry(cursor, PRISM_CAP_SUPPORTED_PARTIAL_FORMATS, 64'h0000_0000_0000_0010);
    append_entry(cursor, PRISM_CAP_SUPPORTED_OUTPUT_FORMATS, 64'h0000_0000_0000_001C);
    append_entry(cursor, PRISM_CAP_MTU_BYTES, 64'(PRISM_ETH_MTU_BYTES));
    append_entry(cursor, PRISM_CAP_MAX_PRISM_PAYLOAD_BYTES,
        64'(PRISM_CHUNK_PAYLOAD_BYTES));
    append_entry(cursor, PRISM_CAP_SUPPORTED_SECURITY_PROFILES, 64'h1);
    append_entry(cursor, PRISM_CAP_SUPPORTED_RELIABILITY_FEATURES, 64'h8);
    append_entry(cursor, PRISM_CAP_REPLAY_CACHE_DEPTH, 64'd64);
    append_entry(cursor, PRISM_CAP_REPLAY_CACHE_RETENTION_MS, 64'd10000);
    profile_value = (64'(PRISM_ACC_FP32_ARRIVAL) << 56) | (64'd32 << 40)
        | (64'hFFFF_FFFF << 8) | 64'd1;
    append_entry(cursor, PRISM_CAP_ACCUMULATOR_PROFILE_CAPABILITY, profile_value);
    profile_value = (64'(PRISM_ACC_FP32_ORDERED) << 56) | (64'd32 << 40)
        | (64'hFFFF_FFFF << 8) | 64'd1;
    append_entry(cursor, PRISM_CAP_ACCUMULATOR_PROFILE_CAPABILITY, profile_value);
    for (width_index_value = 0; width_index_value < WIDTH_COUNT;
        width_index_value = width_index_value + 1) begin
      case (width_index_value)
        0: width_value = 16'(WIDTH_0);
        1: width_value = 16'(WIDTH_1);
        default: width_value = 16'(WIDTH_2);
      endcase
      profile_value = (64'(PRISM_ACC_KULISCH_FP32) << 56) | (64'(width_value) << 40)
          | (64'hFFFF_FFFF << 8);
      append_entry(cursor, PRISM_CAP_ACCUMULATOR_PROFILE_CAPABILITY, profile_value);
    end
  endtask

  task automatic append_resource_snapshot(inout integer cursor, input logic [63:0] id);
    append_u64_tlv(cursor, PRISM_TLV_RESOURCE_SNAPSHOT_ID, id);
    begin_tlv(cursor, PRISM_TLV_RESOURCE_SNAPSHOT, 32'd240);
    append_entry(cursor, 16'h0001, 64'(GROUPS));
    append_entry(cursor, 16'h0002, 64'(OPERATIONS));
    append_entry(cursor, 16'h0003, 64'(OPERATIONS));
    append_entry(cursor, 16'h0004,
        64'(OPERATIONS) * (64'(PRISM_MAX_CHUNKS) / 64'd4));
    append_entry(cursor, 16'h0005, 64'(ACCUMULATOR_RANGES));
    append_entry(cursor, 16'h0006, 64'(REPLAY_SLOTS));
    append_entry(cursor, 16'h0007, 64'(MAX_RESULT_ROUTES * OPERATIONS));
    append_entry(cursor, 16'h0008, 64'(MAX_REPLICATION_GROUPS));
    append_entry(cursor, 16'h0009, 64'(MAX_REPLICATION_GROUPS * MAX_DESTINATIONS_PER_GROUP));
    append_entry(cursor, 16'h000A, 64'd0);
    append_entry(cursor, 16'h000B, 64'd0);
    append_entry(cursor, 16'h000C, 64'd0);
    append_entry(cursor, 16'h000D, 64'd0);
    append_entry(cursor, 16'h000E, 64'd0);
    append_entry(cursor, 16'h000F, 64'd0);
  endtask

  task automatic append_single_allocation(
      inout integer cursor,
      input logic [15:0] record_type,
      input logic [15:0] allocation_key
  );
    begin_tlv(cursor, record_type, 32'd16);
    append_entry(cursor, allocation_key, 64'd1);
  endtask

  task automatic append_transport_filler(inout integer cursor);
    put_be16(cursor, 16'hFFFE);
    put_be16(cursor, 16'b0);
    put_be32(cursor, 32'd12);
    for (integer index = 0; index < 12; index = index + 1) put_byte(cursor, 8'b0);
    pad_tlv(cursor, 12);
  endtask

  initial begin
    if ((RESPONSE_BYTES < 800) || (WIDTH_COUNT < 1) || (WIDTH_COUNT > 3)) begin
      $fatal(1, "prism_control_response_encoder parameters are illegal");
    end
  end

  assign s_result_ready = !active;
  assign m_header = header_reg;
  assign m_payload_length = payload_length_reg;
  assign m_header_valid = active && !header_sent;
  assign m_byte_valid = active && header_sent && (payload_length_reg != 0);
  assign m_byte = response_memory[byte_index[$clog2(RESPONSE_BYTES)-1:0]];
  assign m_byte_last = m_byte_valid && (byte_index + 1'b1 == payload_length_reg);

  always_ff @(posedge clk) begin : encode_response
    integer cursor;
    if (!rst_n) begin
      header_reg <= '0;
      payload_length_reg <= '0;
      byte_index <= '0;
      active <= 1'b0;
      header_sent <= 1'b0;
      snapshot_id <= '0;
    end else begin
      if (s_result_valid && s_result_ready) begin
        cursor = 0;
        header_reg <= s_result.header;
        byte_index <= '0;
        header_sent <= 1'b0;
        active <= 1'b1;
        if (s_result.status == PRISM_STATUS_OK) begin
          case (s_result.header.command)
            PRISM_CMD_CAPS_RESPONSE: begin
              append_u64_tlv(cursor, PRISM_TLV_DEVICE_BOOT_ID, s_result.device_boot_id);
              begin_tlv(cursor, PRISM_TLV_PROTOCOL_VERSION_RANGE, 32'd8);
              put_byte(cursor, {4'b0, PRISM_VERSION_MAJOR});
              put_byte(cursor, {4'b0, PRISM_VERSION_MINOR});
              put_byte(cursor, {4'b0, PRISM_VERSION_MAJOR});
              put_byte(cursor, {4'b0, PRISM_VERSION_MINOR});
              put_be32(cursor, 32'b0);
              append_u64_tlv(cursor, PRISM_TLV_FEATURE_MASK, 64'h0000_0000_0000_0008);
              append_capabilities(cursor);
            end
            PRISM_CMD_RESOURCE_RESPONSE: begin
              snapshot_id <= snapshot_id + 1'b1;
              append_resource_snapshot(cursor, snapshot_id + 1'b1);
            end
            PRISM_CMD_SESSION_OPEN_RESPONSE: begin
              append_u64_tlv(cursor, PRISM_TLV_SESSION_COOKIE, s_result.session_cookie);
              append_u64_tlv(cursor, PRISM_TLV_DEVICE_BOOT_ID, s_result.device_boot_id);
              append_u64_tlv(cursor, PRISM_TLV_LEASE_MS, s_result.lease_ms);
              append_u64_tlv(cursor, PRISM_TLV_LEASE_GRACE_MS, s_result.lease_grace_ms);
            end
            PRISM_CMD_SESSION_RENEW_RESPONSE:
              append_u64_tlv(cursor, PRISM_TLV_LEASE_MS, s_result.lease_ms);
            PRISM_CMD_GROUP_STAGE_RESPONSE: begin
              append_group_handle(
                  cursor, s_result.group_id, s_result.group_generation);
              append_single_allocation(cursor, PRISM_TLV_RESOURCE_RESERVATION, 16'h0001);
            end
            PRISM_CMD_GROUP_COMMIT_RESPONSE,
            PRISM_CMD_GROUP_STATUS_RESPONSE: begin
              append_group_handle(
                  cursor, s_result.group_id, s_result.group_generation);
              append_u64_tlv(cursor, PRISM_TLV_GROUP_STATUS, 64'(s_result.group_state));
            end
            PRISM_CMD_GROUP_DESTROY_RESPONSE: append_group_handle(
                cursor, s_result.group_id, s_result.group_generation);
            PRISM_CMD_OP_PREPARE_RESPONSE: begin
              append_operation_handle(
                  cursor, s_result.operation_id, s_result.operation_generation);
              append_single_allocation(cursor, PRISM_TLV_GRANTED_RESOURCES, 16'h0002);
            end
            PRISM_CMD_OP_COMMIT_RESPONSE,
            PRISM_CMD_OP_ABORT_RESPONSE,
            PRISM_CMD_OP_STATUS_RESPONSE: begin
              append_operation_handle(
                  cursor, s_result.operation_id, s_result.operation_generation);
              append_u64_tlv(cursor, PRISM_TLV_OPERATION_STATUS,
                  64'(s_result.operation_state));
            end
            PRISM_CMD_OP_RELEASE_RESPONSE: append_operation_handle(
                cursor, s_result.operation_id, s_result.operation_generation);
            default: begin end
          endcase
        end
        // An optional TLV prevents Ethernet padding from becoming ambiguous CONTROL payload.
        if (cursor < 20) append_transport_filler(cursor);
        payload_length_reg <= 16'(cursor);
      end

      if (m_header_valid && m_header_ready) begin
        header_sent <= 1'b1;
        if (payload_length_reg == 0) active <= 1'b0;
      end
      if (m_byte_valid && m_byte_ready) begin
        if (m_byte_last) begin
          active <= 1'b0;
          header_sent <= 1'b0;
        end else begin
          byte_index <= byte_index + 1'b1;
        end
      end
    end
  end

endmodule
