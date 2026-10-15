//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_arrival_backend.sv
// Module: prism_fp32_arrival_backend
// Description: Bank validated tiles into online FP32 accumulation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_arrival_backend #(
    parameter int unsigned PORTS = 2,
    parameter int unsigned BANKS = 4,
    localparam int unsigned BANK_W = $clog2(BANKS),
    localparam int unsigned ROWS = 256 / BANKS,
    localparam int unsigned ROW_W = $clog2(ROWS)
) (
    input logic clk,
    input logic rst_n,
    input logic s_release,
    input logic [31:0] s_total_elements,
    input logic [3:0] s_children,
    input logic [31:0] s_first [0:PORTS-1],
    input logic [7:0] s_format [0:PORTS-1],
    input logic [511:0] s_bits [0:PORTS-1],
    input logic [15:0] s_keep [0:PORTS-1],
    input logic [PORTS-1:0] s_valid,
    output logic [PORTS-1:0] s_ready,
    output logic [7:0] m_slot,
    output logic [15:0] m_present,
    output logic [511:0] m_bits,
    output logic m_error,
    output logic m_valid,
    input logic m_ready,
    output logic m_idle,
    output logic m_fault
);
  import prism_pkg::*;
  localparam int unsigned INPUT_W = 8 + 8 + 16 + 512;
  localparam int unsigned OUTPUT_W = 8 + 16 + 1 + 512;
  logic [INPUT_W-1:0] port_data [0:PORTS-1];
  logic [PORTS-1:0] bank_source_ready [0:BANKS-1];
  logic [BANKS-1:0] bank_idle, output_valid, output_ready, bank_fault;
  logic [OUTPUT_W-1:0] output_data [0:BANKS-1];

  initial begin
    if (PORTS < 1 || PORTS > 8 || BANKS < 2 || BANKS > 16
        || (BANKS & (BANKS-1)) != 0)
      $fatal(1, "FP32 arrival backend geometry is unsupported");
  end
  for (genvar port = 0; port < PORTS; port++) begin : gen_port
    assign port_data[port] = {s_first[port][11:4], s_format[port],
        s_keep[port], s_bits[port]};
    always_comb begin
      s_ready[port] = 1'b0;
      for (integer bank = 0; bank < BANKS; bank++)
        s_ready[port] |= bank_source_ready[bank][port];
    end
  end
  assign m_idle = (&bank_idle) && !(|output_valid);
  assign m_fault = |bank_fault;

  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_bank
    logic [PORTS-1:0] request_valid;
    logic selected_valid, selected_ready;
    logic [7:0] slot, format;
    logic [15:0] keep, expected;
    logic [511:0] raw_bits, native_bits;
    logic [ROW_W-1:0] commit_row;
    logic [511:0] commit_bits;
    logic [63:0] commit_counts;
    logic commit_complete, commit_error, commit_valid, commit_ready;
    logic queue_ready;
    logic [ROWS*16-1:0] busy;
    logic [15:0] commit_mask;
    logic [ROW_W-1:0] result_row;
    logic [511:0] result_bits;
    logic [15:0] result_keep;
    logic result_valid, result_error;
    // Exclude overlapping reserved lanes before arbitration: a dependent head must not
    // block an independent range offered by another port. Only the bank
    // handshake admits an update; the local reservation still enforces RAW.
    for (genvar port = 0; port < PORTS; port++) begin : gen_request
      assign request_valid[port] = s_valid[port] && !s_release
          && s_first[port][4 +: BANK_W] == BANK_W'(bank)
          && !(|(busy[s_first[port][11:4+BANK_W]*16 +: 16] & s_keep[port]));
    end
    prism_fp32_stream_arbiter #(.PORTS(PORTS), .WIDTH(INPUT_W)) u_admission (
        .clk(clk), .rst_n(rst_n && !s_release),
        .s_data(port_data), .s_valid(request_valid),
        .s_ready(bank_source_ready[bank]),
        .m_data({slot, format, keep, raw_bits}),
        .m_valid(selected_valid), .m_ready(selected_ready)
    );
    for (genvar lane = 0; lane < 16; lane++) begin : gen_convert
      logic [31:0] int8_bits, fp16_bits, bf16_bits;
      prism_int8_to_fp32 u_int8 (
          .input_bits(raw_bits[lane*8 +: 8]), .output_bits(int8_bits));
      prism_fp16_to_fp32 u_fp16 (
          .input_bits(raw_bits[lane*16 +: 16]), .output_bits(fp16_bits));
      prism_bf16_to_fp32 u_bf16 (
          .input_bits(raw_bits[lane*16 +: 16]), .output_bits(bf16_bits));
      always_comb begin
        case (format)
          PRISM_FORMAT_INT8: native_bits[lane*32 +: 32] = int8_bits;
          PRISM_FORMAT_FP16: native_bits[lane*32 +: 32] = fp16_bits;
          PRISM_FORMAT_BF16: native_bits[lane*32 +: 32] = bf16_bits;
          default: native_bits[lane*32 +: 32] = raw_bits[lane*32 +: 32];
        endcase
      end
      assign expected[lane] = (32'(slot) << 4) + lane < s_total_elements;
    end
    prism_fp32_arrival_bank #(.ROWS(ROWS)) u_state (
        .clk(clk), .rst_n(rst_n), .s_release(s_release),
        .s_row(slot[7:BANK_W]), .s_bits(native_bits), .s_keep(keep),
        .s_expected_keep(expected), .s_children(s_children),
        .s_valid(selected_valid), .s_ready(selected_ready),
        .m_row(commit_row), .m_bits(commit_bits), .m_counts(commit_counts),
        .m_complete(commit_complete), .m_error(commit_error),
        .m_valid(commit_valid), .m_ready(commit_ready), .m_idle(bank_idle[bank]),
        .m_keep(commit_mask), .m_busy(busy),
        .m_result_row(result_row), .m_result_bits(result_bits),
        .m_result_keep(result_keep), .m_result_valid(result_valid),
        .m_result_error(result_error),
        .m_result_ready(queue_ready)
    );
    assign commit_ready = 1'b1;
    assign output_data[bank] = {result_row, BANK_W'(bank), result_keep, result_error, result_bits};
    assign output_valid[bank] = result_valid;
    assign queue_ready = output_ready[bank];
    always_ff @(posedge clk) begin
      if (!rst_n || s_release) bank_fault[bank] <= 1'b0;
      else if (commit_valid && commit_ready && commit_error) bank_fault[bank] <= 1'b1;
    end
    wire unused_commit = ^{commit_counts, commit_mask, commit_row, commit_bits, commit_complete};
  end

  prism_fp32_stream_arbiter #(.PORTS(BANKS), .WIDTH(OUTPUT_W)) u_result (
      .clk(clk), .rst_n(rst_n && !s_release),
      .s_data(output_data), .s_valid(output_valid), .s_ready(output_ready),
      .m_data({m_slot, m_present, m_error, m_bits}),
      .m_valid(m_valid), .m_ready(m_ready)
  );
endmodule
