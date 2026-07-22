//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_fp32_to_kulisch.sv
// Module: prism_fp32_to_kulisch
// Description: Specializes binary-float deposit generation for FP32 operands.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_fp32_to_kulisch #(
    parameter int unsigned ACC_W = 288
) (
    input  logic [31:0] input_bits,
    output logic signed [ACC_W-1:0] deposit,
    output logic finite,
    output logic zero,
    output logic zero_sign,
    output logic nan,
    output logic positive_infinity,
    output logic negative_infinity,
    output logic overflow
);

  prism_binary_float_to_kulisch #(
      .EXP_W  (8),
      .FRAC_W (23),
      .ACC_W  (ACC_W)
  ) u_binary_float_to_kulisch (
      .input_bits        (input_bits),
      .deposit           (deposit),
      .finite            (finite),
      .zero              (zero),
      .zero_sign         (zero_sign),
      .nan               (nan),
      .positive_infinity (positive_infinity),
      .negative_infinity (negative_infinity),
      .overflow          (overflow)
  );

endmodule
