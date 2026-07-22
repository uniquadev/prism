//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_int8_to_kulisch.sv
// Module: prism_int8_to_kulisch
// Description: Sign-extends one INT8 operand into the selected fixed-point width.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_int8_to_kulisch #(
    parameter int unsigned ACC_W = 64
) (
    input  logic [7:0] input_bits,
    output logic signed [ACC_W-1:0] deposit,
    output logic finite,
    output logic zero,
    output logic zero_sign,
    output logic nan,
    output logic positive_infinity,
    output logic negative_infinity,
    output logic overflow
);

  initial begin
    if (ACC_W < 8) begin
      $fatal(1, "prism_int8_to_kulisch ACC_W must be at least eight");
    end
  end

  always_comb begin
    deposit = {{(ACC_W-8){input_bits[7]}}, input_bits};
    finite = 1'b1;
    zero = (input_bits == 0);
    zero_sign = 1'b0;
    nan = 1'b0;
    positive_infinity = 1'b0;
    negative_infinity = 1'b0;
    overflow = 1'b0;
  end

endmodule
