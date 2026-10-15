//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_rounded_result_store.sv
// Module: prism_fp32_rounded_result_store
// Description: Bank completed FP32 tiles for native or wide AUTO readout.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_rounded_result_store #(
    parameter int unsigned STRIPES = 8,
    parameter int unsigned RANGES = 256,
    localparam int unsigned STRIPE_W = STRIPES > 1 ? $clog2(STRIPES) : 1,
    localparam int unsigned ROW_W = $clog2(RANGES / STRIPES)
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic                       s_release,
    input  logic [31:0]                s_total_elements,
    input  logic [7:0]                 s_slot,
    input  logic [15:0]                s_present,
    input  logic [511:0]               s_bits,
    input  logic                       s_error,
    input  logic                       s_valid,
    output logic                       s_ready,
    output logic                       m_all_written,
    input  logic [7:0]                 s_result_slot,
    input  logic                       s_wide_read,
    input  logic                       s_result_read_valid,
    output logic                       s_result_read_ready,
    output logic [7:0]                 m_result_slot,
    output logic [STRIPES*16-1:0]      m_result_present,
    output logic [STRIPES*512-1:0]     m_result_bits,
    output logic                       m_result_error,
    output logic                       m_result_valid,
    input  logic                       m_result_ready
);

  localparam int unsigned SHIFT_W = $clog2(STRIPES);
  logic [RANGES-1:0] written;
  logic [15:0] present [0:RANGES-1];
  logic error_bit [0:RANGES-1];
  logic [8:0] written_count, total_slots;
  logic [STRIPE_W-1:0] write_stripe, output_stripe;
  logic [ROW_W-1:0] write_row, read_row, output_row;
  logic [511:0] stripe_bits [0:STRIPES-1];
  logic read_accept, write_accept, output_wide;
  logic requested_complete, read_error;
  logic [STRIPES*16-1:0] read_present;

  initial begin
    if (STRIPES < 1 || (STRIPES & (STRIPES - 1)) != 0
        || RANGES < 2*STRIPES || (RANGES & (RANGES - 1)) != 0)
      $fatal(1, "Rounded result store requires power-of-two geometry");
  end

  assign total_slots = 9'((s_total_elements + 32'd15) >> 4);
  assign write_stripe = STRIPES == 1 ? '0 : STRIPE_W'(s_slot);
  assign write_row = ROW_W'(s_slot >> SHIFT_W);
  assign output_stripe = STRIPES == 1 ? '0 : STRIPE_W'(m_result_slot);
  assign output_row = ROW_W'(m_result_slot >> (output_wide ? 0 : SHIFT_W));
  assign read_row = read_accept
      ? ROW_W'(s_result_slot >> (s_wide_read ? 0 : SHIFT_W)) : output_row;
  assign s_ready = !s_release && int'(s_slot) < int'(total_slots)
      && !written[s_slot];
  assign write_accept = s_valid && s_ready;
  assign m_all_written = written_count == total_slots;

  always_comb begin
    integer slot;
    requested_complete = !s_release;
    read_present = '0;
    read_error = 1'b0;
    slot = 0;
    if (s_wide_read) begin
      if (int'(s_result_slot)*STRIPES >= int'(total_slots))
        requested_complete = 1'b0;
      for (integer stripe = 0; stripe < STRIPES; stripe++) begin
        slot = int'(s_result_slot)*STRIPES + stripe;
        if (slot < int'(total_slots)) begin
          if (!written[slot]) requested_complete = 1'b0;
          else begin
            read_present[stripe*16 +: 16] = present[slot];
            read_error |= error_bit[slot];
          end
        end
      end
    end else if (int'(s_result_slot) >= int'(total_slots))
      requested_complete = 1'b0;
    else if (!written[s_result_slot]) requested_complete = 1'b0;
    else begin
      read_present[15:0] = present[s_result_slot];
      read_error = error_bit[s_result_slot];
    end
  end

  assign s_result_read_ready = requested_complete
      && (!m_result_valid || m_result_ready);
  assign read_accept = s_result_read_valid && s_result_read_ready;

  always_comb begin
    m_result_bits = '0;
    if (output_wide) begin
      for (integer stripe = 0; stripe < STRIPES; stripe++) begin
        if (m_result_present[stripe*16 +: 16] != '0)
          m_result_bits[stripe*512 +: 512] = stripe_bits[stripe];
      end
    end else if (m_result_present[15:0] != '0)
      m_result_bits[511:0] = stripe_bits[output_stripe];
  end

  for (genvar stripe = 0; stripe < STRIPES; stripe++) begin : gen_ram
    prism_sync_ram_1w1r #(
        .WIDTH(512), .DEPTH(RANGES/STRIPES), .ADDR_W(ROW_W)
    ) u_ram (
        .clk(clk),
        .write_enable(write_accept && write_stripe == STRIPE_W'(stripe)),
        .write_address(write_row), .write_data(s_bits),
        .read_address(read_row), .read_data(stripe_bits[stripe])
    );
  end

  always_ff @(posedge clk) begin
    if (!rst_n || s_release) begin
      written <= '0;
      written_count <= '0;
      m_result_valid <= 1'b0;
      m_result_slot <= '0;
      m_result_present <= '0;
      m_result_error <= 1'b0;
      output_wide <= 1'b0;
    end else begin
      if (write_accept) begin
        written[s_slot] <= 1'b1;
        written_count <= written_count + 9'd1;
        present[s_slot] <= s_present;
        error_bit[s_slot] <= s_error;
      end
      if (read_accept) begin
        m_result_valid <= 1'b1;
        m_result_slot <= s_result_slot;
        output_wide <= s_wide_read;
        m_result_present <= read_present;
        m_result_error <= read_error;
      end else if (m_result_valid && m_result_ready) m_result_valid <= 1'b0;
    end
  end

endmodule
