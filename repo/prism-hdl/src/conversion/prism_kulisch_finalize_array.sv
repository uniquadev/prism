//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_kulisch_finalize_array.sv
// Module: prism_kulisch_finalize_array
// Description: Finalizes all Kulisch lanes in parallel to binary32.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_kulisch_finalize_array #(
    parameter int unsigned ACC_W = 320,
    parameter int unsigned LANES = 16
) (
    input  logic signed [LANES*ACC_W-1:0] accumulators,
    input  prism_pkg::prism_wire_format_e  input_format,
    input  logic [LANES-1:0]               saw_nan,
    input  logic [LANES-1:0]               saw_positive_infinity,
    input  logic [LANES-1:0]               saw_negative_infinity,
    input  logic [LANES-1:0]               saw_finite_nonzero,
    input  logic [LANES-1:0]               saw_zero,
    input  logic [LANES-1:0]               all_zero_negative,
    output logic [LANES*32-1:0]            fp32_bits,
    output logic [LANES-1:0]               overflow,
    output logic [LANES-1:0]               underflow,
    output logic [LANES-1:0]               inexact
);

  initial begin
    if ((ACC_W < 8) || (ACC_W > 320) || (LANES < 1)) begin
      $fatal(1, "prism_kulisch_finalize_array parameters are illegal");
    end
  end

  for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
    prism_kulisch_to_fp32 #(
        .ACC_W(ACC_W)
    ) u_converter (
        .accumulator(accumulators[lane*ACC_W +: ACC_W]),
        .input_format(input_format),
        .saw_nan(saw_nan[lane]),
        .saw_positive_infinity(saw_positive_infinity[lane]),
        .saw_negative_infinity(saw_negative_infinity[lane]),
        .saw_finite_nonzero(saw_finite_nonzero[lane]),
        .saw_zero(saw_zero[lane]),
        .all_zero_negative(all_zero_negative[lane]),
        .fp32_bits(fp32_bits[lane*32 +: 32]),
        .overflow(overflow[lane]),
        .underflow(underflow[lane]),
        .inexact(inexact[lane])
    );
  end

endmodule
