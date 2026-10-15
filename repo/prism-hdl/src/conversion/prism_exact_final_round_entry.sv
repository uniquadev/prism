//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_final_round_entry.sv
// Module: prism_exact_final_round_entry
// Description: Accepts exact tiles for the final rounding and counts its queue places.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// The part of the final rounding that belongs with the source of the tiles:
// the handshake that accepts a tile, the count of the places in the result
// queue, and the first register of the tile. Everything it exchanges with
// the rounding itself goes from a register to a register, so the two can be
// placed apart.
module prism_exact_final_round_entry #(
    parameter int unsigned LANES = 16,
    parameter int unsigned KULISCH_W = 320,
    // Rounded tiles the queue behind the rounding holds.
    parameter int unsigned DEPTH = 32,
    // Places kept for tiles that have been asked for and are on their way.
    parameter int unsigned RESERVE = 8
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic [31:0]                s_first_element,
    input  logic [LANES-1:0]           s_element_keep,
    input  logic [LANES*8-1:0]         s_kulisch_tags,
    input  logic [LANES*KULISCH_W-1:0] s_kulisch_integers,
    input  logic [7:0]                 s_output_format,
    input  logic                       s_valid,
    output logic                       s_ready,
    // A source that cannot be stopped asks for a tile only while this is up:
    // the tiles it has already asked for then still find a place.
    output logic                       m_request_ready,
    // A rounded tile was taken from the queue in the cycle before.
    input  logic                       s_taken,
    // The tile register is kept as it is: another consumer of the same
    // tiles registers them too, elsewhere, and one register for both would
    // have to lie between them.
    (* dont_touch = "true" *) output logic [31:0]                m_first_element,
    (* dont_touch = "true" *) output logic [LANES-1:0]           m_element_keep,
    (* dont_touch = "true" *) output logic [LANES*8-1:0]         m_kulisch_tags,
    (* dont_touch = "true" *) output logic [LANES*KULISCH_W-1:0] m_kulisch_integers,
    output logic [7:0]                 m_output_format,
    output logic                       m_valid
);

  logic accept, credit;
  logic [$clog2(DEPTH+1)-1:0] held, held_next;

  assign s_ready = credit;
  assign accept = s_valid && s_ready;

  always_ff @(posedge clk) begin
    if (!rst_n) m_valid <= 1'b0;
    else m_valid <= accept;
  end
  always_ff @(posedge clk) begin
    m_first_element <= s_first_element;
    m_element_keep <= s_element_keep;
    m_kulisch_tags <= s_kulisch_tags;
    m_kulisch_integers <= s_kulisch_integers;
    m_output_format <= s_output_format;
  end

  // A tile holds a place from the cycle it is accepted until the cycle
  // after it is taken.
  always_comb begin
    held_next = held;
    case ({accept, s_taken})
      2'b10: held_next = held + 1'b1;
      2'b01: held_next = held - 1'b1;
      default: ;
    endcase
  end
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      held <= '0;
      credit <= 1'b1;
      m_request_ready <= 1'b0;
    end else begin
      held <= held_next;
      credit <= int'(held_next) < DEPTH;
      m_request_ready <= int'(held_next) + RESERVE < DEPTH;
    end
  end

endmodule
