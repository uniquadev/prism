
// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

// Modulo: reduction_output_converter
//
// Descrizione:
//   Converte il risultato FP32 interno nel formato payload di uscita.
//
// Stato attuale:
//   - DTYPE_INT8: FP32 -> UINT8 saturating.
//   - DTYPE_FP32: scrittura diretta dei 4 byte FP32 little-endian.
//   - DTYPE_BF16/DTYPE_FP16: non ancora implementati.
module reduction_output_converter (
    input  logic [31:0] value_fp32,
    input  logic [7:0]  data_type,

    output logic [31:0] encoded_bytes,
    output logic [2:0]  lane_bytes,
    output logic        data_type_supported
);

  logic [7:0] uint8_sat;

  fp32_to_uint8_sat u_fp32_to_uint8_sat (
      .in_fp32(value_fp32),
      .out_u8(uint8_sat)
  );

  always_comb begin
    encoded_bytes       = 32'd0;
    lane_bytes          = 3'd0;
    data_type_supported = 1'b0;

    unique case (data_type)
      DTYPE_INT8: begin
        encoded_bytes[7:0] = uint8_sat;
        lane_bytes          = 3'd1;
        data_type_supported = 1'b1;
      end

      DTYPE_FP32: begin
        // Scrittura little-endian nel payload Mini-Sharp.
        encoded_bytes[7:0]   = value_fp32[7:0];
        encoded_bytes[15:8]  = value_fp32[15:8];
        encoded_bytes[23:16] = value_fp32[23:16];
        encoded_bytes[31:24] = value_fp32[31:24];
        lane_bytes           = 3'd4;
        data_type_supported  = 1'b1;
      end

      default: begin
        encoded_bytes       = 32'd0;
        lane_bytes          = 3'd0;
        data_type_supported = 1'b0;
      end
    endcase
  end

endmodule
