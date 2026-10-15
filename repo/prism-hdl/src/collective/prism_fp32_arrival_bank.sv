//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_arrival_bank.sv
// Module: prism_fp32_arrival_bank
// Description: Online FP32 read-modify-write state with local RAW exclusion.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_arrival_bank #(
    parameter int unsigned ROWS = 64,
    localparam int unsigned ROW_W = $clog2(ROWS)
) (
    input logic clk,
    input logic rst_n,
    input logic s_release,
    input logic [ROW_W-1:0] s_row,
    input logic [511:0] s_bits,
    input logic [15:0] s_keep,
    input logic [15:0] s_expected_keep,
    input logic [3:0] s_children,
    input logic s_valid,
    output logic s_ready,
    output logic [ROW_W-1:0] m_row,
    output logic [511:0] m_bits,
    output logic [63:0] m_counts,
    output logic [15:0] m_keep,
    output logic m_complete,
    output logic m_error,
    output logic m_valid,
    input logic m_ready,
    output logic [ROW_W-1:0] m_result_row,
    output logic [511:0] m_result_bits,
    output logic [15:0] m_result_keep,
    output logic m_result_valid,
    output logic m_result_error,
    input logic m_result_ready,
    output logic m_idle,
    output logic [ROWS*16-1:0] m_busy
);
  // Each lane has one synchronous 36-bit RAM (sum and contribution count).
  // Reserve only lanes being updated: a packet boundary can split a row
  // without creating a dependency between its disjoint element positions.
  // The read port serves updates and completed-row snapshots; writes are
  // masked by the committed lanes. No same-lane read/write collision is legal.
  localparam int unsigned TAG_W = ROW_W + 64 + 16 + 16 + 1;
  localparam int unsigned RESULT_W = ROW_W + 16 + 512 + 1;
  logic [15:0] initialized [0:ROWS-1];
  logic [ROWS*16-1:0] pending, completed;
  logic read_valid, read_ready, read_result, read_error;
  logic [ROWS-1:0] row_error;
  logic [ROW_W-1:0] read_row, ram_address;
  logic [511:0] read_bits, prior_bits, canonical_bits;
  logic [15:0] read_keep, read_expected, read_initialized, prior_present;
  logic [3:0] read_children;
  logic [63:0] next_counts;
  logic next_error;
  logic [TAG_W-1:0] update_tag;
  logic [15:0] commit_expected, commit_done, done_after;
  logic update_valid, update_ready, read_ready_update;
  logic accept, commit, snapshot_accept;
  logic [35:0] ram_word [0:15];
  logic [ROW_W+16:0] snapshot_data;
  logic snapshot_valid, snapshot_ready, snapshot_queue_ready;
  logic result_queue_ready;

  initial begin
    if (ROWS < 2 || (ROWS & (ROWS-1)) != 0)
      $fatal(1, "FP32 arrival bank requires power-of-two rows");
  end

  assign snapshot_ready = (!read_valid || read_ready) && !s_release;
  assign snapshot_accept = snapshot_valid && snapshot_ready;
  assign s_ready = rst_n && !s_release && (!read_valid || read_ready)
      && !snapshot_valid && !(|(m_busy[s_row*16 +: 16] & s_keep));
  assign accept = s_valid && s_ready;
  assign ram_address = snapshot_accept ? snapshot_data[ROW_W+16:17]
      : accept ? s_row : read_row;
  assign m_busy = pending | completed;
  assign m_idle = !(|pending) && !read_valid && !update_valid
      && !snapshot_valid && !m_result_valid;
  assign {m_row, m_counts, m_keep, commit_expected, m_error} = update_tag;
  assign done_after = completed[m_row*16 +: 16] | commit_done;
  assign m_complete = commit_expected != 0
      && (done_after & commit_expected) == commit_expected;
  // A completed row must have a snapshot slot before its final write commits.
  // While that write waits, no later write can change its completion status.
  assign m_valid = update_valid && (!m_complete || snapshot_queue_ready);
  assign update_ready = m_ready && (!m_complete || snapshot_queue_ready);
  assign commit = m_valid && m_ready;

  for (genvar lane = 0; lane < 16; lane++) begin : gen_lane
    prism_fp32_canonicalize u_canonical (
        .input_bits(s_bits[lane*32 +: 32]),
        .output_bits(canonical_bits[lane*32 +: 32])
    );
    prism_sync_ram_1w1r #(
        .WIDTH(36), .DEPTH(ROWS), .ADDR_W(ROW_W), .BLOCK_RAM(1'b1)
    ) u_state (
        .clk(clk), .write_enable(commit && m_keep[lane] && !s_release),
        .write_address(m_row),
        .write_data({m_counts[lane*4 +: 4], m_bits[lane*32 +: 32]}),
        .read_address(ram_address), .read_data(ram_word[lane])
    );
    assign prior_bits[lane*32 +: 32] = read_initialized[lane] && (read_result || read_keep[lane])
        ? ram_word[lane][31:0] : 32'b0;
    assign prior_present[lane] = read_initialized[lane] && read_keep[lane]
        && ram_word[lane][35:32] != 0;
    assign commit_done[lane] = m_keep[lane] && m_counts[lane*4 +: 4] == s_children;

    // Lane-local ownership: disjoint masks on the same row can overlap in
    // the arithmetic pipeline, but each actual element remains serialized.
    always_ff @(posedge clk) begin
      if (!rst_n || s_release) begin
        for (integer row = 0; row < ROWS; row++) begin
          initialized[row][lane] <= 1'b0;
          pending[row*16+lane] <= 1'b0;
          completed[row*16+lane] <= 1'b0;
        end
      end else begin
        if (commit && m_keep[lane]) begin
          initialized[m_row][lane] <= 1'b1;
          pending[m_row*16+lane] <= 1'b0;
          completed[m_row*16+lane] <= commit_done[lane];
        end
        if (accept && s_keep[lane]) pending[s_row*16+lane] <= 1'b1;
      end
    end
  end

  always_comb begin
    next_error = read_children == 0 || read_children > 8
        || (read_keep & ~read_expected) != 0 || read_keep == 0;
    for (integer lane = 0; lane < 16; lane++) begin
      next_counts[lane*4 +: 4] = read_initialized[lane] && read_keep[lane]
          ? ram_word[lane][35:32] : 4'b0;
      if (read_keep[lane]) begin
        if (next_counts[lane*4 +: 4] >= read_children) next_error = 1'b1;
        next_counts[lane*4 +: 4]++;
      end
    end
  end

  prism_fp32_accumulate_tile #(.TAG_W(TAG_W)) u_accumulate (
      .clk(clk), .rst_n(rst_n && !s_release),
      .s_sum(prior_bits), .s_bits(read_bits),
      .s_present(prior_present), .s_keep(read_keep),
      .s_tag({read_row, next_counts, read_keep, read_expected, next_error}),
      .s_valid(read_valid && !read_result), .s_ready(read_ready_update),
      .m_bits(m_bits), .m_tag(update_tag),
      .m_valid(update_valid), .m_ready(update_ready)
  );
  assign read_ready = read_result ? result_queue_ready : read_ready_update;

  prism_elastic_skid_buffer #(.WIDTH(ROW_W+17)) u_snapshot_request (
      .clk(clk), .rst_n(rst_n && !s_release),
      .s_data({m_row, commit_expected, row_error[m_row] || m_error}), .s_valid(commit && m_complete),
      .s_ready(snapshot_queue_ready), .m_data(snapshot_data),
      .m_valid(snapshot_valid), .m_ready(snapshot_ready)
  );
  prism_elastic_skid_buffer #(.WIDTH(RESULT_W)) u_snapshot_result (
      .clk(clk), .rst_n(rst_n && !s_release),
      .s_data({read_row, read_expected, read_error, prior_bits}),
      .s_valid(read_valid && read_result), .s_ready(result_queue_ready),
      .m_data({m_result_row, m_result_keep, m_result_error, m_result_bits}),
      .m_valid(m_result_valid), .m_ready(m_result_ready)
  );

  always_ff @(posedge clk) begin
    if (!rst_n || s_release) begin
      read_valid <= 1'b0;
      read_row <= '0;
      read_initialized <= '0;
      read_result <= 1'b0;
      read_error <= 1'b0;
    end else if (!read_valid || read_ready) begin
      read_valid <= accept || snapshot_accept;
      if (snapshot_accept) begin
        read_row <= snapshot_data[ROW_W+16:17];
        read_expected <= snapshot_data[16:1];
        read_error <= snapshot_data[0];
        read_initialized <= initialized[snapshot_data[ROW_W+16:17]];
        read_result <= 1'b1;
      end else if (accept) begin
        read_row <= s_row;
        read_initialized <= initialized[s_row];
        read_bits <= canonical_bits;
        read_keep <= s_keep;
        read_expected <= s_expected_keep;
        read_children <= s_children;
        read_result <= 1'b0;
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n || s_release) row_error <= '0;
    else if (commit) row_error[m_row] <= row_error[m_row] || m_error;
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (rst_n && !s_release && commit
        && (pending[m_row*16 +: 16] & m_keep) != m_keep)
      $fatal(1, "FP32 bank committed unreserved lanes");
    if (rst_n && !s_release && accept && commit && s_row == m_row && |(s_keep & m_keep))
      $fatal(1, "FP32 bank read/write collision escaped RAW exclusion");
  end
`endif
endmodule
