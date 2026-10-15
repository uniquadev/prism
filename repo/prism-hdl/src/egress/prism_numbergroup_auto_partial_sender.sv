//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_auto_partial_sender.sv
// Module: prism_numbergroup_auto_partial_sender
// Description: Classifies exact or rounded partial tiles into lossless DATA frames.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_auto_partial_sender #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MTU_BYTES = 1500,
    parameter int unsigned LANES = 128
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic                            s_reset,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                     s_total_elements,
    input  logic [15:0]                     s_mtu,
    input  logic [15:0]                     s_kulisch_bits,
    input  logic [31:0]                     s_tile_first_element,
    input  logic [LANES-1:0]                s_tile_keep,
    input  logic                            s_native_input,
    input  logic [LANES*32-1:0]             s_tile_native_bits,
    input  logic [LANES*8-1:0]              s_tile_tags,
    input  logic [LANES*KULISCH_W-1:0]      s_tile_integers,
    input  logic                            s_tile_valid,
    output logic                            s_tile_ready,
    output logic [511:0]                    m_axis_tdata,
    output logic [63:0]                     m_axis_tkeep,
    output logic                            m_axis_tlast,
    output logic [15:0]                     m_frame_bytes,
    output logic [31:0]                     m_packet_id,
    output logic                            m_last_frame_done,
    output logic                            m_axis_tvalid,
    input  logic                            m_axis_tready,
    output logic                            m_fault
);


  typedef enum logic [1:0] {RUN, DRAIN, ERROR_SEND, DONE} state_t;
  localparam int unsigned COUNT_W = $clog2(LANES + 1);
  state_t state;
  prism_pkg::prism_numbergroup_header_t error_header_reg, error_header;
  logic header_captured, classified_width_loss;
  logic [31:0] next_packet_id, error_first_element;
  logic [447:0] error_header_bytes;
  logic [511:0] error_frame;
  logic [511:0] stream_data;
  logic [63:0] stream_keep;
  logic stream_last, stream_valid, stream_last_frame_done, stream_axis_ready;
  logic [15:0] stream_frame_bytes;
  logic [31:0] stream_packet_id;
  logic classifier_input_ready;
  logic [31:0] classified_first, segment_first;
  logic [LANES-1:0] classified_keep;
  logic [LANES*8-1:0] classified_formats, classified_tags;
  logic [LANES*32-1:0] classified_native_bits, classified_fp32_bits;
  logic classified_fp32_eligible;
  logic [LANES*KULISCH_W-1:0] classified_integers;
  logic classified_valid, classified_ready, classified_error;
  logic [COUNT_W-1:0] segment_count;
  logic [LANES*8-1:0] segment_formats, segment_tags;
  logic [LANES*32-1:0] segment_native_bits;
  logic [LANES*KULISCH_W-1:0] segment_integers;
  logic segment_valid, segment_ready, split_input_ready, split_fault, stream_fault;

  assign s_tile_ready = state == RUN && classifier_input_ready;
  assign classified_ready = state == RUN
      && (classified_width_loss || split_input_ready);
  assign stream_axis_ready = m_axis_tready && state inside {RUN, DRAIN};
  assign m_axis_tdata = state == ERROR_SEND ? error_frame : stream_data;
  assign m_axis_tkeep = state == ERROR_SEND
      ? 64'h0fff_ffff_ffff_ffff : stream_keep;
  assign m_axis_tlast = state == ERROR_SEND ? 1'b1 : stream_last;
  assign m_frame_bytes = state == ERROR_SEND ? 16'd60 : stream_frame_bytes;
  assign m_packet_id = state == ERROR_SEND ? next_packet_id : stream_packet_id;
  assign m_axis_tvalid = state == ERROR_SEND
      || (state inside {RUN, DRAIN} && stream_valid);
  assign m_last_frame_done = state == ERROR_SEND
      ? m_axis_tready : stream_last_frame_done;
  assign m_fault = split_fault || stream_fault;

  // Only a Kulisch value needs the configured wire width. AUTO may use a
  // narrower native format when that is itself lossless. Valid exact FP32
  // operations use at least 278 bits, bounding this check to the upper bits.
  always_comb begin
    classified_width_loss = 1'b0;
    if (s_kulisch_bits >= 16'd278 && int'(s_kulisch_bits) < KULISCH_W)
      for (int lane = 0; lane < LANES; lane++)
        if (classified_keep[lane]
            && classified_formats[lane*8 +: 8]
                == prism_pkg::PRISM_FORMAT_KULISCH)
          for (int bit_index = 278; bit_index < KULISCH_W; bit_index++)
            if (bit_index >= int'(s_kulisch_bits)
                && classified_integers[lane*KULISCH_W+bit_index]
                    != classified_integers[lane*KULISCH_W+int'(s_kulisch_bits)-1])
              classified_width_loss = 1'b1;
  end

  always_comb begin
    error_header = error_header_reg;
    error_header.ethertype = prism_pkg::PRISM_ETHERTYPE;
    error_header.version = 8'h20;
    error_header.packet_class = prism_pkg::PRISM_OP_COL_DATA;
    error_header.packet_id = next_packet_id;
    error_header.first_element = error_first_element;
    error_header.element_count = '0;
    error_header.group_count = '0;
    error_header.flags = prism_pkg::PRISM_DATA_FLAG_LAST
        | prism_pkg::PRISM_DATA_FLAG_ACCUMULATION_INEXACT;
    error_header.body_bytes = '0;
    error_header.reserved = '0;
    error_header_bytes = {
        error_header.destination_mac, error_header.source_mac,
        error_header.ethertype, error_header.version,
        error_header.packet_class, error_header.key.job_id,
        error_header.key.group_id, error_header.key.group_generation,
        error_header.key.operation_id, error_header.key.operation_generation,
        error_header.source_endpoint, error_header.destination_endpoint,
        error_header.packet_id, error_header.first_element,
        error_header.element_count, error_header.group_count,
        error_header.flags, error_header.body_bytes,
        error_header.stream_id, error_header.reserved
    };
    error_frame = '0;
    for (int byte_index = 0; byte_index < 56; byte_index++)
      error_frame[byte_index*8 +: 8]
          = error_header_bytes[(55-byte_index)*8 +: 8];
  end

  always_ff @(posedge clk) begin
    if (!rst_n || s_reset) begin
      state <= RUN;
      error_header_reg <= '0;
      header_captured <= 1'b0;
      next_packet_id <= '0;
      error_first_element <= '0;
    end else begin
      if (s_tile_valid && s_tile_ready && !header_captured) begin
        error_header_reg <= s_header;
        next_packet_id <= s_header.packet_id;
        header_captured <= 1'b1;
      end
      if (stream_valid && stream_axis_ready && stream_last)
        next_packet_id <= stream_packet_id + 32'd1;
      case (state)
        RUN: if (classified_valid && classified_ready && classified_width_loss) begin
          error_first_element <= classified_first;
          state <= DRAIN;
        end
        DRAIN: if (!stream_valid
            || (stream_axis_ready && stream_last)) state <= ERROR_SEND;
        ERROR_SEND: if (m_axis_tready) state <= DONE;
        DONE: begin end
        default: state <= RUN;
      endcase
    end
  end

  prism_auto_wire_tile16 #(.KULISCH_W(KULISCH_W), .LANES(LANES)) u_classify (
      .clk(clk), .rst_n(rst_n && !s_reset && state == RUN),
      .s_first_element(s_tile_first_element), .s_keep(s_tile_keep),
      .s_mode_wide(!s_native_input), .s_fp32_bits(s_tile_native_bits),
      .s_tags(s_tile_tags), .s_integers(s_tile_integers),
      .s_valid(s_tile_valid && state == RUN), .s_lane_valid('0), .s_ready(classifier_input_ready),
      .m_first_element(classified_first), .m_keep(classified_keep),
      .m_formats(classified_formats), .m_native_bits(classified_native_bits),
      .m_fp32_bits(classified_fp32_bits), .m_fp32_eligible(classified_fp32_eligible),
      .m_tags(classified_tags), .m_integers(classified_integers),
      .m_valid(classified_valid), .m_lane_valid(), .m_ready(classified_ready),
      .m_error(classified_error)
  );

  logic unused_reserve_ready;
  prism_numbergroup_banked_segment_reader #(.KULISCH_W(KULISCH_W), .LANES(LANES)) u_split (
      .clk(clk), .rst_n(rst_n), .s_clear(s_reset || state inside {ERROR_SEND, DONE}),
      .s_reserve(1'b0), .s_reserve_ready(unused_reserve_ready), .s_lane_valid('0),
      .s_mtu(s_mtu), .s_kulisch_bits(s_kulisch_bits),
      .s_first_element(classified_first), .s_keep(classified_keep),
      .s_formats(classified_formats), .s_native_bits(classified_native_bits),
      .s_fp32_bits(classified_fp32_bits), .s_fp32_eligible(classified_fp32_eligible),
      .s_tags(classified_tags), .s_integers(classified_integers),
      .s_error(classified_error),
      .s_valid(classified_valid && state == RUN && !classified_width_loss),
      .s_ready(split_input_ready),
      .m_first_element(segment_first), .m_count(segment_count),
      .m_formats(segment_formats), .m_native_bits(segment_native_bits),
      .m_tags(segment_tags), .m_integers(segment_integers),
      .m_valid(segment_valid), .m_ready(segment_ready && state == RUN),
      .m_fault(split_fault)
  );

  prism_numbergroup_mixed_tile_streamer #(
      .KULISCH_W(KULISCH_W), .MTU_BYTES(MTU_BYTES), .LANES(LANES),
      .PACKET_CLASS(prism_pkg::PRISM_OP_COL_DATA)
  ) u_stream (
      .clk(clk), .rst_n(rst_n), .s_reset(s_reset || state inside {ERROR_SEND, DONE}),
      .s_header(s_header), .s_total_elements(s_total_elements),
      .s_mtu(s_mtu), .s_kulisch_bits(s_kulisch_bits),
      .s_first_frame_tiles(LANES == 128
          ? 8'((((int'(s_mtu)-prism_pkg::PRISM_CONTROL_WORD_BYTES
              -prism_pkg::PRISM_DATA_HEADER_BYTES+LANES-1)/LANES)/2)+1) : 8'd0),
      .s_tile_first_element(segment_first), .s_tile_count(segment_count),
      .s_formats(segment_formats), .s_native_bits(segment_native_bits),
      .s_tags(segment_tags), .s_integers(segment_integers),
      .s_tile_valid(segment_valid && state == RUN), .s_tile_ready(segment_ready),
      .m_axis_tdata(stream_data), .m_axis_tkeep(stream_keep),
      .m_axis_tlast(stream_last), .m_frame_bytes(stream_frame_bytes),
      .m_packet_id(stream_packet_id), .m_last_frame_done(stream_last_frame_done),
      .m_axis_tvalid(stream_valid), .m_axis_tready(stream_axis_ready),
      .m_fault(stream_fault)
  );

endmodule
