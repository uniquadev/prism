//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_int8_to_kulisch.sv
// Module: prism_int8_to_kulisch
// Description: Maps INT8 to the common 2^-149 Kulisch fixed-point scale.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_int8_to_kulisch #(
    parameter int unsigned ACC_W = 279
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
    if ((ACC_W < 8) || (ACC_W > 320)) begin
      $fatal(1, "prism_int8_to_kulisch ACC_W must be in 8..320");
    end
  end

  logic signed [156:0] full_deposit;

  always_comb begin
    full_deposit = 157'($signed(input_bits)) <<< 149;
    deposit = ACC_W'(full_deposit);
    finite = 1'b1;
    zero = (input_bits == 0);
    zero_sign = 1'b0;
    nan = 1'b0;
    positive_infinity = 1'b0;
    negative_infinity = 1'b0;
    overflow = (ACC_W < 157)
        && (full_deposit != 157'($signed(deposit)));
  end

endmodule
