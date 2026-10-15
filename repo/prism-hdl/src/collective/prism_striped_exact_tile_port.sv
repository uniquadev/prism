//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_striped_exact_tile_port.sv
// Module: prism_striped_exact_tile_port
// Description: Four independent range banks share one 512-bit native tile port.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_striped_exact_tile_port #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_ORIGINAL_TERMS = 16,
    parameter int unsigned BANKS = 4,
    parameter int unsigned RESULT_LANES = 16
) (
    input  logic                     clk,
    input  logic                     rst_n,
    input  logic [31:0]              s_first_element,
    input  logic [7:0]               s_format,
    input  logic [511:0]             s_bits,
    input  logic [63:0]              s_keep,
    input  logic                     s_valid,
    output logic                     s_ready,
    // Drop the tiles that wait in front of the banks.
    input  logic                     s_flush,
    input  logic                     s_release,
    output logic                     s_release_ready,
    input  logic [7:0]               s_result_slot,
    input  logic                     s_wide_result,
    input  logic                     s_result_read_valid,
    output logic                     s_result_read_ready,
    output logic [7:0]               m_result_slot,
    output logic [RESULT_LANES-1:0]  m_result_present,
    output logic [RESULT_LANES*8-1:0] m_result_tags,
    output logic [RESULT_LANES*KULISCH_W-1:0] m_result_integers,
    output logic                     m_result_valid,
    output logic                     m_arithmetic_fault
);

  localparam int unsigned BANK_W = $clog2(BANKS);
  localparam int unsigned SLOT_W = 8 - BANK_W;
  logic [31:0] bank_first [0:BANKS-1];
  logic [511:0] bank_bits [0:BANKS-1];
  logic [15:0] bank_keep [0:BANKS-1];
  logic [BANKS-1:0] bank_input_valid, bank_input_ready;
  logic [BANKS-1:0] bank_release_ready, bank_read_ready;
  logic [BANKS-1:0] bank_result_valid, bank_value_valid;
  logic [SLOT_W-1:0] bank_result_slot [0:BANKS-1];
  logic [15:0] bank_result_present [0:BANKS-1];
  logic [127:0] bank_result_tags [0:BANKS-1];
  logic [16*KULISCH_W-1:0] bank_result_integers [0:BANKS-1];
  logic [31:0] bank_errors [0:BANKS-1];
  // The bank and the width a request asked for, one register behind the
  // request and one more with its result.
  logic [BANK_W-1:0] fetched_bank, selected_bank;
  logic fetched_wide, selected_wide;
  // The bank that supplies the low tile of a result: bank 0 for a wide
  // result, the requested bank otherwise. Each lane of the low tile has its
  // own copies of it at both register steps, so the choice lies with the
  // lane it serves and is not sent to every bit from one place.
  (* dont_touch = "true" *) logic [BANK_W-1:0] fetched_low [0:15];
  (* dont_touch = "true" *) logic [BANK_W-1:0] selected_low [0:15];
  logic read_request;

  initial begin
    if ((BANKS != 4 && BANKS != 8)
        || (RESULT_LANES != 16 && RESULT_LANES != BANKS*16))
      $fatal(1, "Striped exact readout requires a supported bank width");
  end

  prism_native_tile_dispatch4 #(.BANKS(BANKS)) u_dispatch (
      .s_first_element(s_first_element), .s_format(s_format),
      .s_bits(s_bits), .s_keep(s_keep), .s_valid(s_valid),
      .s_ready(s_ready), .m_first_element(bank_first),
      .m_bits(bank_bits), .m_keep(bank_keep),
      .m_valid(bank_input_valid), .m_ready(bank_input_ready)
  );

  // A read request is registered before it reaches the banks, so the
  // requester's handshake does not drive the memory addresses of every lane.
  // The registered request arms the banks; it is granted to all of them in
  // the same cycle, so their results arrive together, two cycles later, and
  // stay for one cycle.
  logic [7:0] request_slot;
  logic request_wide, request_valid;
  prism_elastic_register #(.WIDTH(9)) u_read_request (
      .clk(clk), .rst_n(rst_n),
      .s_data({s_wide_result, s_result_slot}), .s_valid(s_result_read_valid),
      .s_ready(s_result_read_ready),
      .m_data({request_wide, request_slot}), .m_valid(request_valid),
      .m_ready(&bank_read_ready)
  );
  assign s_release_ready = &bank_release_ready && !request_valid;
  assign read_request = request_valid && (&bank_read_ready);
  assign m_result_valid = bank_result_valid[0];
  assign m_result_slot = selected_wide
      ? (8'(bank_result_slot[0]) << BANK_W)
      : {bank_result_slot[selected_bank], selected_bank};
  // Presence qualifies each lane. Unselected upper banks need no payload
  // zeroing: keeping their local read data avoids broadcasting selected_wide
  // across every integer bit. The low tile still selects the requested bank.
  // No request, validity, read credit, or latency changes at this boundary.
  always_comb begin
    m_result_present = '0;
    m_result_tags = '0;
    m_result_integers = '0;
    if (RESULT_LANES == BANKS*16) begin
      for (integer bank = 1; bank < BANKS; bank++) begin
        m_result_present[bank*16 +: 16] = selected_wide
            ? bank_result_present[bank] : '0;
        m_result_tags[bank*128 +: 128] = bank_result_tags[bank];
        m_result_integers[bank*16*KULISCH_W +: 16*KULISCH_W]
            = bank_result_integers[bank];
      end
    end
    for (integer lane = 0; lane < 16; lane++) begin
      m_result_present[lane] = bank_result_present[selected_low[lane]][lane];
      m_result_tags[lane*8 +: 8] = bank_result_tags[selected_low[lane]][lane*8 +: 8];
      m_result_integers[lane*KULISCH_W +: KULISCH_W]
          = bank_result_integers[selected_low[lane]][lane*KULISCH_W +: KULISCH_W];
    end
  end
  always_comb begin
    m_arithmetic_fault = 1'b0;
    for (integer bank = 0; bank < BANKS; bank++)
      m_arithmetic_fault |= bank_value_valid[bank] && (|bank_errors[bank]);
  end

  always_ff @(posedge clk) begin
    fetched_bank <= request_slot[BANK_W-1:0];
    fetched_wide <= RESULT_LANES == BANKS*16 && request_wide;
    selected_bank <= fetched_bank;
    selected_wide <= fetched_wide;
    for (integer lane = 0; lane < 16; lane++) begin
      fetched_low[lane] <= RESULT_LANES == BANKS*16 && request_wide
          ? BANK_W'(0) : request_slot[BANK_W-1:0];
      selected_low[lane] <= fetched_low[lane];
    end
    if (rst_n && bank_result_valid != {BANKS{bank_result_valid[0]}})
      $fatal(1, "Striped exact banks returned their results apart");
    if (rst_n && m_result_valid) begin
      for (integer bank = 1; bank < BANKS; bank++) begin
        if (bank_result_slot[bank] != bank_result_slot[0])
          $fatal(1, "Striped exact banks returned different range slots");
      end
    end
  end

  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_bank
    // Each bank takes its part of a tile from a buffer of its own, so the
    // dispatch sees only whether the buffers have room, and what a bank
    // decides about its part (a slot still in its stages, the checks of the
    // part) stays inside the bank.
    logic [31:0] held_first;
    logic [7:0] held_format;
    logic [511:0] held_bits;
    logic [15:0] held_keep;
    logic held_valid, held_ready;
    prism_elastic_skid_buffer #(.WIDTH(32 + 8 + 512 + 16)) u_input (
        .clk(clk), .rst_n(rst_n && !s_flush),
        .s_data({bank_first[bank], s_format, bank_bits[bank], bank_keep[bank]}),
        .s_valid(bank_input_valid[bank]), .s_ready(bank_input_ready[bank]),
        .m_data({held_first, held_format, held_bits, held_keep}),
        .m_valid(held_valid), .m_ready(held_ready)
    );
    prism_exact_native_tile_pipeline #(
        .RANGES(256/BANKS), .KULISCH_W(KULISCH_W),
        .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS),
        .STRIPE_BITS(BANK_W), .STRIPE_INDEX(bank)
    ) u_pipeline (
        .clk(clk), .rst_n(rst_n),
        .s_slot(held_first[11:BANK_W+4]),
        .s_first_element(held_first),
        .s_format(held_format), .s_element_bits(held_bits),
        .s_element_keep(held_keep),
        .s_valid(held_valid),
        .s_ready(held_ready),
        .s_release(s_release),
        .s_release_ready(bank_release_ready[bank]),
        .s_result_slot(request_wide && RESULT_LANES == BANKS*16
            ? request_slot[SLOT_W-1:0] : request_slot[7:BANK_W]),
        .s_result_read_arm(request_valid),
        .s_result_read_valid(read_request),
        .s_result_read_ready(bank_read_ready[bank]),
        .m_result_slot(bank_result_slot[bank]),
        .m_result_present(bank_result_present[bank]),
        .m_result_tags(bank_result_tags[bank]),
        .m_result_integers(bank_result_integers[bank]),
        .m_result_valid(bank_result_valid[bank]),
        .m_first_element(), .m_element_keep(),
        .m_kulisch_tags(), .m_kulisch_integers(),
        .m_errors(bank_errors[bank]),
        .m_valid(bank_value_valid[bank]), .m_ready(1'b1)
    );
  end

endmodule
