//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_native_tile_harness.sv
// Module: prism_numbergroup_native_tile_harness
// Description: Validated NumberGroup bytes through aligned native arithmetic tiles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_native_tile_harness (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [511:0] s_axis_tdata,
    input  logic [63:0]  s_axis_tkeep,
    input  logic         s_axis_tlast,
    input  logic         s_axis_tuser,
    input  logic         s_axis_tvalid,
    output logic         s_axis_tready,
    output logic         m_frame_valid,
    output logic         m_frame_accept,
    output logic [2:0]   m_frame_error,
    output logic [31:0]  m_tile_first_element,
    output logic [7:0]   m_tile_format,
    output logic [7:0]   m_tile_count,
    output logic [15:0]  m_tile_contributor_id,
    output logic [511:0] m_tile_bits,
    output logic [63:0]  m_tile_keep,
    output logic         m_tile_valid,
    input  logic         m_tile_ready
);

  prism_pkg::prism_numbergroup_header_t header;
  prism_pkg::prism_tile_meta_t base_meta;
  prism_pkg::prism_tile_meta_t tile_meta;
  logic [15:0] frame_bytes;
  logic [4:0] frame_format_mask;
  logic [15:0] read_address;
  logic [7:0] read_data;
  logic [31:0] global_index;
  logic [7:0] format_id;
  logic [7:0] group_index;
  logic [15:0] value_bytes;
  logic [15:0] byte_index;
  logic [7:0] value_byte;
  logic element_last_byte;
  logic group_last_byte;
  logic packet_last_byte;
  logic value_valid;
  logic value_ready;
  logic reader_ready;
  logic reader_done;
  logic validator_frame_valid, validator_frame_accept;
  logic window_s_ready, window_m_valid, window_m_ready;
  logic [1:0] window_reason;
  logic window_release_ready;
  logic [1:0] window_complete;
  logic [63:0] window_watermarks;
  typedef enum logic [1:0] {ADMIT_IDLE, ADMIT_WAIT, ADMIT_READ, ADMIT_REJECT}
      admission_state_t;
  admission_state_t admission_state;
  logic unused_signals;
  assign unused_signals = ^{frame_bytes, frame_format_mask, group_index, value_bytes,
      group_last_byte, reader_ready, window_release_ready, window_complete,
      window_watermarks};

  assign m_frame_valid = validator_frame_valid;
  assign m_frame_accept = validator_frame_accept && admission_state == ADMIT_READ;

  prism_numbergroup_interval_window #(
      .WINDOW_ELEMENTS(64), .CONTRIBUTORS(2)
  ) u_window (
      .clk(clk), .rst_n(rst_n),
      .s_first_element(header.first_element),
      .s_element_count(header.element_count),
      .s_total_elements(header.flags[0]
          ? header.first_element + 32'(header.element_count) : 32'd64),
      .s_window_elements(16'd64),
      .s_candidate(1'b0),
      .s_contributor_slot(header.source_endpoint[0]),
      .s_last(header.flags[0]),
      .s_valid(admission_state == ADMIT_IDLE && validator_frame_valid
          && validator_frame_accept),
      .s_ready(window_s_ready),
      .s_release(1'b0), .s_release_ready(window_release_ready),
      .m_complete(window_complete),
      .m_watermarks(window_watermarks),
      .m_reason(window_reason), .m_valid(window_m_valid),
      .m_ready(window_m_ready)
  );

  assign window_m_ready = admission_state == ADMIT_WAIT;

  always_ff @(posedge clk) begin
    if (!rst_n) admission_state <= ADMIT_IDLE;
    else begin
      case (admission_state)
        ADMIT_IDLE: begin
          if (validator_frame_valid && validator_frame_accept && window_s_ready)
            admission_state <= ADMIT_WAIT;
        end
        ADMIT_WAIT: begin
          if (window_m_valid)
            admission_state <= window_reason == 0 ? ADMIT_READ : ADMIT_REJECT;
        end
        ADMIT_READ: begin
          if (reader_done) admission_state <= ADMIT_IDLE;
        end
        ADMIT_REJECT: admission_state <= ADMIT_IDLE;
        default: admission_state <= ADMIT_IDLE;
      endcase
    end
  end

  always_comb begin
    base_meta = '0;
    base_meta.key = header.key;
    base_meta.contributor_id = header.source_endpoint;
    base_meta.operation_slot = 16'd1;
    base_meta.group_slot = 16'd1;
    base_meta.expected_contributors = 16'd2;
    base_meta.total_element_count = 32'd64;
  end

  prism_numbergroup_frame_validator u_validator (
      .clk(clk),
      .rst_n(rst_n),
      .s_axis_tdata(s_axis_tdata),
      .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tlast(s_axis_tlast),
      .s_axis_tuser(s_axis_tuser),
      .s_axis_tvalid(s_axis_tvalid),
      .s_axis_tready(s_axis_tready),
      .s_mtu(16'd1500),
      .s_kulisch_bits(16'd279),
      .m_header(header),
      .m_frame_bytes(frame_bytes),
      .m_format_mask(frame_format_mask),
      .m_accept(validator_frame_accept),
      .m_error_code(m_frame_error),
      .m_valid(validator_frame_valid),
      .m_ready(validator_frame_valid && (!validator_frame_accept
          || (admission_state == ADMIT_READ && reader_done)
          || admission_state == ADMIT_REJECT)),
      .m_read_address(read_address),
      .m_read_data(read_data),
      .m_read_word_address(16'd0), .m_read_word_data(),
      .m_read_next_word_data(),
      .m_copy_word_address(16'd0), .m_copy_word_data()
  );

  prism_numbergroup_value_reader u_reader (
      .clk(clk),
      .rst_n(rst_n),
      .s_header(header),
      .s_kulisch_bits(16'd279),
      .s_valid(validator_frame_valid && admission_state == ADMIT_READ),
      .s_ready(reader_ready),
      .read_address(read_address),
      .read_data(read_data),
      .m_global_index(global_index),
      .m_format(format_id),
      .m_group_index(group_index),
      .m_value_bytes(value_bytes),
      .m_byte_index(byte_index),
      .m_value_byte(value_byte),
      .m_element_last_byte(element_last_byte),
      .m_group_last_byte(group_last_byte),
      .m_packet_last_byte(packet_last_byte),
      .m_valid(value_valid),
      .m_ready(value_ready),
      .m_done_valid(reader_done),
      .m_done_ready(1'b1)
  );

  prism_numbergroup_native_tile_builder u_builder (
      .clk(clk),
      .rst_n(rst_n),
      .s_base_meta(base_meta),
      .s_global_index(global_index),
      .s_format(format_id),
      .s_byte_index(byte_index),
      .s_value_byte(value_byte),
      .s_element_last_byte(element_last_byte),
      .s_packet_last_byte(packet_last_byte),
      .s_valid(value_valid),
      .s_ready(value_ready),
      .m_meta(tile_meta),
      .m_element_bits(m_tile_bits),
      .m_element_keep(m_tile_keep),
      .m_valid(m_tile_valid),
      .m_ready(m_tile_ready)
  );

  assign m_tile_first_element = tile_meta.first_element;
  assign m_tile_format = tile_meta.input_format;
  assign m_tile_count = tile_meta.element_count;
  assign m_tile_contributor_id = tile_meta.contributor_id;

endmodule
