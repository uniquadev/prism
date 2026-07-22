//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_pkg.sv
// Package: prism_pkg
// Description: Defines stable PRISM protocol constants, types, and shared helpers.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

package prism_pkg;

  // Constants in this section belong to the Protocol 1.0 wire ABI.
  localparam logic [3:0] PRISM_VERSION_MAJOR = 4'h1;
  localparam logic [3:0] PRISM_VERSION_MINOR = 4'h0;
  localparam logic [15:0] PRISM_ETHERTYPE = 16'h88B5;
  localparam int unsigned PRISM_ETH_MTU_BYTES = 1500;
  localparam int unsigned PRISM_ETH_HEADER_BYTES = 14;
  localparam int unsigned PRISM_CONTROL_WORD_BYTES = 2;
  localparam int unsigned PRISM_CONTROL_HEADER_BYTES = 24;
  localparam int unsigned PRISM_DATA_HEADER_BYTES = 24;
  localparam int unsigned PRISM_RESULT_HEADER_BYTES = 24;
  // ABI reservations are intentionally exposed before their packet paths are implemented.
  /* verilator lint_off UNUSEDPARAM */
  localparam int unsigned PRISM_PROGRESS_HEADER_BYTES = 40;
  /* verilator lint_on UNUSEDPARAM */
  localparam int unsigned PRISM_CHUNK_PAYLOAD_BYTES =
      PRISM_ETH_MTU_BYTES - PRISM_CONTROL_WORD_BYTES - PRISM_DATA_HEADER_BYTES;
  /* verilator lint_off UNUSEDPARAM */
  localparam int unsigned PRISM_MAX_FRAME_BYTES =
      PRISM_ETH_HEADER_BYTES + PRISM_ETH_MTU_BYTES;
  /* verilator lint_on UNUSEDPARAM */
  localparam int unsigned PRISM_MAX_CHUNKS = 1 << 24;

  typedef enum logic [7:0] {
    PRISM_OP_INVALID      = 8'h00,
    PRISM_OP_CONTROL      = 8'h01,
    PRISM_OP_COL_DATA     = 8'h02,
    PRISM_OP_COL_RES      = 8'h03,
    PRISM_OP_COL_PROGRESS = 8'h04
  } prism_opcode_e;

  typedef enum logic [7:0] {
    PRISM_FORMAT_INVALID = 8'h00,
    PRISM_FORMAT_INT8    = 8'h01,
    PRISM_FORMAT_FP16    = 8'h02,
    PRISM_FORMAT_BF16    = 8'h03,
    PRISM_FORMAT_FP32    = 8'h04
  } prism_wire_format_e;

  typedef enum logic [7:0] {
    PRISM_ACC_INVALID      = 8'h00,
    PRISM_ACC_FP32_ARRIVAL = 8'h01,
    PRISM_ACC_FP32_ORDERED = 8'h02,
    PRISM_ACC_KULISCH_FP32 = 8'h03
  } prism_accumulator_profile_e;

  typedef enum logic [7:0] {
    PRISM_SEMANTIC_INVALID   = 8'h00,
    PRISM_SEMANTIC_REDUCE    = 8'h01,
    PRISM_SEMANTIC_ALLREDUCE = 8'h02,
    PRISM_SEMANTIC_REDUCE_SCATTER = 8'h03
  } prism_collective_semantic_e;

  typedef enum logic [7:0] {
    PRISM_REDUCTION_INVALID = 8'h00,
    PRISM_REDUCTION_SUM     = 8'h01
  } prism_reduction_operator_e;

  typedef enum logic [7:0] {
    PRISM_ROLE_INVALID = 8'h00,
    PRISM_ROLE_LEAF    = 8'h01,
    PRISM_ROLE_INTERNAL = 8'h02,
    PRISM_ROLE_ROOT    = 8'h03,
    PRISM_ROLE_SINGLE  = 8'h04
  } prism_node_role_e;

  typedef enum logic [7:0] {
    PRISM_STATUS_OK                           = 8'h00,
    PRISM_STATUS_UNSUPPORTED_VERSION          = 8'h01,
    PRISM_STATUS_UNSUPPORTED_COMMAND          = 8'h02,
    PRISM_STATUS_UNSUPPORTED_FEATURE          = 8'h03,
    PRISM_STATUS_INVALID_REQUEST              = 8'h04,
    PRISM_STATUS_INVALID_RECORD               = 8'h05,
    PRISM_STATUS_INVALID_STATE                = 8'h06,
    PRISM_STATUS_AUTH_REQUIRED                = 8'h07,
    PRISM_STATUS_AUTH_FAILED                  = 8'h08,
    PRISM_STATUS_STALE_SESSION                = 8'h09,
    PRISM_STATUS_STALE_DEVICE_BOOT_ID         = 8'h0A,
    PRISM_STATUS_TXN_CONFLICT                 = 8'h0B,
    PRISM_STATUS_NOT_FOUND                    = 8'h0C,
    PRISM_STATUS_ALREADY_EXISTS               = 8'h0D,
    PRISM_STATUS_GENERATION_MISMATCH           = 8'h0E,
    PRISM_STATUS_GROUP_BUSY                    = 8'h0F,
    PRISM_STATUS_OPERATION_BUSY                = 8'h10,
    PRISM_STATUS_NO_GROUP_SLOT                = 8'h11,
    PRISM_STATUS_NO_OPERATION_SLOT            = 8'h12,
    PRISM_STATUS_NO_BITMAP_MEMORY             = 8'h13,
    PRISM_STATUS_NO_ACCUMULATOR_RANGE         = 8'h14,
    PRISM_STATUS_NO_REPLAY_BUFFER             = 8'h15,
    PRISM_STATUS_NO_ROUTE_RESOURCE            = 8'h16,
    PRISM_STATUS_NO_REPLICATION_RESOURCE      = 8'h17,
    PRISM_STATUS_UNSUPPORTED_ARITHMETIC_CONFIGURATION = 8'h18,
    PRISM_STATUS_BAD_PAYLOAD_LENGTH           = 8'h19,
    PRISM_STATUS_OUT_OF_WINDOW                = 8'h1A,
    PRISM_STATUS_RETRY                        = 8'h1B,
    PRISM_STATUS_TIMEOUT                      = 8'h1C,
    PRISM_STATUS_ABORTED                      = 8'h1D,
    PRISM_STATUS_INTERNAL_ERROR               = 8'h1E
  } prism_status_e;

  typedef enum logic [2:0] {
    PRISM_PACKET_DROP    = 3'd0,
    PRISM_PACKET_CONTROL = 3'd1,
    PRISM_PACKET_DATA    = 3'd2,
    PRISM_PACKET_RESULT  = 3'd3
  } prism_packet_class_e;

  typedef enum logic [15:0] {
    PRISM_CMD_INVALID                = 16'h0000,
    PRISM_CMD_CAPS_QUERY             = 16'h0001,
    PRISM_CMD_CAPS_RESPONSE          = 16'h0002,
    PRISM_CMD_RESOURCE_QUERY         = 16'h0003,
    PRISM_CMD_RESOURCE_RESPONSE      = 16'h0004,
    PRISM_CMD_SESSION_OPEN           = 16'h0010,
    PRISM_CMD_SESSION_OPEN_RESPONSE  = 16'h0011,
    PRISM_CMD_SESSION_RENEW          = 16'h0012,
    PRISM_CMD_SESSION_RENEW_RESPONSE = 16'h0013,
    PRISM_CMD_SESSION_CLOSE          = 16'h0014,
    PRISM_CMD_SESSION_CLOSE_RESPONSE = 16'h0015,
    PRISM_CMD_GROUP_STAGE            = 16'h0100,
    PRISM_CMD_GROUP_STAGE_RESPONSE   = 16'h0101,
    PRISM_CMD_GROUP_COMMIT           = 16'h0102,
    PRISM_CMD_GROUP_COMMIT_RESPONSE  = 16'h0103,
    PRISM_CMD_GROUP_ABORT            = 16'h0104,
    PRISM_CMD_GROUP_ABORT_RESPONSE   = 16'h0105,
    PRISM_CMD_GROUP_STATUS           = 16'h0106,
    PRISM_CMD_GROUP_STATUS_RESPONSE  = 16'h0107,
    PRISM_CMD_GROUP_DESTROY          = 16'h0108,
    PRISM_CMD_GROUP_DESTROY_RESPONSE = 16'h0109,
    PRISM_CMD_OP_PREPARE             = 16'h0200,
    PRISM_CMD_OP_PREPARE_RESPONSE    = 16'h0201,
    PRISM_CMD_OP_COMMIT              = 16'h0202,
    PRISM_CMD_OP_COMMIT_RESPONSE     = 16'h0203,
    PRISM_CMD_OP_ABORT               = 16'h0204,
    PRISM_CMD_OP_ABORT_RESPONSE      = 16'h0205,
    PRISM_CMD_OP_STATUS              = 16'h0206,
    PRISM_CMD_OP_STATUS_RESPONSE     = 16'h0207,
    PRISM_CMD_OP_RELEASE             = 16'h0208,
    PRISM_CMD_OP_RELEASE_RESPONSE    = 16'h0209,
    PRISM_CMD_OP_COMPLETE_EVENT      = 16'h0300,
    PRISM_CMD_OP_ERROR_EVENT         = 16'h0301,
    PRISM_CMD_RESOURCE_PRESSURE_EVENT = 16'h0302,
    PRISM_CMD_EVENT_ACK              = 16'h0303
  } prism_control_command_e;

  typedef enum logic [15:0] {
    PRISM_TLV_INVALID                = 16'h0000,
    PRISM_TLV_JOB_ID                 = 16'h0001,
    PRISM_TLV_DEVICE_BOOT_ID         = 16'h0002,
    PRISM_TLV_SESSION_COOKIE         = 16'h0003,
    PRISM_TLV_LEASE_MS               = 16'h0004,
    PRISM_TLV_LEASE_GRACE_MS         = 16'h0005,
    PRISM_TLV_SECURITY_PROFILE       = 16'h0006,
    PRISM_TLV_FEATURE_MASK           = 16'h0007,
    PRISM_TLV_PROTOCOL_VERSION_RANGE = 16'h0008,
    PRISM_TLV_CAPABILITIES           = 16'h0009,
    PRISM_TLV_RESOURCE_SNAPSHOT_ID   = 16'h000A,
    PRISM_TLV_RESOURCE_SNAPSHOT      = 16'h000B,
    PRISM_TLV_RESOURCE_RESERVATION   = 16'h000C,
    PRISM_TLV_PAYLOAD_DIGEST         = 16'h000D,
    PRISM_TLV_ERROR_DETAIL           = 16'h000E,
    PRISM_TLV_RELEASED_RESOURCES     = 16'h000F,
    PRISM_TLV_AUTH_DATA              = 16'h0010,
    PRISM_TLV_SESSION_USAGE          = 16'h0011,
    PRISM_TLV_GROUP_HANDLE           = 16'h0100,
    PRISM_TLV_GROUP_DESCRIPTOR       = 16'h0101,
    PRISM_TLV_CONTRIBUTOR_BINDING    = 16'h0102,
    PRISM_TLV_UPSTREAM_ACTION        = 16'h0103,
    PRISM_TLV_REPLICATION_GROUP      = 16'h0104,
    PRISM_TLV_GROUP_STATUS           = 16'h0105,
    PRISM_TLV_OPERATION_HANDLE       = 16'h0200,
    PRISM_TLV_OPERATION_DESCRIPTOR   = 16'h0201,
    PRISM_TLV_RESULT_ROUTE_RANGE     = 16'h0202,
    PRISM_TLV_GRANTED_RESOURCES      = 16'h0203,
    PRISM_TLV_OPERATION_STATUS       = 16'h0204,
    PRISM_TLV_PHASE_BITMAP_SUMMARY   = 16'h0205,
    PRISM_TLV_RETRY_POLICY           = 16'h0206,
    PRISM_TLV_EVENT_DETAIL           = 16'h0300
  } prism_tlv_type_e;

  typedef enum logic [15:0] {
    PRISM_CAP_INVALID                              = 16'h0000,
    PRISM_CAP_MAX_SESSIONS                         = 16'h0001,
    PRISM_CAP_MAX_INSTALLED_GROUPS                 = 16'h0002,
    PRISM_CAP_MAX_OPERATION_CONTEXTS               = 16'h0003,
    PRISM_CAP_MAX_ACTIVE_OPERATIONS_GLOBAL         = 16'h0004,
    PRISM_CAP_MAX_ACTIVE_OPERATIONS_PER_GROUP      = 16'h0005,
    PRISM_CAP_MAX_CHUNKS_PER_DIRECT_STREAM         = 16'h0006,
    PRISM_CAP_MAX_BITMAP_BYTES_PER_OPERATION       = 16'h0007,
    PRISM_CAP_TOTAL_PHASE_BITMAP_POOL_BYTES        = 16'h0008,
    PRISM_CAP_MAX_ACTIVE_ACCUMULATOR_RANGES_GLOBAL = 16'h0009,
    PRISM_CAP_MAX_ACTIVE_ACCUMULATOR_RANGES_PER_OP = 16'h000A,
    PRISM_CAP_TOTAL_REPLAY_OUTPUT_SLOTS             = 16'h000B,
    PRISM_CAP_MAX_LOCAL_CONTRIBUTORS                = 16'h000C,
    PRISM_CAP_MAX_REPLICATION_GROUPS                = 16'h000D,
    PRISM_CAP_MAX_RESULT_DESTINATIONS_PER_GROUP     = 16'h000E,
    PRISM_CAP_MAX_OPERATION_RESULT_ROUTE_RANGES     = 16'h000F,
    PRISM_CAP_MAX_MANAGEMENT_STAGING_BYTES          = 16'h0010,
    PRISM_CAP_MAX_SELECTIVE_ACK_WINDOW              = 16'h0011,
    PRISM_CAP_SUPPORTED_COLLECTIVE_SEMANTICS        = 16'h0012,
    PRISM_CAP_SUPPORTED_REDUCTION_OPERATORS         = 16'h0013,
    PRISM_CAP_SUPPORTED_INPUT_FORMATS               = 16'h0014,
    PRISM_CAP_SUPPORTED_ACCUMULATOR_PROFILES        = 16'h0015,
    PRISM_CAP_SUPPORTED_PARTIAL_FORMATS             = 16'h0016,
    PRISM_CAP_SUPPORTED_OUTPUT_FORMATS              = 16'h0017,
    PRISM_CAP_MTU_BYTES                             = 16'h0018,
    PRISM_CAP_MAX_PRISM_PAYLOAD_BYTES               = 16'h0019,
    PRISM_CAP_SUPPORTED_SECURITY_PROFILES           = 16'h001A,
    PRISM_CAP_SUPPORTED_RELIABILITY_FEATURES        = 16'h001B,
    PRISM_CAP_REPLAY_CACHE_DEPTH                    = 16'h001C,
    PRISM_CAP_REPLAY_CACHE_RETENTION_MS             = 16'h001D,
    PRISM_CAP_ACCUMULATOR_PROFILE_CAPABILITY        = 16'h001E
  } prism_capability_key_e;

  localparam logic [7:0] PRISM_CONTROL_FLAG_REQUEST = 8'h01;
  localparam logic [7:0] PRISM_CONTROL_FLAG_RESPONSE = 8'h02;
  localparam logic [7:0] PRISM_CONTROL_FLAG_EVENT = 8'h04;
  // Recognized ABI flags remain declared even when the prototype does not implement the action.
  /* verilator lint_off UNUSEDPARAM */
  localparam logic [7:0] PRISM_CONTROL_FLAG_ACK_REQUIRED = 8'h08;
  localparam logic [7:0] PRISM_CONTROL_FLAG_AUTH_PRESENT = 8'h10;
  /* verilator lint_on UNUSEDPARAM */
  localparam logic [7:0] PRISM_CONTROL_FLAG_KNOWN_MASK = 8'h1F;
  localparam logic [15:0] PRISM_TLV_FLAG_MANDATORY = 16'h0001;
  localparam logic [15:0] PRISM_TLV_FLAG_KNOWN_MASK = 16'h0001;

  typedef enum logic [2:0] {
    PRISM_TLV_EVENT_MESSAGE_START = 3'd0,
    PRISM_TLV_EVENT_RECORD_START  = 3'd1,
    PRISM_TLV_EVENT_VALUE_BYTE    = 3'd2,
    PRISM_TLV_EVENT_RECORD_END    = 3'd3,
    PRISM_TLV_EVENT_MESSAGE_END   = 3'd4
  } prism_tlv_event_kind_e;

  typedef enum logic [7:0] {
    PRISM_SESSION_CLOSED   = 8'h00,
    PRISM_SESSION_OPEN     = 8'h01,
    PRISM_SESSION_EXPIRING = 8'h02,
    PRISM_SESSION_ORPHANED = 8'h03
  } prism_session_state_e;

  typedef enum logic [7:0] {
    PRISM_GROUP_FREE       = 8'h00,
    PRISM_GROUP_STAGED     = 8'h01,
    PRISM_GROUP_INSTALLED  = 8'h02,
    PRISM_GROUP_DESTROYING = 8'h03
  } prism_group_state_e;

  typedef enum logic [7:0] {
    PRISM_OPERATION_FREE      = 8'h00,
    PRISM_OPERATION_PREPARED  = 8'h01,
    PRISM_OPERATION_ACTIVE    = 8'h02,
    PRISM_OPERATION_COMPLETE  = 8'h03,
    PRISM_OPERATION_RELEASING = 8'h04,
    PRISM_OPERATION_ABORTED   = 8'h05
  } prism_operation_state_e;

  /* verilator lint_off UNUSEDPARAM */
  localparam logic [7:0] PRISM_DATA_FLAG_RETRANSMIT = 8'h01;
  localparam logic [7:0] PRISM_DATA_FLAG_ACK_REQUIRED = 8'h02;
  /* verilator lint_on UNUSEDPARAM */
  localparam logic [7:0] PRISM_DATA_FLAG_LAST_CHUNK = 8'h04;
  // Approved laboratory extension; it remains sticky for the global interval.
  localparam logic [7:0] PRISM_DATA_FLAG_ACCUMULATION_INEXACT = 8'h08;
  localparam logic [7:0] PRISM_DATA_FLAG_KNOWN_MASK = 8'h0F;

  typedef struct packed {
    logic [63:0] job_id;
    logic [15:0] group_id;
    logic [15:0] group_generation;
    logic [15:0] operation_id;
    logic [31:0] operation_generation;
  } prism_operation_key_t;

  typedef struct packed {
    prism_operation_key_t key;
    logic [15:0] contributor_id;
    logic [23:0] chunk_index;
    logic [7:0] flags;
  } prism_data_header_t;

  typedef struct packed {
    prism_operation_key_t key;
    logic [15:0] result_path_id;
    logic [23:0] chunk_index;
    logic [7:0] flags;
  } prism_result_header_t;

  typedef struct packed {
    logic [63:0] session_cookie;
    logic [63:0] transaction_id;
    logic [15:0] command;
    logic [7:0] flags;
    logic [7:0] status;
    logic [15:0] fragment_index;
    logic [15:0] fragment_count;
    // Local metadata, not serialized in the PM_OP_CONTROL header.
    logic [47:0] source_mac;
    logic [47:0] destination_mac;
    logic [15:0] ingress_port;
  } prism_control_header_t;

  typedef struct packed {
    prism_tlv_event_kind_e kind;
    prism_control_header_t header;
    logic [15:0] record_type;
    logic [15:0] record_flags;
    logic [31:0] record_length;
    logic [7:0] value_byte;
    logic value_last;
    prism_status_e status;
  } prism_tlv_event_t;

  typedef struct packed {
    logic [15:0] contributor_id;
    logic [15:0] ingress_port;
    logic [47:0] source_mac;
  } prism_contributor_binding_t;

  typedef struct packed {
    prism_node_role_e node_role;
    logic [15:0] expected_local_contributors;
  } prism_group_descriptor_t;

  typedef struct packed {
    logic has_parent;
    logic [15:0] parent_contributor_id;
    logic [15:0] egress_port;
    logic [47:0] parent_mac;
  } prism_upstream_action_t;

  typedef struct packed {
    logic [23:0] chunk_first;
    logic [23:0] chunk_last;
    logic [15:0] replication_group_id;
  } prism_result_route_t;

  typedef struct packed {
    logic [15:0] replication_group_id;
    logic [15:0] result_path_id;
    logic [15:0] egress_port;
    logic [7:0] next_hop_type;
    logic [47:0] destination_mac;
  } prism_replication_entry_t;

  typedef struct packed {
    prism_collective_semantic_e semantic;
    prism_reduction_operator_e reduction_operator;
    prism_wire_format_e input_format;
    prism_accumulator_profile_e accumulator_profile;
    prism_wire_format_e partial_format;
    prism_wire_format_e output_format;
    logic result_delivery_role;
    logic [31:0] element_count;
    logic [31:0] maximum_reduction_terms;
    logic [31:0] timeout_ms;
    logic [15:0] requested_window_chunks;
    logic [15:0] requested_replay_slots;
    logic [15:0] result_route_count;
    logic [15:0] retry_limit;
  } prism_operation_descriptor_t;

  typedef struct packed {
    prism_control_header_t header;
    prism_status_e decode_status;
    logic [31:0] present;
    logic [63:0] job_id;
    logic [7:0] security_profile;
    logic [63:0] lease_ms;
    logic [15:0] group_id;
    logic [15:0] group_generation;
    prism_group_descriptor_t group_descriptor;
    prism_upstream_action_t upstream_action;
    logic [15:0] contributor_count;
    logic [15:0] replication_entry_count;
    logic [15:0] operation_id;
    logic [31:0] operation_generation;
    prism_operation_descriptor_t operation_descriptor;
    logic [15:0] result_route_count;
  } prism_control_request_t;

  typedef struct packed {
    prism_control_header_t header;
    prism_status_e status;
    logic [63:0] session_cookie;
    logic [63:0] device_boot_id;
    logic [63:0] lease_ms;
    logic [63:0] lease_grace_ms;
    logic [15:0] group_id;
    logic [15:0] group_generation;
    prism_group_state_e group_state;
    logic [15:0] operation_id;
    logic [31:0] operation_generation;
    prism_operation_state_e operation_state;
    logic [15:0] operation_slot;
    logic [15:0] selected_accumulator_width;
    logic accumulation_inexact;
  } prism_control_result_t;

  typedef struct packed {
    logic [15:0] operation_slot;
    logic [15:0] group_slot;
    prism_operation_descriptor_t descriptor;
    logic [15:0] selected_accumulator_width;
    logic [1:0] selected_width_index;
    logic accumulation_inexact;
    logic [15:0] expected_contributors;
  } prism_ingress_context_t;

  localparam int unsigned PRISM_PRESENT_JOB_ID = 0;
  localparam int unsigned PRISM_PRESENT_SECURITY_PROFILE = 1;
  localparam int unsigned PRISM_PRESENT_LEASE_MS = 2;
  localparam int unsigned PRISM_PRESENT_GROUP_HANDLE = 3;
  localparam int unsigned PRISM_PRESENT_GROUP_DESCRIPTOR = 4;
  localparam int unsigned PRISM_PRESENT_UPSTREAM_ACTION = 5;
  localparam int unsigned PRISM_PRESENT_OPERATION_HANDLE = 6;
  localparam int unsigned PRISM_PRESENT_OPERATION_DESCRIPTOR = 7;

  typedef struct packed {
    logic [47:0] destination_mac;
    logic [47:0] source_mac;
    logic [15:0] ethertype;
    logic [3:0] version_major;
    logic [3:0] version_minor;
    prism_opcode_e opcode;
    prism_control_header_t control;
    prism_data_header_t data;
    prism_result_header_t result;
    logic [15:0] ingress_port;
    logic fixed_header_valid;
  } prism_parsed_header_t;

  typedef struct packed {
    prism_parsed_header_t header;
    logic [15:0] frame_bytes;
    logic nonfinal_keep_error;
    logic final_keep_error;
    logic adapter_error;
  } prism_frame_desc_t;

  typedef struct packed {
    prism_operation_key_t key;
    logic [31:0] first_element;
    logic [15:0] contributor_id;
    logic [15:0] operation_slot;
    logic [15:0] group_slot;
    logic [15:0] expected_contributors;
    logic [7:0] input_format;
    logic [7:0] output_format;
    logic [7:0] accumulator_profile;
    logic [1:0] selected_width_index;
    logic [7:0] semantic;
    logic [31:0] total_element_count;
    logic [15:0] result_route_count;
    logic [7:0] element_count;
    logic [7:0] flags;
    logic last_tile;
  } prism_tile_meta_t;

  typedef struct packed {
    prism_operation_key_t key;
    logic [15:0] operation_slot;
    logic [15:0] group_slot;
    logic [7:0] semantic;
    logic [7:0] output_format;
    logic [15:0] result_route_count;
    logic [23:0] chunk_index;
    logic [23:0] total_chunks;
    logic [15:0] payload_bytes;
    logic accumulation_inexact;
  } prism_result_chunk_meta_t;

  typedef struct packed {
    logic [15:0] chunk_slot;
    prism_result_chunk_meta_t chunk;
    logic [15:0] result_path_id;
    logic [15:0] egress_port;
    logic [47:0] destination_mac;
  } prism_result_packet_job_t;

  typedef struct packed {
    logic invalid;
    logic overflow;
    logic underflow;
    logic inexact;
    logic canonical_nan;
    logic positive_infinity;
    logic negative_infinity;
    logic accumulation_inexact;
  } prism_math_status_t;

  function automatic int unsigned prism_clog2_safe(input int unsigned value);
    if (value <= 1) begin
      return 1;
    end
    return int'($clog2(value));
  endfunction

  function automatic int unsigned prism_ceil_div(
      input int unsigned numerator,
      input int unsigned denominator
  );
    if (denominator == 0) begin
      return 0;
    end
    return (numerator + denominator - 1) / denominator;
  endfunction

  function automatic int unsigned prism_bytes_per_element(
      input prism_wire_format_e format
  );
    case (format)
      PRISM_FORMAT_INT8: return 1;
      PRISM_FORMAT_FP16: return 2;
      PRISM_FORMAT_BF16: return 2;
      PRISM_FORMAT_FP32: return 4;
      default: return 0;
    endcase
  endfunction

  function automatic int unsigned prism_elements_per_chunk(
      input prism_wire_format_e format
  );
    int unsigned bytes_per_element;
    bytes_per_element = prism_bytes_per_element(format);
    if (bytes_per_element == 0) begin
      return 0;
    end
    return PRISM_CHUNK_PAYLOAD_BYTES / bytes_per_element;
  endfunction

  function automatic int unsigned prism_chunk_count(
      input int unsigned element_count,
      input prism_wire_format_e format
  );
    int unsigned elements_per_chunk;
    elements_per_chunk = prism_elements_per_chunk(format);
    if ((element_count == 0) || (elements_per_chunk == 0)) begin
      return 0;
    end
    return prism_ceil_div(element_count, elements_per_chunk);
  endfunction

  function automatic int unsigned prism_ceil_log2_terms(input logic [31:0] terms);
    logic [31:0] remaining;
    int unsigned result;
    if (terms <= 1) begin
      return 0;
    end
    remaining = terms - 1;
    result = 0;
    while (remaining != 0) begin
      remaining = remaining >> 1;
      result++;
    end
    return result;
  endfunction

  function automatic int unsigned prism_required_kulisch_width(
      input prism_wire_format_e format,
      input logic [31:0] maximum_terms
  );
    int unsigned base_width;
    case (format)
      PRISM_FORMAT_INT8: base_width = 8;
      PRISM_FORMAT_FP16: base_width = 41;
      PRISM_FORMAT_BF16: base_width = 262;
      PRISM_FORMAT_FP32: base_width = 278;
      default: base_width = 0;
    endcase
    if ((base_width == 0) || (maximum_terms == 0)) begin
      return 0;
    end
    return base_width + prism_ceil_log2_terms(maximum_terms);
  endfunction

  function automatic logic prism_keep_is_contiguous(
      input logic [63:0] keep,
      input int unsigned keep_width
  );
    logic seen_zero;
    seen_zero = 1'b0;
    prism_keep_is_contiguous = 1'b1;
    for (int unsigned index = 0; index < 64; index++) begin
      if (index < keep_width) begin
        if (!keep[index]) begin
          seen_zero = 1'b1;
        end else if (seen_zero) begin
          prism_keep_is_contiguous = 1'b0;
        end
      end
    end
  endfunction

endpackage
