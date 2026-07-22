//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp16_to_fp32.sv
// Module: prism_fp16_to_fp32
// Description: Widens one binary16 value, including subnormals, to binary32.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp16_to_fp32 (
    input  logic [15:0] input_bits,
    output logic [31:0] output_bits
);

  logic sign;
  logic [4:0] exponent16;
  logic [9:0] fraction16;
  logic [7:0] exponent32;
  logic [22:0] normalized;
  logic [3:0] leading_index;

  always_comb begin
    sign = input_bits[15];
    exponent16 = input_bits[14:10];
    fraction16 = input_bits[9:0];
    exponent32 = '0;
    normalized = '0;
    leading_index = 0;
    output_bits = '0;

    if (exponent16 == 5'h1F) begin
      output_bits = (fraction16 == 0) ? {sign, 8'hFF, 23'h0} : 32'h7FC0_0000;
    end else if (exponent16 != 0) begin
      exponent32 = {3'b0, exponent16} + 8'd112;
      output_bits = {sign, exponent32, fraction16, 13'h0};
    end else if (fraction16 != 0) begin
      for (int index = 0; index < 10; index++) begin
        if (fraction16[index]) begin
          leading_index = 4'(index);
        end
      end
      exponent32 = 8'd103 + {4'b0, leading_index};
      normalized = 23'(fraction16) << (5'd23 - {1'b0, leading_index});
      output_bits = {sign, exponent32, normalized};
    end else begin
      output_bits = {sign, 31'h0};
    end
  end

endmodule
