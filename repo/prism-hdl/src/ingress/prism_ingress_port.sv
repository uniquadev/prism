//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_ingress_port.sv
// Module: prism_ingress_port
// Description: Buffers, parses, looks up, and validates one external ingress stream.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_ingress_port #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned PORT_INDEX = 0,
    parameter int unsigned NUM_PORTS = 2,
    parameter int unsigned FIFO_DEPTH = 64,
    parameter int unsigned USER_W = 1
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  logic [DATA_W-1:0]                         s_axis_tdata,
    input  logic [DATA_W/8-1:0]                       s_axis_tkeep,
    input  logic                                      s_axis_tlast,
    input  logic [USER_W-1:0]                         s_axis_tuser,
    input  logic                                      s_axis_tvalid,
    output logic                                      s_axis_tready,
    input  logic [NUM_PORTS*48-1:0]                   local_macs,
    input  logic                                      laboratory_extension_enabled,
    output logic                                      lookup_request,
    input  logic                                      lookup_grant,
    output prism_pkg::prism_operation_key_t           operation_lookup_key,
    input  logic                                      operation_lookup_valid,
    input  prism_pkg::prism_operation_state_e         operation_lookup_state,
    input  logic [15:0]                               operation_lookup_slot,
    input  prism_pkg::prism_operation_descriptor_t    operation_lookup_descriptor,
    input  logic [15:0]                               operation_lookup_group_slot,
    input  logic [15:0]                               operation_lookup_expected_contributors,
    input  logic [15:0]                               operation_lookup_selected_width,
    input  logic [1:0]                                operation_lookup_width_index,
    input  logic                                      operation_lookup_accumulation_inexact,
    output logic [15:0]                               contributor_lookup_slot,
    output logic [15:0]                               contributor_lookup_id,
    input  logic                                      contributor_lookup_valid,
    input  prism_pkg::prism_contributor_binding_t     contributor_lookup_binding,
    output prism_pkg::prism_frame_desc_t              m_packet,
    output prism_pkg::prism_packet_class_e            m_packet_class,
    output prism_pkg::prism_status_e                  m_packet_status,
    output prism_pkg::prism_ingress_context_t         m_packet_context,
    output logic                                      m_packet_valid,
    input  logic                                      m_packet_ready,
    output logic [DATA_W-1:0]                         m_axis_tdata,
    output logic [DATA_W/8-1:0]                       m_axis_tkeep,
    output logic                                      m_axis_tlast,
    output logic [USER_W-1:0]                         m_axis_tuser,
    output logic                                      m_axis_tvalid,
    input  logic                                      m_axis_tready
);

  import prism_pkg::*;

  typedef enum logic [1:0] {STATE_PARSE, STATE_VALIDATE, STATE_FRAME} state_e;
  state_e state;

  logic [DATA_W-1:0] fifo_tdata;
  logic [DATA_W/8-1:0] fifo_tkeep;
  logic fifo_tlast;
  logic [USER_W-1:0] fifo_tuser;
  logic fifo_tvalid;
  logic fifo_tready;
  logic [15:0] fifo_frame_bytes;
  logic fifo_nonfinal_keep_error;
  logic fifo_final_keep_error;
  logic fifo_adapter_error;
  logic [$clog2(FIFO_DEPTH+1)-1:0] unused_beat_occupancy;
  logic [$clog2(FIFO_DEPTH+1)-1:0] unused_completed_frames;

  prism_parsed_header_t parsed_header;
  logic parser_valid;
  logic parser_ready;
  prism_frame_desc_t frame_candidate;
  prism_frame_desc_t validated_frame;
  prism_packet_class_e validated_class;
  prism_status_e validated_status;
  logic validator_valid;
  logic validator_ready;
  logic unused_validator_ready;
  logic [15:0] expected_payload_bytes;
  logic expected_last_chunk;
  int unsigned bytes_per_element;
  int unsigned elements_per_chunk;
  int unsigned chunk_count;
  logic [31:0] first_element;
  logic [31:0] remaining_elements;
  logic binding_matches;
  prism_ingress_context_t context_reg;

  // ---------------------------------------------------------------------------
  // Elaboration checks
  // ---------------------------------------------------------------------------

  initial begin
    if ((DATA_W != 512) || (PORT_INDEX >= NUM_PORTS) || (FIFO_DEPTH < 24)) begin
      $fatal(1, "prism_ingress_port requires a legal 512-bit port profile");
    end
  end

  // ---------------------------------------------------------------------------
  // Complete-frame ingress buffering
  // ---------------------------------------------------------------------------

  prism_axis_frame_fifo #(
      .DATA_W(DATA_W),
      .USER_W(USER_W),
      .DEPTH(FIFO_DEPTH),
      .MAX_FRAME_BEATS(24)
  ) u_frame_fifo (
      .clk(clk),
      .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata),
      .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast),
      .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid),
      .s_axis_tready(s_axis_tready),
      .m_axis_tdata(fifo_tdata),
      .m_axis_tkeep(fifo_tkeep),
      .m_axis_tlast(fifo_tlast),
      .m_axis_tuser(fifo_tuser),
      .m_axis_tvalid(fifo_tvalid),
      .m_axis_tready(fifo_tready),
      .m_frame_bytes(fifo_frame_bytes),
      .m_nonfinal_keep_error(fifo_nonfinal_keep_error),
      .m_final_keep_error(fifo_final_keep_error),
      .m_adapter_error(fifo_adapter_error),
      .beat_occupancy(unused_beat_occupancy),
      .completed_frames(unused_completed_frames)
  );

  // ---------------------------------------------------------------------------
  // Header parsing and control-table lookup
  // ---------------------------------------------------------------------------

  prism_header_parser #(
      .DATA_W(DATA_W),
      .PORT_INDEX(PORT_INDEX)
  ) u_header_parser (
      .s_tdata(fifo_tdata),
      .s_tkeep(fifo_tkeep),
      .s_valid(fifo_tvalid && (state == STATE_PARSE)),
      .s_ready(parser_ready),
      .m_header(parsed_header),
      .m_valid(parser_valid),
      .m_ready((state == STATE_PARSE) && lookup_grant)
  );

  always_comb begin
    operation_lookup_key = (parsed_header.opcode == PRISM_OP_COL_RES)
        ? parsed_header.result.key : parsed_header.data.key;
  end

  always_comb begin
    contributor_lookup_slot = operation_lookup_group_slot;
    contributor_lookup_id = parsed_header.data.contributor_id;
  end

  always_comb begin
    frame_candidate = '0;
    frame_candidate.header = parsed_header;
    frame_candidate.frame_bytes = fifo_frame_bytes;
    frame_candidate.nonfinal_keep_error = fifo_nonfinal_keep_error;
    frame_candidate.final_keep_error = fifo_final_keep_error;
    frame_candidate.adapter_error = fifo_adapter_error;
  end

  always_comb begin
    bytes_per_element = prism_bytes_per_element(operation_lookup_descriptor.input_format);
    elements_per_chunk = prism_elements_per_chunk(operation_lookup_descriptor.input_format);
    chunk_count = prism_chunk_count(operation_lookup_descriptor.element_count,
        operation_lookup_descriptor.input_format);
    first_element = parsed_header.data.chunk_index * elements_per_chunk;
    remaining_elements = (first_element < operation_lookup_descriptor.element_count)
        ? operation_lookup_descriptor.element_count - first_element : 0;
    expected_payload_bytes = 16'(((remaining_elements < elements_per_chunk)
        ? remaining_elements : elements_per_chunk) * bytes_per_element);
    expected_last_chunk = (chunk_count != 0)
        && (parsed_header.data.chunk_index == 24'(chunk_count - 1));
    binding_matches = contributor_lookup_valid
        && (contributor_lookup_binding.contributor_id == parsed_header.data.contributor_id)
        && (contributor_lookup_binding.ingress_port == 16'(PORT_INDEX))
        && (contributor_lookup_binding.source_mac == parsed_header.source_mac);
  end

  // ---------------------------------------------------------------------------
  // Protocol validation and admitted-frame output
  // ---------------------------------------------------------------------------

  prism_packet_validator #(
      .NUM_PORTS(NUM_PORTS)
  ) u_packet_validator (
      .clk(clk),
      .rst_n(rst_n),
      .s_frame(frame_candidate),
      .s_valid(parser_valid && parser_ready && (state == STATE_PARSE)),
      .s_ready(unused_validator_ready),
      .local_macs(local_macs),
      .context_valid(operation_lookup_valid
          && (operation_lookup_state == PRISM_OPERATION_ACTIVE)),
      .contributor_binding_valid(binding_matches),
      .expected_payload_bytes(expected_payload_bytes),
      .expected_last_chunk(expected_last_chunk),
      .endpoint_contributor(1'b1),
      .laboratory_extension_enabled(laboratory_extension_enabled),
      .m_frame(validated_frame),
      .m_class(validated_class),
      .m_status(validated_status),
      .m_valid(validator_valid),
      .m_ready(validator_ready)
  );

  assign validator_ready = (state == STATE_VALIDATE) && m_packet_ready;
  assign lookup_request = (state == STATE_PARSE) && fifo_tvalid;
  assign m_packet = validated_frame;
  assign m_packet_class = validated_class;
  assign m_packet_status = validated_status;
  assign m_packet_context = context_reg;
  assign m_packet_valid = (state == STATE_VALIDATE) && validator_valid;

  assign m_axis_tdata = fifo_tdata;
  assign m_axis_tkeep = fifo_tkeep;
  assign m_axis_tlast = fifo_tlast;
  assign m_axis_tuser = fifo_tuser;
  assign m_axis_tvalid = (state == STATE_FRAME) && fifo_tvalid;
  assign fifo_tready = (state == STATE_FRAME) && m_axis_tready;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= STATE_PARSE;
      context_reg <= '0;
    end else begin
      if ((state == STATE_PARSE) && parser_valid && parser_ready) begin
        state <= STATE_VALIDATE;
        context_reg <= '{
          operation_slot: operation_lookup_slot,
          group_slot: operation_lookup_group_slot,
          descriptor: operation_lookup_descriptor,
          selected_accumulator_width: operation_lookup_selected_width,
          selected_width_index: operation_lookup_width_index,
          accumulation_inexact: operation_lookup_accumulation_inexact,
          expected_contributors: operation_lookup_expected_contributors
        };
      end
      if (m_packet_valid && m_packet_ready) begin
        state <= STATE_FRAME;
      end
      if (m_axis_tvalid && m_axis_tready && m_axis_tlast) begin
        state <= STATE_PARSE;
      end
    end
  end

endmodule
