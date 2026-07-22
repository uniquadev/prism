//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_packetizer.sv
// Module: prism_control_packetizer
// Description: Captures a CONTROL payload and serializes one Ethernet response frame.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_packetizer #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1,
    parameter int unsigned NUM_PORTS = 2,
    parameter int unsigned PAYLOAD_CAPACITY = 1400
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  logic [NUM_PORTS*48-1:0]               local_macs,
    input  prism_pkg::prism_control_header_t      s_header,
    input  logic [15:0]                           s_payload_length,
    input  logic                                  s_header_valid,
    output logic                                  s_header_ready,
    input  logic [7:0]                            s_byte,
    input  logic                                  s_byte_last,
    input  logic                                  s_byte_valid,
    output logic                                  s_byte_ready,
    output logic [15:0]                           m_egress_port,
    output logic [DATA_W-1:0]                     m_axis_tdata,
    output logic [DATA_W/8-1:0]                   m_axis_tkeep,
    output logic                                  m_axis_tlast,
    output logic [USER_W-1:0]                     m_axis_tuser,
    output logic                                  m_axis_tvalid,
    input  logic                                  m_axis_tready
);

  import prism_pkg::*;

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned HEADER_BYTES = PRISM_ETH_HEADER_BYTES
      + PRISM_CONTROL_WORD_BYTES + PRISM_CONTROL_HEADER_BYTES;
  localparam int unsigned PAYLOAD_W = prism_clog2_safe(PAYLOAD_CAPACITY);

  typedef enum logic [1:0] {STATE_IDLE, STATE_CAPTURE, STATE_TRANSMIT} state_e;
  state_e state;
  prism_control_header_t header_reg;
  logic [15:0] payload_length_reg;
  logic [15:0] capture_index;
  logic [15:0] frame_offset;
  logic [7:0] payload_memory [0:PAYLOAD_CAPACITY-1];
  logic [15:0] logical_frame_bytes;
  logic [15:0] transmitted_frame_bytes;
  logic [15:0] beat_bytes;
  logic [47:0] source_mac;
  // Response destination selection uses the request source; the canonical header also carries
  // the original request destination for diagnostics.
  logic unused_header_fields;
  assign unused_header_fields = ^header_reg;

  function automatic logic [7:0] be64_byte(
      input logic [63:0] value,
      input int unsigned index
  );
    return value[(7-index)*8 +: 8];
  endfunction

  function automatic logic [7:0] be48_byte(
      input logic [47:0] value,
      input int unsigned index
  );
    return value[(5-index)*8 +: 8];
  endfunction

  function automatic logic [7:0] frame_byte(input int unsigned position);
    if (position < 6) return be48_byte(header_reg.source_mac, position);
    if (position < 12) return be48_byte(source_mac, position - 6);
    case (position)
      12: return PRISM_ETHERTYPE[15:8];
      13: return PRISM_ETHERTYPE[7:0];
      14: return {PRISM_VERSION_MAJOR, PRISM_VERSION_MINOR};
      15: return PRISM_OP_CONTROL;
      16,17,18,19,20,21,22,23: return be64_byte(header_reg.session_cookie, position - 16);
      24,25,26,27,28,29,30,31: return be64_byte(header_reg.transaction_id, position - 24);
      32: return header_reg.command[15:8];
      33: return header_reg.command[7:0];
      34: return header_reg.flags;
      35: return header_reg.status;
      36: return header_reg.fragment_index[15:8];
      37: return header_reg.fragment_index[7:0];
      38: return header_reg.fragment_count[15:8];
      39: return header_reg.fragment_count[7:0];
      default: begin
        if ((position >= HEADER_BYTES)
            && (position < HEADER_BYTES + 32'(payload_length_reg))) begin
          return payload_memory[PAYLOAD_W'(position - HEADER_BYTES)];
        end
        return 8'b0;
      end
    endcase
  endfunction

  initial begin
    if ((DATA_W != 512) || (NUM_PORTS < 1) || (PAYLOAD_CAPACITY < 1)) begin
      $fatal(1, "prism_control_packetizer parameters are illegal");
    end
  end

  assign s_header_ready = state == STATE_IDLE;
  assign s_byte_ready = state == STATE_CAPTURE;
  assign m_egress_port = header_reg.ingress_port;
  assign source_mac = (header_reg.ingress_port < 16'(NUM_PORTS))
      ? local_macs[int'(header_reg.ingress_port)*48 +: 48] : 48'b0;
  assign logical_frame_bytes = 16'(HEADER_BYTES) + payload_length_reg;
  assign transmitted_frame_bytes = (logical_frame_bytes < 60) ? 16'd60 : logical_frame_bytes;
  assign beat_bytes = ((transmitted_frame_bytes - frame_offset) > 16'(KEEP_W))
      ? 16'(KEEP_W) : transmitted_frame_bytes - frame_offset;

  always_comb begin
    m_axis_tdata = '0;
    m_axis_tkeep = '0;
    for (int unsigned octet = 0; octet < KEEP_W; octet++) begin
      if (octet < beat_bytes) begin
        m_axis_tdata[octet*8 +: 8] = frame_byte(32'(frame_offset) + octet);
        m_axis_tkeep[octet] = 1'b1;
      end
    end
    m_axis_tlast = (state == STATE_TRANSMIT)
        && (frame_offset + beat_bytes == transmitted_frame_bytes);
    m_axis_tuser = '0;
    m_axis_tvalid = state == STATE_TRANSMIT;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= STATE_IDLE;
      header_reg <= '0;
      payload_length_reg <= '0;
      capture_index <= '0;
      frame_offset <= '0;
    end else begin
      if (s_header_valid && s_header_ready) begin
        header_reg <= s_header;
        payload_length_reg <= s_payload_length;
        capture_index <= '0;
        frame_offset <= '0;
        state <= (s_payload_length == 0) ? STATE_TRANSMIT : STATE_CAPTURE;
      end
      if (s_byte_valid && s_byte_ready) begin
        if (capture_index < 16'(PAYLOAD_CAPACITY)) begin
          payload_memory[PAYLOAD_W'(capture_index)] <= s_byte;
        end
        capture_index <= capture_index + 16'd1;
        if (s_byte_last || (capture_index + 16'd1 == payload_length_reg)) begin
          state <= STATE_TRANSMIT;
          frame_offset <= '0;
        end
      end
      if (m_axis_tvalid && m_axis_tready) begin
        if (m_axis_tlast) begin
          state <= STATE_IDLE;
          frame_offset <= '0;
        end else begin
          frame_offset <= frame_offset + 16'(KEEP_W);
        end
      end
    end
  end

endmodule
