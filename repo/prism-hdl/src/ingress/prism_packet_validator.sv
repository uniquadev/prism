//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_packet_validator.sv
// Module: prism_packet_validator
// Description: Classifies a closed PRISM frame after context and payload validation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_packet_validator #(
    parameter int unsigned NUM_PORTS = 2
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_frame_desc_t              s_frame,
    input  logic                                      s_valid,
    output logic                                      s_ready,
    input  logic [NUM_PORTS*48-1:0]                   local_macs,
    input  logic                                      context_valid,
    input  logic                                      contributor_binding_valid,
    input  logic [15:0]                               expected_payload_bytes,
    input  logic                                      expected_last_chunk,
    input  logic                                      endpoint_contributor,
    input  logic                                      laboratory_extension_enabled,
    output prism_pkg::prism_frame_desc_t              m_frame,
    output prism_pkg::prism_packet_class_e            m_class,
    output prism_pkg::prism_status_e                  m_status,
    output logic                                      m_valid,
    input  logic                                      m_ready
);

  import prism_pkg::*;

  logic local_destination;
  logic valid_comb;
  prism_packet_class_e class_comb;
  prism_status_e status_comb;
  logic [15:0] logical_frame_bytes;
  logic [15:0] padded_frame_bytes;
  logic payload_length_valid;
  logic [7:0] selected_flags;

  assign s_ready = !m_valid || m_ready;

  initial begin
    if (NUM_PORTS == 0) begin
      $fatal(1, "prism_packet_validator NUM_PORTS must be positive");
    end
  end

  always_comb begin
    local_destination = 1'b0;
    for (int unsigned port = 0; port < NUM_PORTS; port++) begin
      local_destination |= s_frame.header.destination_mac == local_macs[port*48 +: 48];
    end

    selected_flags = (s_frame.header.opcode == PRISM_OP_COL_RES)
        ? s_frame.header.result.flags : s_frame.header.data.flags;
    logical_frame_bytes = 16'(PRISM_ETH_HEADER_BYTES + PRISM_CONTROL_WORD_BYTES
        + PRISM_DATA_HEADER_BYTES) + expected_payload_bytes;
    padded_frame_bytes = (logical_frame_bytes < 60) ? 16'd60 : logical_frame_bytes;
    payload_length_valid = (s_frame.frame_bytes == logical_frame_bytes)
        || (s_frame.frame_bytes == padded_frame_bytes);

    valid_comb = 1'b0;
    class_comb = PRISM_PACKET_DROP;
    status_comb = PRISM_STATUS_INVALID_REQUEST;

    if (s_frame.adapter_error || s_frame.nonfinal_keep_error || s_frame.final_keep_error
        || !s_frame.header.fixed_header_valid) begin
      status_comb = PRISM_STATUS_BAD_PAYLOAD_LENGTH;
    end else if (s_frame.header.ethertype != PRISM_ETHERTYPE) begin
      status_comb = PRISM_STATUS_INVALID_REQUEST;
    end else if (!local_destination) begin
      status_comb = PRISM_STATUS_NOT_FOUND;
    end else if ((s_frame.header.version_major != PRISM_VERSION_MAJOR)
        || (s_frame.header.version_minor != PRISM_VERSION_MINOR)) begin
      status_comb = PRISM_STATUS_UNSUPPORTED_VERSION;
    end else begin
      case (s_frame.header.opcode)
        PRISM_OP_CONTROL: begin
          if ((s_frame.header.control.fragment_count == 0)
              || (s_frame.header.control.fragment_index >= s_frame.header.control.fragment_count)) begin
            status_comb = PRISM_STATUS_INVALID_REQUEST;
          end else begin
            valid_comb = 1'b1;
            class_comb = PRISM_PACKET_CONTROL;
            status_comb = PRISM_STATUS_OK;
          end
        end
        PRISM_OP_COL_DATA, PRISM_OP_COL_RES: begin
          if (!context_valid) begin
            status_comb = PRISM_STATUS_NOT_FOUND;
          end else if ((selected_flags & ~PRISM_DATA_FLAG_KNOWN_MASK) != 0) begin
            status_comb = PRISM_STATUS_INVALID_REQUEST;
          end else if ((selected_flags & PRISM_DATA_FLAG_ACCUMULATION_INEXACT) != 0
              && (!laboratory_extension_enabled
                  || ((s_frame.header.opcode == PRISM_OP_COL_DATA) && endpoint_contributor))) begin
            status_comb = PRISM_STATUS_INVALID_REQUEST;
          end else if ((s_frame.header.opcode == PRISM_OP_COL_DATA)
              && !contributor_binding_valid) begin
            status_comb = PRISM_STATUS_INVALID_RECORD;
          end else if (!payload_length_valid
              || (((selected_flags & PRISM_DATA_FLAG_LAST_CHUNK) != 0) != expected_last_chunk)) begin
            status_comb = PRISM_STATUS_BAD_PAYLOAD_LENGTH;
          end else begin
            valid_comb = 1'b1;
            class_comb = (s_frame.header.opcode == PRISM_OP_COL_DATA)
                ? PRISM_PACKET_DATA : PRISM_PACKET_RESULT;
            status_comb = PRISM_STATUS_OK;
          end
        end
        default: status_comb = PRISM_STATUS_UNSUPPORTED_FEATURE;
      endcase
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_frame <= '0;
      m_class <= PRISM_PACKET_DROP;
      m_status <= PRISM_STATUS_INVALID_REQUEST;
      m_valid <= 1'b0;
    end else if (s_ready) begin
      m_valid <= s_valid;
      if (s_valid) begin
        m_frame <= s_frame;
        m_class <= valid_comb ? class_comb : PRISM_PACKET_DROP;
        m_status <= status_comb;
      end
    end
  end

endmodule
