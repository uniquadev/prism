//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_segment_choice.sv
// Module: prism_numbergroup_segment_choice
// Description: Chooses where the segment that starts at a cursor ends.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Combinational. A segment carries every admitted lane up to one limit that
// keeps exact values on the sixteen low lanes of the datapath: it stops
// before the first Kulisch lane that lies sixteen or more lanes after its
// start. Lanes beyond the sixteenth are therefore native.
module prism_numbergroup_segment_choice #(
    parameter int unsigned LANES = 64,
    localparam int unsigned COUNT_W = $clog2(LANES + 1)
) (
    // Results of the admission for the cursor.
    input  logic [LANES-1:0]    s_admitted,
    input  logic [LANES-1:0]    s_beyond_far,
    input  logic                s_last_admitted,
    input  logic                s_cursor_admitted,
    input  logic                s_wide_at_cursor,
    input  logic                s_no_far,
    input  logic                s_one_left,
    input  logic [COUNT_W-1:0]  s_far_wide,
    input  logic [COUNT_W-1:0]  s_cursor_plus_one,
    // A Kulisch value wider than the datapath is forwarded alone.
    input  logic                s_forward_wide,
    // The segment is [cursor, m_end).
    output logic [COUNT_W-1:0]  m_end,
    output logic                m_last,
    output logic                m_valid
);

  logic [COUNT_W-1:0] admitted_end;
  logic forward, past_far;

  always_comb begin
    admitted_end = '0;
    for (int lane = 0; lane < LANES; lane++)
      if (s_admitted[lane]) admitted_end = COUNT_W'(lane + 1);
  end

  assign forward = s_wide_at_cursor && s_forward_wide;
  assign past_far = |(s_admitted & s_beyond_far);

  always_comb begin
    m_end = admitted_end;
    if (forward) m_end = s_cursor_plus_one;
    else if (past_far) m_end = s_far_wide;
  end

  assign m_last = forward ? s_one_left : s_last_admitted && s_no_far;
  assign m_valid = s_cursor_admitted || forward;

endmodule
