//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_to_bf16.sv
// Module: prism_fp32_to_bf16
// Description: Narrows binary32 to BF16 with ties-to-even rounding and status.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_to_bf16 (
    input  logic [31:0] input_bits,
    output logic [15:0] output_bits,
    output logic overflow,
    output logic underflow,
    output logic inexact,
    output logic canonical_nan
);

  logic [15:0] rounded;
  logic increment;

  always_comb begin
    increment = (input_bits[15:0] > 16'h8000)
        || ((input_bits[15:0] == 16'h8000) && input_bits[16]);
    rounded = input_bits[31:16] + {15'b0, increment};
    overflow = 1'b0;
    underflow = 1'b0;
    inexact = 1'b0;
    canonical_nan = 1'b0;

    if ((input_bits[30:23] == 8'hFF) && (input_bits[22:0] != 0)) begin
      output_bits = 16'h7FC0;
      canonical_nan = 1'b1;
    end else if (input_bits[30:23] == 8'hFF) begin
      output_bits = {input_bits[31], 8'hFF, 7'h00};
    end else begin
      output_bits = rounded;
      inexact = (input_bits[15:0] != 0);
      overflow = (input_bits[30:23] != 8'hFF) && (output_bits[14:7] == 8'hFF);
      underflow = (input_bits[30:23] != 0) && (output_bits[14:7] == 0) && inexact;
    end
  end

endmodule
