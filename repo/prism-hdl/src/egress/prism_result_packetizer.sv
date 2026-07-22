//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_result_packetizer.sv
// Module: prism_result_packetizer
// Description: Serializes one stored result chunk into an Ethernet RES frame.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_result_packetizer #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1,
    parameter int unsigned PORT_INDEX = 0
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  logic [47:0]                           local_mac,
    input  prism_pkg::prism_result_packet_job_t   s_job,
    input  logic                                  s_job_valid,
    output logic                                  s_job_ready,
    output logic [15:0]                           read_slot,
    output logic [15:0]                           read_offset,
    input  logic [511:0]                          read_data,
    input  logic                                  read_slot_armed,
    output logic [DATA_W-1:0]                     m_axis_tdata,
    output logic [DATA_W/8-1:0]                   m_axis_tkeep,
    output logic                                  m_axis_tlast,
    output logic [USER_W-1:0]                     m_axis_tuser,
    output logic                                  m_axis_tvalid,
    input  logic                                  m_axis_tready,
    output logic                                  release_valid,
    output logic [15:0]                           release_slot
);

  import prism_pkg::*;

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned HEADER_BYTES = PRISM_ETH_HEADER_BYTES
      + PRISM_CONTROL_WORD_BYTES + PRISM_RESULT_HEADER_BYTES;

  prism_result_packet_job_t job_reg;
  logic active;
  logic [15:0] frame_offset;
  logic [15:0] logical_frame_bytes;
  logic [15:0] transmitted_frame_bytes;
  logic [15:0] beat_bytes;
  logic [7:0] flags;
  logic [15:0] unused_job_egress_port;

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
    int unsigned payload_position;
    begin
      payload_position = 0;
      if (position < 6) return be48_byte(job_reg.destination_mac, position);
      if (position < 12) return be48_byte(local_mac, position - 6);
      case (position)
        12: return PRISM_ETHERTYPE[15:8];
        13: return PRISM_ETHERTYPE[7:0];
        14: return {PRISM_VERSION_MAJOR, PRISM_VERSION_MINOR};
        15: return PRISM_OP_COL_RES;
        16,17,18,19,20,21,22,23: return be64_byte(job_reg.chunk.key.job_id, position - 16);
        24: return job_reg.chunk.key.group_id[15:8];
        25: return job_reg.chunk.key.group_id[7:0];
        26: return job_reg.chunk.key.group_generation[15:8];
        27: return job_reg.chunk.key.group_generation[7:0];
        28: return job_reg.chunk.key.operation_id[15:8];
        29: return job_reg.chunk.key.operation_id[7:0];
        30: return job_reg.chunk.key.operation_generation[31:24];
        31: return job_reg.chunk.key.operation_generation[23:16];
        32: return job_reg.chunk.key.operation_generation[15:8];
        33: return job_reg.chunk.key.operation_generation[7:0];
        34: return job_reg.result_path_id[15:8];
        35: return job_reg.result_path_id[7:0];
        36: return job_reg.chunk.chunk_index[23:16];
        37: return job_reg.chunk.chunk_index[15:8];
        38: return job_reg.chunk.chunk_index[7:0];
        39: return flags;
        default: begin
          if ((position >= HEADER_BYTES)
              && (position < HEADER_BYTES + 32'(job_reg.chunk.payload_bytes))) begin
            payload_position = position - HEADER_BYTES;
            return read_data[(payload_position-32'(read_offset))*8 +: 8];
          end
          return 8'b0;
        end
      endcase
    end
  endfunction

  initial begin
    if ((DATA_W != 512) || (USER_W < 1) || (PORT_INDEX >= 65536)) begin
      $fatal(1, "prism_result_packetizer parameters are illegal");
    end
  end

  assign read_slot = active ? job_reg.chunk_slot : s_job.chunk_slot;
  assign unused_job_egress_port = job_reg.egress_port;
  assign s_job_ready = !active && read_slot_armed;
  assign logical_frame_bytes = 16'(HEADER_BYTES) + job_reg.chunk.payload_bytes;
  assign transmitted_frame_bytes = (logical_frame_bytes < 60) ? 16'd60 : logical_frame_bytes;
  assign beat_bytes = ((transmitted_frame_bytes - frame_offset) > 16'(KEEP_W))
      ? 16'(KEEP_W) : transmitted_frame_bytes - frame_offset;
  assign read_offset = (frame_offset < 16'(HEADER_BYTES))
      ? 16'b0 : frame_offset - 16'(HEADER_BYTES);
  assign flags = ((job_reg.chunk.chunk_index + 24'd1 == job_reg.chunk.total_chunks)
      ? PRISM_DATA_FLAG_LAST_CHUNK : 8'b0)
      | (job_reg.chunk.accumulation_inexact
          ? PRISM_DATA_FLAG_ACCUMULATION_INEXACT : 8'b0);

  always_comb begin
    m_axis_tdata = '0;
    m_axis_tkeep = '0;
    for (int unsigned octet = 0; octet < KEEP_W; octet++) begin
      if (octet < beat_bytes) begin
        m_axis_tdata[octet*8 +: 8] = frame_byte(32'(frame_offset) + octet);
        m_axis_tkeep[octet] = 1'b1;
      end
    end
    m_axis_tlast = active && (frame_offset + beat_bytes == transmitted_frame_bytes);
    m_axis_tuser = '0;
    m_axis_tvalid = active;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      job_reg <= '0;
      active <= 1'b0;
      frame_offset <= '0;
      release_valid <= 1'b0;
      release_slot <= '0;
    end else begin
      release_valid <= 1'b0;
      if (s_job_valid && s_job_ready) begin
        job_reg <= s_job;
        active <= 1'b1;
        frame_offset <= '0;
      end
      if (m_axis_tvalid && m_axis_tready) begin
        if (m_axis_tlast) begin
          active <= 1'b0;
          frame_offset <= '0;
          release_valid <= 1'b1;
          release_slot <= job_reg.chunk_slot;
        end else begin
          frame_offset <= frame_offset + 16'(KEEP_W);
        end
      end
    end
  end

endmodule
