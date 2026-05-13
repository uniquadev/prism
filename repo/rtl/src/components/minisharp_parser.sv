// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

module minisharp_parser #(
    parameter int MAX_PACKET_BYTES = 2048
) (
    input  logic [(MAX_PACKET_BYTES*8)-1:0] frame,
    input  logic [15:0]                     frame_len,

    output logic                            valid_minisharp,
    output logic [31:0]                     chunk_id,
    output logic [31:0]                     p_size,
    output logic [7:0]                      op_flags,
    output logic [15:0]                     flow_id,
    output logic [7:0]                      collective_op,
    output logic [7:0]                      data_type,
    output logic [7:0]                      collective_flags,
    output logic [7:0]                      reserved,
    output logic [15:0]                     expected_contributions,
    output logic [15:0]                     contribution_index,

    output logic                            is_reduce_sum_int8
);

  logic [31:0] required_len;

  always_comb begin
    chunk_id = {
      frame[8*(CHUNK_ID_OFFSET + 3) +: 8],
      frame[8*(CHUNK_ID_OFFSET + 2) +: 8],
      frame[8*(CHUNK_ID_OFFSET + 1) +: 8],
      frame[8*(CHUNK_ID_OFFSET + 0) +: 8]
    };

    p_size = {
      frame[8*(P_SIZE_OFFSET + 3) +: 8],
      frame[8*(P_SIZE_OFFSET + 2) +: 8],
      frame[8*(P_SIZE_OFFSET + 1) +: 8],
      frame[8*(P_SIZE_OFFSET + 0) +: 8]
    };

    // flow_id is encoded little-endian in the Mini-Sharp header.
    flow_id = {
      frame[8*(FLOW_ID_OFFSET + 1) +: 8],
      frame[8*(FLOW_ID_OFFSET + 0) +: 8]
    };

    // `op_flags` è un singolo byte che contiene informazioni specifiche
    // sull'operazione di riduzione; lo esponiamo come campo a 8 bit.
    op_flags = frame[8*OP_FLAGS_OFFSET +: 8];

    collective_op    = frame[8*COLLECTIVE_OP_OFFSET +: 8];
    data_type        = frame[8*DATA_TYPE_OFFSET +: 8];
    collective_flags = frame[8*COLLECTIVE_FLAGS_OFFSET +: 8];
    reserved         = frame[8*RESERVED_OFFSET +: 8];

    expected_contributions = {
      frame[8*(EXPECTED_CONTRIB_OFFSET + 1) +: 8],
      frame[8*(EXPECTED_CONTRIB_OFFSET + 0) +: 8]
    };

    contribution_index = {
      frame[8*(CONTRIBUTION_INDEX_OFFSET + 1) +: 8],
      frame[8*(CONTRIBUTION_INDEX_OFFSET + 0) +: 8]
    };

    required_len = MINISHARP_PAYLOAD_OFFSET + p_size;

    valid_minisharp =
      (frame_len >= MINISHARP_PAYLOAD_OFFSET) &&
      (frame_len >= required_len);

    is_reduce_sum_int8 =
      valid_minisharp &&
      (op_flags       == REDUCE_OP_SUM) &&
      (collective_op == COLLECTIVE_REDUCE) &&
      (data_type     == DTYPE_INT8);
  end

endmodule
