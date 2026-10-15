//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_segment_admission.sv
// Module: prism_numbergroup_segment_admission
// Description: Finds the lanes of a tile that fit in one packet body from a cursor.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Combinational. The tile is described by tables that do not depend on the
// cursor; the cursor selects one packet limit and the properties of the run
// it cuts. A lane is admitted when the padded body from the cursor up to and
// including that lane fits. The remaining outputs are the facts about the
// cursor that the segment choice needs.
module prism_numbergroup_segment_admission #(
    parameter int unsigned LANES = 64,
    parameter int unsigned LIMIT_W = 12,
    localparam int unsigned COUNT_W = $clog2(LANES + 1)
) (
    input  logic [COUNT_W-1:0]        s_cursor,
    input  logic [COUNT_W-1:0]        s_total,
    // A Kulisch value wider than the datapath is forwarded alone.
    input  logic                      s_forward_wide,
    // Per lane: padded body words up to the lane, first lane of its run and
    // the padding that closes the run at the lane.
    input  logic [LANES*LIMIT_W-1:0]  s_words,
    input  logic [LANES*COUNT_W-1:0]  s_origin,
    input  logic [LANES*2-1:0]        s_padding,
    input  logic [LANES*2-1:0]        s_end_padding,
    // Per cursor: body words available to a segment that starts there,
    // whether the cursor is the first lane of a run, and the first Kulisch
    // lane at or after it (LANES when there is none).
    input  logic [LANES*LIMIT_W-1:0]  s_limit,
    input  logic [LANES-1:0]          s_run_head,
    input  logic [LANES*COUNT_W-1:0]  s_first_wide,
    // The same per-lane values for the last lane of the tile.
    input  logic [LIMIT_W-1:0]        s_last_words,
    input  logic [COUNT_W-1:0]        s_last_origin,
    input  logic [1:0]                s_last_padding,
    output logic [LANES-1:0]          m_admitted,
    // Lanes at or beyond the first Kulisch lane that the segment cannot
    // hold: the first one sixteen or more lanes after the cursor.
    output logic [LANES-1:0]          m_beyond_far,
    output logic                      m_last_admitted,
    output logic                      m_cursor_admitted,
    output logic                      m_wide_at_cursor,
    output logic                      m_no_far,
    output logic                      m_one_left,
    output logic [COUNT_W-1:0]        m_far_wide,
    output logic [COUNT_W-1:0]        m_cursor_plus_one
);

  localparam int unsigned INDEX_W = LANES > 1 ? $clog2(LANES) : 1;

  logic [INDEX_W-1:0] index;
  logic [LIMIT_W-1:0] limit, cursor_words;
  logic [COUNT_W-1:0] cursor_origin, first_wide, far_wide;
  logic [LANES*COUNT_W-1:0] far_table;
  logic [1:0] consumed_padding, cursor_padding, cursor_end_padding;
  logic cursor_head, wide_allows_last;

  assign index = INDEX_W'(s_cursor);
  assign limit = s_limit[int'(index)*LIMIT_W +: LIMIT_W];
  assign cursor_head = s_run_head[index];
  assign cursor_origin = s_origin[int'(index)*COUNT_W +: COUNT_W];
  assign cursor_end_padding = s_end_padding[int'(index)*2 +: 2];
  assign cursor_words = s_words[int'(index)*LIMIT_W +: LIMIT_W];
  assign cursor_padding = s_padding[int'(index)*2 +: 2];
  assign first_wide = s_first_wide[int'(index)*COUNT_W +: COUNT_W];
  // The same table read sixteen lanes further: its entries are only wired
  // to other positions.
  for (genvar lane = 0; lane < LANES; lane++) begin : gen_far
    if (lane + 16 < LANES) begin : in_tile
      assign far_table[lane*COUNT_W +: COUNT_W] = s_first_wide[(lane+16)*COUNT_W +: COUNT_W];
    end else begin : past_tile
      assign far_table[lane*COUNT_W +: COUNT_W] = COUNT_W'(LANES);
    end
  end
  assign far_wide = far_table[int'(index)*COUNT_W +: COUNT_W];
  // Padding of the part of the run already sent, when the cursor cuts a run.
  if (LANES > 1) begin : gen_consumed
    logic [LANES*2-1:0] previous_padding;
    assign previous_padding = {s_padding[0 +: (LANES-1)*2], 2'b00};
    assign consumed_padding = previous_padding[int'(index)*2 +: 2];
  end else begin : gen_no_consumed
    assign consumed_padding = 2'b00;
  end

  // A segment that starts inside a run pays one more word when the padding
  // of the part already sent exceeds the padding of the part it carries.
  // "words < limit" stands for "words <= limit - 1": a legal MTU leaves a
  // body of more than one word, so the limit is never zero.
  function automatic logic fits(
      input logic [LIMIT_W-1:0] words,
      input logic [LIMIT_W-1:0] available,
      input logic inside_run,
      input logic [1:0] sent_padding,
      input logic [1:0] first_end_padding
  );
    logic tighter;
    tighter = inside_run && sent_padding > first_end_padding;
    return tighter ? words < available : words <= available;
  endfunction

  for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
    logic same_run;
    logic [1:0] first_end_padding;
    assign same_run = s_origin[lane*COUNT_W +: COUNT_W] == cursor_origin;
    assign first_end_padding = same_run ? s_padding[lane*2 +: 2] : cursor_end_padding;
    assign m_admitted[lane] = COUNT_W'(lane) >= s_cursor && COUNT_W'(lane) < s_total
        && (!s_forward_wide || COUNT_W'(lane) < first_wide)
        && fits(s_words[lane*LIMIT_W +: LIMIT_W], limit, !cursor_head, consumed_padding,
            first_end_padding);
    assign m_beyond_far[lane] = COUNT_W'(lane) >= far_wide;
  end
  assign wide_allows_last = !s_forward_wide || first_wide == COUNT_W'(LANES);
  assign m_last_admitted = wide_allows_last && fits(s_last_words, limit, !cursor_head,
      consumed_padding, s_last_origin == cursor_origin ? s_last_padding : cursor_end_padding);
  assign m_cursor_admitted = (!s_forward_wide || first_wide != s_cursor)
      && fits(cursor_words, limit, !cursor_head, consumed_padding, cursor_padding);
  assign m_wide_at_cursor = first_wide == s_cursor;
  assign m_no_far = far_wide == COUNT_W'(LANES);
  assign m_one_left = s_total - s_cursor == COUNT_W'(1);
  assign m_far_wide = far_wide;
  assign m_cursor_plus_one = s_cursor + COUNT_W'(1);

endmodule
