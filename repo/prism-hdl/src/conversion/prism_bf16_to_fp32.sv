//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_bf16_to_fp32.sv
// Module: prism_bf16_to_fp32
// Description: Widens one BF16 bit pattern to canonical binary32.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_bf16_to_fp32 (
    input  logic [15:0] input_bits,
    output logic [31:0] output_bits
);

  always_comb begin
    if ((input_bits[14:7] == 8'hFF) && (input_bits[6:0] != 0)) begin
      output_bits = 32'h7FC0_0000;
    end else begin
      output_bits = {input_bits, 16'h0000};
    end
  end

endmodule
