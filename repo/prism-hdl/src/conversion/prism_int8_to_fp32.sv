//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_int8_to_fp32.sv
// Module: prism_int8_to_fp32
// Description: Converts one signed INT8 operand exactly to binary32.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_int8_to_fp32 (
    input  logic [7:0]  input_bits,
    output logic [31:0] output_bits
);

  logic sign;
  logic [7:0] magnitude;
  logic [22:0] normalized;
  logic [7:0] exponent;
  logic [2:0] leading_index;

  always_comb begin
    sign = input_bits[7];
    magnitude = sign ? (~input_bits + 1'b1) : input_bits;
    normalized = '0;
    exponent = '0;
    leading_index = 0;
    output_bits = '0;

    if (magnitude != 0) begin
      for (int index = 0; index < 8; index++) begin
        if (magnitude[index]) begin
          leading_index = 3'(index);
        end
      end
      exponent = 8'd127 + {5'b0, leading_index};
      normalized = 23'(magnitude) << (5'd23 - {2'b0, leading_index});
      output_bits = {sign, exponent, normalized};
    end
  end

endmodule
