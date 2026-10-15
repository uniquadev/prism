//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_native_tile_serializer.sv
// Module: prism_native_tile_serializer
// Description: Lossless 512-bit native tile to sixteen-lane legacy tile adapter.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_native_tile_serializer #(
    parameter int unsigned CHILD_W = 3
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic [31:0]             s_first_element,
    input  logic [7:0]              s_format,
    input  logic [CHILD_W-1:0]      s_contributor_slot,
    input  logic [511:0]            s_bits,
    input  logic [63:0]             s_keep,
    input  logic                    s_valid,
    output logic                    s_ready,
    output logic [31:0]             m_first_element,
    output logic [7:0]              m_format,
    output logic [7:0]              m_count,
    output logic [CHILD_W-1:0]      m_contributor_slot,
    output logic [511:0]            m_bits,
    output logic [15:0]             m_keep,
    output logic                    m_valid,
    input  logic                    m_ready
);

  logic occupied;
  logic [31:0] first_reg;
  logic [7:0] format_reg;
  logic [CHILD_W-1:0] contributor_reg;
  logic [511:0] bits_reg;
  logic [63:0] keep_reg;
  logic [1:0] slice_reg;
  logic [2:0] first_slice, next_slice;
  logic [5:0] slice_width;
  logic [15:0] slice_keep;

  function automatic logic [2:0] next_nonempty(
      input logic [63:0] keep,
      input logic [2:0] begin_at
  );
    next_nonempty = 3'd4;
    for (integer slice = 3; slice >= 0; slice--)
      if (3'(slice) >= begin_at && |keep[slice*16 +: 16])
        next_nonempty = 3'(slice);
  endfunction

  assign first_slice = next_nonempty(s_keep, 3'd0);
  assign next_slice = next_nonempty(keep_reg, {1'b0, slice_reg} + 3'd1);
  assign slice_keep = 16'(keep_reg >> (int'(slice_reg) * 16));
  assign slice_width = format_reg == 8'h01 ? 6'd8
      : format_reg == 8'h02 || format_reg == 8'h03 ? 6'd16 : 6'd32;
  assign m_first_element = first_reg + 32'(slice_reg) * 32'd16;
  assign m_format = format_reg;
  assign m_contributor_slot = contributor_reg;
  assign m_keep = slice_keep;
  assign m_count = 8'($countones(slice_keep));
  assign m_bits = 512'(bits_reg >> (int'(slice_reg) * 16 * int'(slice_width)));
  assign m_valid = occupied;
  assign s_ready = !occupied || (m_ready && next_slice == 3'd4);

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      occupied <= 1'b0;
      first_reg <= '0;
      format_reg <= '0;
      contributor_reg <= '0;
      bits_reg <= '0;
      keep_reg <= '0;
      slice_reg <= '0;
    end else if (s_valid && s_ready) begin
      occupied <= first_slice != 3'd4;
      first_reg <= s_first_element;
      format_reg <= s_format;
      contributor_reg <= s_contributor_slot;
      bits_reg <= s_bits;
      keep_reg <= s_keep;
      slice_reg <= 2'(first_slice);
    end else if (m_valid && m_ready) begin
      if (next_slice == 3'd4) occupied <= 1'b0;
      else slice_reg <= 2'(next_slice);
    end
  end

endmodule
