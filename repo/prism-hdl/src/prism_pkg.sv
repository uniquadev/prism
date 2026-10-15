//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_pkg.sv
// Package: prism_pkg
// Description: Defines the NumberGroup wire registry and shared RTL types.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

package prism_pkg;

  localparam logic [3:0] PRISM_VERSION_MAJOR = 4'h2;
  localparam logic [3:0] PRISM_VERSION_MINOR = 4'h0;
  localparam logic [15:0] PRISM_ETHERTYPE = 16'h88B5;
  localparam int unsigned PRISM_ETH_MTU_BYTES = 1500;
  localparam int unsigned PRISM_ETH_HEADER_BYTES = 14;
  localparam int unsigned PRISM_CONTROL_WORD_BYTES = 2;
  localparam int unsigned PRISM_CONTROL_HEADER_BYTES = 32;
  localparam int unsigned PRISM_DATA_HEADER_BYTES = 40;
  localparam int unsigned PRISM_RESULT_HEADER_BYTES = 40;
  localparam int unsigned PRISM_NUMBERGROUP_DESCRIPTOR_BYTES = 4;
  localparam int unsigned PRISM_CONTEXT_FIXED_BYTES = 48;
  localparam int unsigned PRISM_ENDPOINT_BINDING_BYTES = 24;
  localparam int unsigned PRISM_PROGRESS_HEADER_BYTES = 44;

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
    PRISM_FORMAT_FP32    = 8'h04,
    PRISM_FORMAT_KULISCH = 8'h80
  } prism_wire_format_e;

  // Profile IDs are wire values, not positions in a bit mask. The SINGLE
  // control parser accepts only its implemented tuples.
  typedef enum logic [7:0] {
    PRISM_ACC_INVALID       = 8'h00,
    PRISM_ACC_FP32_ARRIVAL  = 8'h01,
    PRISM_ACC_KULISCH_FIXED = 8'h80
  } prism_accumulator_profile_e;

  typedef enum logic [7:0] {
    PRISM_SEMANTIC_INVALID        = 8'h00,
    PRISM_SEMANTIC_REDUCE         = 8'h01,
    PRISM_SEMANTIC_ALLREDUCE      = 8'h02,
    PRISM_SEMANTIC_REDUCE_SCATTER = 8'h03
  } prism_collective_semantic_e;

  localparam logic [7:0] PRISM_DATA_FLAG_LAST = 8'h01;
  localparam logic [7:0] PRISM_DATA_FLAG_ACCUMULATION_INEXACT = 8'h02;

  typedef struct packed {
    logic [63:0] job_id;
    logic [15:0] group_id;
    logic [15:0] group_generation;
    logic [15:0] operation_id;
    logic [31:0] operation_generation;
  } prism_operation_key_t;

  typedef struct packed {
    logic [47:0] destination_mac;
    logic [47:0] source_mac;
    logic [15:0] ethertype;
    logic [7:0] version;
    prism_opcode_e packet_class;
    prism_operation_key_t key;
    logic [15:0] source_endpoint;
    logic [15:0] destination_endpoint;
    logic [31:0] packet_id;
    logic [31:0] first_element;
    logic [15:0] element_count;
    logic [7:0] group_count;
    logic [7:0] flags;
    logic [15:0] body_bytes;
    logic [15:0] stream_id;
    logic [15:0] reserved;
    logic [15:0] ingress_port;
    logic fixed_header_valid;
  } prism_numbergroup_header_t;

  typedef struct packed {
    logic [47:0] destination_mac;
    logic [47:0] source_mac;
    logic [15:0] ethertype;
    logic [7:0] version;
    prism_opcode_e packet_class;
    prism_operation_key_t key;
    logic [31:0] transaction_id;
    logic [15:0] source_endpoint;
    logic [15:0] destination_endpoint;
    logic [7:0] command;
    logic [7:0] status;
    logic [15:0] body_bytes;
    logic [7:0] fragment_index;
    logic [7:0] fragment_count;
    logic [15:0] ingress_port;
    logic fixed_header_valid;
  } prism_control_frame_header_t;

  typedef struct packed {
    prism_operation_key_t key;
    logic [31:0] issue_group_first_element;
    logic [31:0] first_element;
    logic [15:0] contributor_id;
    logic [15:0] operation_slot;
    logic [15:0] group_slot;
    logic [15:0] expected_contributors;
    logic [7:0] input_format;
    logic [7:0] output_format;
    logic [7:0] accumulator_profile;
    logic [7:0] semantic;
    logic [31:0] total_element_count;
    logic [15:0] result_route_count;
    logic [7:0] element_count;
    logic [7:0] flags;
    logic issue_group_leader;
    logic last_tile;
  } prism_tile_meta_t;

  function automatic int unsigned prism_clog2_safe(input int unsigned value);
    if (value <= 1) return 1;
    return int'($clog2(value));
  endfunction

  function automatic int unsigned prism_ceil_log2_terms(input logic [31:0] terms);
    logic [31:0] remaining;
    int unsigned result;
    if (terms <= 1) return 0;
    remaining = terms - 1;
    result = 0;
    for (int unsigned bit_index = 0; bit_index < 32; bit_index++) begin
      if (remaining != 0) begin
        remaining = remaining >> 1;
        result++;
      end
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
    if ((base_width == 0) || (maximum_terms == 0)) return 0;
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
        if (!keep[index]) seen_zero = 1'b1;
        else if (seen_zero) prism_keep_is_contiguous = 1'b0;
      end
    end
  endfunction

endpackage
