//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_native_tile_dispatch4.sv
// Module: prism_native_tile_dispatch4
// Description: Route up to four sixteen-element ranges from one native AXI tile.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_native_tile_dispatch4 #(
    parameter int unsigned BANKS = 4
) (
    input  logic         [31:0] s_first_element,
    input  logic         [7:0]  s_format,
    input  logic         [511:0] s_bits,
    input  logic         [63:0] s_keep,
    input  logic                s_valid,
    output logic                s_ready,
    output logic         [31:0] m_first_element [0:BANKS-1],
    output logic         [511:0] m_bits [0:BANKS-1],
    output logic         [15:0] m_keep [0:BANKS-1],
    output logic         [BANKS-1:0] m_valid,
    input  logic         [BANKS-1:0] m_ready
);

  localparam int unsigned BANK_W = $clog2(BANKS);
  logic [BANK_W-1:0] base_bank;
  logic [5:0] element_width;
  logic [BANKS-1:0] bank_present;
  initial begin
    if (BANKS != 4 && BANKS != 8)
      $fatal(1, "Native tile dispatch supports four or eight banks");
  end
  assign base_bank = s_first_element[BANK_W+3:4];
  assign element_width = s_format == 8'h01 ? 6'd8
      : s_format == 8'h02 || s_format == 8'h03 ? 6'd16 : 6'd32;

  for (genvar bank = 0; bank < BANKS; bank++) begin : gen_bank
    logic [BANK_W:0] relative_bank;
    logic bank_in_tile;
    assign bank_in_tile = (BANK_W+1)'(bank) >= {1'b0, base_bank};
    assign relative_bank = (BANK_W+1)'(bank) - {1'b0, base_bank};
    assign m_first_element[bank] = {s_first_element[31:BANK_W+4],
        {(BANK_W+4){1'b0}}}
        + 32'(bank * 16);
    assign m_keep[bank] = bank_in_tile
        ? 16'(s_keep >> (int'(relative_bank) * 16)) : '0;
    assign m_bits[bank] = bank_in_tile
        ? 512'(s_bits >> (int'(relative_bank) * 16 * int'(element_width))) : '0;
    assign bank_present[bank] = |m_keep[bank];
    assign m_valid[bank] = s_valid && s_ready && bank_present[bank];
  end

  assign s_ready = &((~bank_present) | m_ready);

endmodule
