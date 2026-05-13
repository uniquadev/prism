
// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

// Modulo: reduction_input_converter
//
// Descrizione:
//   Converte una lane del payload Mini-Sharp nel formato interno FP32.
//
// Convenzione byte FP32:
//   Per DTYPE_FP32 il payload Mini-Sharp è little-endian:
//     byte 0 -> bit [7:0]
//     byte 1 -> bit [15:8]
//     byte 2 -> bit [23:16]
//     byte 3 -> bit [31:24]
//
// Stato attuale:
//   - DTYPE_INT8: 1 byte, interpretato come unsigned per compatibilità col test.
//   - DTYPE_FP32: 4 byte, nessuna conversione aritmetica.
//   - DTYPE_BF16/DTYPE_FP16: non ancora implementati.
module reduction_input_converter #(
    parameter int MAX_PACKET_BYTES = 2048
) (
    input  logic [(MAX_PACKET_BYTES*8)-1:0] frame,
    input  logic [31:0]                     byte_offset,
    input  logic [7:0]                      data_type,

    output logic [31:0]                     sample_fp32,
    output logic [2:0]                      lane_bytes,
    output logic                            data_type_supported
);

  logic [7:0] sample_u8;
  logic [31:0] sample_u8_fp32;

  assign sample_u8 = frame[8*(MINISHARP_PAYLOAD_OFFSET + byte_offset) +: 8];

  uint8_to_fp32 u_uint8_to_fp32 (
      .in_u8(sample_u8),
      .out_fp32(sample_u8_fp32)
  );

  always_comb begin
    sample_fp32         = 32'd0;
    lane_bytes          = 3'd0;
    data_type_supported = 1'b0;

    unique case (data_type)
      DTYPE_INT8: begin
        sample_fp32         = sample_u8_fp32;
        lane_bytes          = 3'd1;
        data_type_supported = 1'b1;
      end

      DTYPE_FP32: begin
        sample_fp32 = {
          frame[8*(MINISHARP_PAYLOAD_OFFSET + byte_offset + 3) +: 8],
          frame[8*(MINISHARP_PAYLOAD_OFFSET + byte_offset + 2) +: 8],
          frame[8*(MINISHARP_PAYLOAD_OFFSET + byte_offset + 1) +: 8],
          frame[8*(MINISHARP_PAYLOAD_OFFSET + byte_offset + 0) +: 8]
        };
        lane_bytes          = 3'd4;
        data_type_supported = 1'b1;
      end

      default: begin
        sample_fp32         = 32'd0;
        lane_bytes          = 3'd0;
        data_type_supported = 1'b0;
      end
    endcase
  end

endmodule
