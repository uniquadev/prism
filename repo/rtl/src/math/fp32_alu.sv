
// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

// Modulo: fp32_alu
//
// Descrizione:
//   ALU FP32 volutamente semplice. Riceve operandi già in formato FP32 e produce
//   un risultato FP32. Non conosce pacchetti, datatype del protocollo, chunk,
//   collective_id o expected_contributions.
//
// Stato attuale:
//   - FP32_ALU_ADD usa fp32_adder.
//   - MIN/MAX sono riservati per estensione futura.
module fp32_alu (
    input  fp32_alu_op_e alu_op,

    input  logic [31:0] lhs_fp32,
    input  logic [31:0] rhs_fp32,

    output logic [31:0] result_fp32
);

  logic [31:0] add_result_fp32;

  fp32_adder u_fp32_adder (
      .a(lhs_fp32),
      .b(rhs_fp32),
      .y(add_result_fp32)
  );

  always_comb begin
    result_fp32 = lhs_fp32;

    unique case (alu_op)
      FP32_ALU_ADD: begin
        result_fp32 = add_result_fp32;
      end

      FP32_ALU_MIN: begin
        // TODO: aggiungere fp32_min.
        result_fp32 = lhs_fp32;
      end

      FP32_ALU_MAX: begin
        // TODO: aggiungere fp32_max.
        result_fp32 = lhs_fp32;
      end

      default: begin
        result_fp32 = lhs_fp32;
      end
    endcase
  end

endmodule
