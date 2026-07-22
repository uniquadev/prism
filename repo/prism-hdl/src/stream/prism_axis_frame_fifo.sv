//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_axis_frame_fifo.sv
// Module: prism_axis_frame_fifo
// Description: Buffers complete AXI frames and reports length and keep errors.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_axis_frame_fifo #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1,
    parameter int unsigned DEPTH = 64,
    parameter int unsigned MAX_FRAME_BEATS = 24
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic [DATA_W-1:0]            s_axis_tdata,
    input  logic [DATA_W/8-1:0]          s_axis_tkeep,
    input  logic                         s_axis_tlast,
    input  logic [USER_W-1:0]            s_axis_tuser,
    input  logic                         s_axis_tvalid,
    output logic                         s_axis_tready,
    output logic [DATA_W-1:0]            m_axis_tdata,
    output logic [DATA_W/8-1:0]          m_axis_tkeep,
    output logic                         m_axis_tlast,
    output logic [USER_W-1:0]            m_axis_tuser,
    output logic                         m_axis_tvalid,
    input  logic                         m_axis_tready,
    output logic [15:0]                  m_frame_bytes,
    output logic                         m_nonfinal_keep_error,
    output logic                         m_final_keep_error,
    output logic                         m_adapter_error,
    output logic [$clog2(DEPTH+1)-1:0]   beat_occupancy,
    output logic [$clog2(DEPTH+1)-1:0]   completed_frames
);

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned WORD_W = DATA_W + KEEP_W + 1 + USER_W;
  localparam int unsigned PTR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
  localparam int unsigned COUNT_W = $clog2(DEPTH + 1);
  localparam int unsigned FRAME_BEAT_W = $clog2(MAX_FRAME_BEATS + 1);

  logic [WORD_W-1:0] memory [0:DEPTH-1];
  logic [PTR_W-1:0] write_pointer;
  logic [PTR_W-1:0] read_pointer;
  logic [COUNT_W-1:0] beat_count;
  logic [COUNT_W-1:0] frame_count;
  logic [15:0] frame_byte_memory [0:DEPTH-1];
  logic frame_nonfinal_error_memory [0:DEPTH-1];
  logic frame_final_error_memory [0:DEPTH-1];
  logic frame_adapter_error_memory [0:DEPTH-1];
  logic [PTR_W-1:0] frame_write_pointer;
  logic [PTR_W-1:0] frame_read_pointer;
  logic [15:0] incoming_frame_bytes;
  logic incoming_nonfinal_error;
  logic incoming_adapter_error;
  logic [FRAME_BEAT_W-1:0] incoming_frame_beats;
  logic dropping_oversized_frame;
  logic [15:0] accepted_bytes;
  logic accept;
  logic store_push;
  logic pop;
  logic push_frame;
  logic pop_frame;
  logic oversize_cut;
  logic stored_last;

  assign s_axis_tready = dropping_oversized_frame
      || (beat_count != COUNT_W'(DEPTH)) || (m_axis_tvalid && m_axis_tready);
  assign m_axis_tvalid = (frame_count != 0);
  assign {m_axis_tuser, m_axis_tlast, m_axis_tkeep, m_axis_tdata} = memory[read_pointer];
  assign accept = s_axis_tvalid && s_axis_tready;
  assign store_push = accept && !dropping_oversized_frame;
  assign pop = m_axis_tvalid && m_axis_tready;
  assign oversize_cut = store_push && !s_axis_tlast
      && (incoming_frame_beats == FRAME_BEAT_W'(MAX_FRAME_BEATS - 1));
  assign stored_last = s_axis_tlast || oversize_cut;
  assign push_frame = store_push && stored_last;
  assign pop_frame = pop && m_axis_tlast;
  assign beat_occupancy = beat_count;
  assign completed_frames = frame_count;
  assign accepted_bytes = 16'($countones(s_axis_tkeep));
  assign m_frame_bytes = frame_byte_memory[frame_read_pointer];
  assign m_nonfinal_keep_error = frame_nonfinal_error_memory[frame_read_pointer];
  assign m_final_keep_error = frame_final_error_memory[frame_read_pointer];
  assign m_adapter_error = frame_adapter_error_memory[frame_read_pointer];

  initial begin
    if ((DATA_W == 0) || ((DATA_W % 8) != 0)) begin
      $fatal(1, "prism_axis_frame_fifo DATA_W must be a positive multiple of eight");
    end
    if (USER_W == 0) begin
      $fatal(1, "prism_axis_frame_fifo USER_W must be positive");
    end
    if (DEPTH < MAX_FRAME_BEATS) begin
      $fatal(1, "prism_axis_frame_fifo must hold at least one maximum frame");
    end
    if (MAX_FRAME_BEATS == 0) begin
      $fatal(1, "prism_axis_frame_fifo MAX_FRAME_BEATS must be positive");
    end
  end

  function automatic logic [PTR_W-1:0] next_pointer(input logic [PTR_W-1:0] pointer);
    if (pointer == PTR_W'(DEPTH - 1)) begin
      return '0;
    end
    return pointer + 1'b1;
  endfunction

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      write_pointer <= '0;
      read_pointer <= '0;
      beat_count <= '0;
      frame_count <= '0;
      frame_write_pointer <= '0;
      frame_read_pointer <= '0;
      incoming_frame_bytes <= '0;
      incoming_nonfinal_error <= 1'b0;
      incoming_adapter_error <= 1'b0;
      incoming_frame_beats <= '0;
      dropping_oversized_frame <= 1'b0;
    end else begin
      if (store_push) begin
        memory[write_pointer] <= {s_axis_tuser, stored_last, s_axis_tkeep, s_axis_tdata};
        write_pointer <= next_pointer(write_pointer);
        incoming_frame_bytes <= incoming_frame_bytes + accepted_bytes;
        incoming_frame_beats <= incoming_frame_beats + 1'b1;
        incoming_nonfinal_error <= incoming_nonfinal_error
            || (!s_axis_tlast && (s_axis_tkeep != {KEEP_W{1'b1}}));
        incoming_adapter_error <= incoming_adapter_error || (|s_axis_tuser);
        if (stored_last) begin
          frame_byte_memory[frame_write_pointer] <= incoming_frame_bytes + accepted_bytes;
          frame_nonfinal_error_memory[frame_write_pointer] <= incoming_nonfinal_error
              || (oversize_cut && (s_axis_tkeep != {KEEP_W{1'b1}}));
          frame_final_error_memory[frame_write_pointer] <= (s_axis_tkeep == 0)
              || !prism_pkg::prism_keep_is_contiguous(64'(s_axis_tkeep), KEEP_W);
          frame_adapter_error_memory[frame_write_pointer] <=
              incoming_adapter_error || (|s_axis_tuser) || oversize_cut;
          frame_write_pointer <= next_pointer(frame_write_pointer);
          incoming_frame_bytes <= '0;
          incoming_frame_beats <= '0;
          incoming_nonfinal_error <= 1'b0;
          incoming_adapter_error <= 1'b0;
          if (oversize_cut) begin
            dropping_oversized_frame <= 1'b1;
          end
        end
      end
      if (accept && dropping_oversized_frame && s_axis_tlast) begin
        dropping_oversized_frame <= 1'b0;
      end
      if (pop) begin
        read_pointer <= next_pointer(read_pointer);
      end
      if (pop_frame) begin
        frame_read_pointer <= next_pointer(frame_read_pointer);
      end
      case ({store_push, pop})
        2'b10: beat_count <= beat_count + 1'b1;
        2'b01: beat_count <= beat_count - 1'b1;
        default: beat_count <= beat_count;
      endcase
      case ({push_frame, pop_frame})
        2'b10: frame_count <= frame_count + 1'b1;
        2'b01: frame_count <= frame_count - 1'b1;
        default: frame_count <= frame_count;
      endcase
    end
  end

endmodule
