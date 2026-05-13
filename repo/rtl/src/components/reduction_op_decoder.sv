
// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

// Modulo: reduction_op_decoder
//
// Descrizione:
//   Traduce l'operazione di riduzione del protocollo Mini-Sharp in una
//   operazione primitiva per la ALU FP32.
//
// Nota importante:
//   REDUCE_OP_AVG non è una singola operazione di ALU. In generale AVG richiede
//   una fase di accumulo tramite ADD e una fase finale di divisione per il numero
//   di contributi. Poiché il datapath non contiene ancora fp32_div, AVG viene
//   marcata come non supportata.
module reduction_op_decoder (
    // `op_flags` è il byte protocollo che codifica l'operazione di riduzione.
    input  logic [7:0]  op_flags,

    output fp32_alu_op_e alu_op,
    output logic         accumulation_supported,
    output logic         needs_finalization
);

  // =========================================================================
  // Descrizione
  // =========================================================================
  // Traduce il codice operativo del protocollo (campo `op_flags`) nella
  // primitiva ALU FP32 da eseguire e fornisce segnali che indicano se
  // l'operazione supporta l'accumulazione e se richiede una fase di
  // finalizzazione (ad es. AVG).

  always_comb begin
    alu_op                 = FP32_ALU_PASS;
    accumulation_supported = 1'b0;
    needs_finalization     = 1'b0;

    unique case (op_flags)
      REDUCE_OP_SUM: begin
        alu_op                 = FP32_ALU_ADD;
        accumulation_supported = 1'b1;
        needs_finalization     = 1'b0;
      end

      REDUCE_OP_MIN: begin
        alu_op                 = FP32_ALU_MIN;
        accumulation_supported = 1'b0; // fp32 min non ancora implementato
        needs_finalization     = 1'b0;
      end

      REDUCE_OP_MAX: begin
        alu_op                 = FP32_ALU_MAX;
        accumulation_supported = 1'b0; // fp32 max non ancora implementato
        needs_finalization     = 1'b0;
      end

      REDUCE_OP_AVG: begin
        alu_op                 = FP32_ALU_ADD;
        accumulation_supported = 1'b0; // richiede fp32_div in finalizzazione
        needs_finalization     = 1'b1;
      end

      default: begin
        alu_op                 = FP32_ALU_PASS;
        accumulation_supported = 1'b0;
        needs_finalization     = 1'b0;
      end
    endcase
  end

endmodule
