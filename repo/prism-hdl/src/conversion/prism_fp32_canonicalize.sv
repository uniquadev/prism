//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_canonicalize.sv
// Module: prism_fp32_canonicalize
// Description: Preserves non-NaNs and replaces every binary32 NaN with the canonical value.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_canonicalize (
    input  logic [31:0] input_bits,
    output logic [31:0] output_bits
);

  always_comb begin
    if ((input_bits[30:23] == 8'hFF) && (input_bits[22:0] != 0)) begin
      output_bits = 32'h7FC0_0000;
    end else begin
      output_bits = input_bits;
    end
  end

endmodule
