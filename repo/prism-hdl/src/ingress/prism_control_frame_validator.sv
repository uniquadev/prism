//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_frame_validator.sv
// Module: prism_control_frame_validator
// Description: Transactional protocol 2.0 CONTROL frame validation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_frame_validator #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned MAX_MTU = 1500,
    parameter int unsigned PORT_INDEX = 0
) (
    input  logic                                        clk,
    input  logic                                        rst_n,
    input  logic [DATA_W-1:0]                           s_axis_tdata,
    input  logic [DATA_W/8-1:0]                         s_axis_tkeep,
    input  logic                                        s_axis_tlast,
    input  logic                                        s_axis_tuser,
    input  logic                                        s_axis_tvalid,
    output logic                                        s_axis_tready,
    input  logic [15:0]                                 s_mtu,
    output prism_pkg::prism_control_frame_header_t      m_header,
    output logic [15:0]                                 m_frame_bytes,
    output logic                                        m_accept,
    output logic [2:0]                                  m_error_code,
    output logic                                        m_valid,
    input  logic                                        m_ready,
    input  logic [15:0]                                 m_read_address,
    output logic [7:0]                                  m_read_data
);

  import prism_pkg::*;

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned MAX_FRAME_BYTES = PRISM_ETH_HEADER_BYTES + MAX_MTU;
  localparam int unsigned FRAME_BEATS = (MAX_FRAME_BYTES + KEEP_W - 1) / KEEP_W;
  localparam int unsigned BEAT_W = prism_clog2_safe(FRAME_BEATS);
  localparam int unsigned HEADER_BYTES = PRISM_ETH_HEADER_BYTES
      + PRISM_CONTROL_WORD_BYTES + PRISM_CONTROL_HEADER_BYTES;

  typedef enum logic [1:0] {RX, CHECK, PADDING, REPORT} state_t;
  state_t state;
  logic [DATA_W-1:0] frame_words [0:FRAME_BEATS-1];
  logic [15:0] beat_index, frame_bytes, mtu_reg, padding_cursor;
  logic receive_error, accepted;
  logic [2:0] error_code;
  prism_control_frame_header_t first_header, header_reg;
  logic unused_parser_ready, unused_parser_valid;

  function automatic logic [7:0] frame_byte(input logic [15:0] address);
    if (int'(address) >= MAX_FRAME_BYTES) return 8'h00;
    return frame_words[int'(address) / KEEP_W][(int'(address) % KEEP_W)*8 +: 8];
  endfunction

  prism_control_header_parser #(
      .DATA_W(DATA_W), .PORT_INDEX(PORT_INDEX)
  ) u_header_parser (
      .s_tdata(s_axis_tdata), .s_tkeep(s_axis_tkeep),
      .s_valid(s_axis_tvalid), .s_ready(unused_parser_ready),
      .m_header(first_header), .m_valid(unused_parser_valid),
      .m_ready(1'b1)
  );

  initial begin
    if (DATA_W != 512 || MAX_MTU < 576 || MAX_MTU > 9216)
      $fatal(1, "CONTROL validator requires 512-bit AXI and a supported MTU");
  end

  assign s_axis_tready = state == RX;
  assign m_header = header_reg;
  assign m_frame_bytes = frame_bytes;
  assign m_accept = accepted;
  assign m_error_code = error_code;
  assign m_valid = state == REPORT;
  assign m_read_data = m_valid && m_accept && m_read_address < frame_bytes
      ? frame_byte(m_read_address) : 8'h00;

  always_ff @(posedge clk) begin : p_validator
    int unsigned received_bytes;
    int unsigned expected_bytes;

    if (!rst_n) begin
      state <= RX;
      beat_index <= '0;
      frame_bytes <= '0;
      mtu_reg <= '0;
      padding_cursor <= '0;
      receive_error <= 1'b0;
      accepted <= 1'b0;
      error_code <= '0;
      header_reg <= '0;
    end else begin
      case (state)
        RX: begin
          if (s_axis_tvalid) begin
            received_bytes = $countones(s_axis_tkeep);
            if (beat_index == 0) begin
              header_reg <= first_header;
              mtu_reg <= s_mtu;
            end
            if (int'(beat_index) < FRAME_BEATS)
              frame_words[beat_index[BEAT_W-1:0]] <= s_axis_tdata;
            // The length of the frame is checked once the frame is complete,
            // from the registered byte count, not beat by beat behind the adder.
            if (received_bytes == 0
                || !prism_keep_is_contiguous(s_axis_tkeep, KEEP_W)
                || (!s_axis_tlast && s_axis_tkeep != {KEEP_W{1'b1}})
                || s_axis_tuser || int'(beat_index) >= FRAME_BEATS)
              receive_error <= 1'b1;
            frame_bytes <= 16'(int'(frame_bytes) + received_bytes);
            if (s_axis_tlast) state <= CHECK;
            else if (beat_index != 16'hFFFF) beat_index <= beat_index + 16'd1;
          end
        end
        CHECK: begin
          expected_bytes = HEADER_BYTES + int'(header_reg.body_bytes);
          if (expected_bytes < 60) expected_bytes = 60;
          if (receive_error || frame_bytes < 60 || int'(frame_bytes) > MAX_FRAME_BYTES
              || !header_reg.fixed_header_valid) begin
            error_code <= 3'd1;
            accepted <= 1'b0;
            state <= REPORT;
          end else if (header_reg.ethertype != PRISM_ETHERTYPE
              || header_reg.version != 8'h20
              || header_reg.packet_class != PRISM_OP_CONTROL
              || header_reg.command < 8'd1 || header_reg.command > 8'd8
              || header_reg.fragment_count == 0
              || header_reg.fragment_index >= header_reg.fragment_count
              || (header_reg.command != 8'd8
                  && (header_reg.fragment_index != 0
                      || header_reg.fragment_count != 1))
              || ((header_reg.command != 8'd1 && header_reg.command != 8'd8)
                  && header_reg.body_bytes != 0)
              || (header_reg.command == 8'd1 && header_reg.body_bytes < 48)) begin
            error_code <= 3'd2;
            accepted <= 1'b0;
            state <= REPORT;
          end else if (mtu_reg < 576 || int'(mtu_reg) > MAX_MTU
              || PRISM_CONTROL_WORD_BYTES + PRISM_CONTROL_HEADER_BYTES
                  + int'(header_reg.body_bytes) > int'(mtu_reg)
              || frame_bytes != 16'(expected_bytes)) begin
            error_code <= 3'd3;
            accepted <= 1'b0;
            state <= REPORT;
          end else begin
            padding_cursor <= 16'(HEADER_BYTES + int'(header_reg.body_bytes));
            state <= PADDING;
          end
        end
        PADDING: begin
          if (padding_cursor == frame_bytes) begin
            accepted <= 1'b1;
            error_code <= '0;
            state <= REPORT;
          end else if (frame_byte(padding_cursor) != 0) begin
            accepted <= 1'b0;
            error_code <= 3'd4;
            state <= REPORT;
          end else padding_cursor <= padding_cursor + 16'd1;
        end
        REPORT: begin
          if (m_ready) begin
            state <= RX;
            beat_index <= '0;
            frame_bytes <= '0;
            receive_error <= 1'b0;
            accepted <= 1'b0;
            error_code <= '0;
          end
        end
        default: state <= RX;
      endcase
    end
  end

endmodule
