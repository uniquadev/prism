//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_interval_window.sv
// Module: prism_numbergroup_interval_window
// Description: Atomic bounded element-interval admission per contributor.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// A frame is admitted when its element interval lies inside the window of
// its contributor and overlaps nothing admitted before. Admission and the
// update of the window are one step: the result is reported in the cycle
// after the frame is offered, as a reason code, and the window then already
// holds the frame.
//
// The comparisons behind that step are prepared ahead. The module sees the
// interval of every frame that may be offered next (CANDIDATES of them) and
// keeps, in two registered steps, what each would meet in the window of
// every contributor. Offering a frame then only selects prepared flags.
// The inputs that describe a candidate, the total and the window span must
// therefore be stable for two cycles before the candidate is offered and
// until its result is taken. The window itself changes only in the step that
// admits a frame and in the scan after it, both of which end before the
// result is reported, so the flags of the next frame are in place in time.
module prism_numbergroup_interval_window #(
    parameter int unsigned WINDOW_ELEMENTS = 512,
    parameter int unsigned MAX_INTERVALS = 16,
    parameter int unsigned CONTRIBUTORS = 2,
    parameter int unsigned CONTRIBUTOR_W = $clog2(CONTRIBUTORS),
    // Frames whose admission is prepared side by side.
    parameter int unsigned CANDIDATES = 1,
    localparam int unsigned CANDIDATE_W = CANDIDATES > 1 ? $clog2(CANDIDATES) : 1
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic [CANDIDATES*32-1:0]   s_first_element,
    input  logic [CANDIDATES*16-1:0]   s_element_count,
    input  logic [31:0]                s_total_elements,
    input  logic [15:0]                s_window_elements,
    // The offered frame: which candidate, from which contributor.
    input  logic [CANDIDATE_W-1:0]     s_candidate,
    input  logic [CONTRIBUTOR_W-1:0]   s_contributor_slot,
    input  logic                       s_last,
    input  logic                       s_valid,
    output logic                       s_ready,
    input  logic                       s_release,
    output logic                       s_release_ready,
    output logic [CONTRIBUTORS-1:0]    m_complete,
    output logic [CONTRIBUTORS*32-1:0] m_watermarks,
    output logic [1:0]                 m_reason,
    output logic                       m_valid,
    input  logic                       m_ready
);

  localparam logic [1:0] ACCEPT = 2'd0;
  localparam logic [1:0] INVALID_RANGE = 2'd1;
  localparam logic [1:0] OVERLAP = 2'd2;
  localparam logic [1:0] NO_CREDIT = 2'd3;
  localparam int unsigned ENTRY_W = $clog2(MAX_INTERVALS);
  localparam int unsigned COUNT_W = $clog2(MAX_INTERVALS + 1);

  typedef enum logic [1:0] {IDLE, DECIDE, SCAN, REPORT} state_t;
  state_t state;
  logic [31:0] watermark [0:CONTRIBUTORS-1];
  logic [31:0] interval_first [0:CONTRIBUTORS-1][0:MAX_INTERVALS-1];
  logic [31:0] interval_end [0:CONTRIBUTORS-1][0:MAX_INTERVALS-1];
  logic [MAX_INTERVALS-1:0] interval_valid [0:CONTRIBUTORS-1];
  logic [COUNT_W-1:0] interval_count [0:CONTRIBUTORS-1];
  logic [CONTRIBUTORS-1:0] last_seen;
  logic [31:0] total_elements_reg;
  logic total_known;
  logic [ENTRY_W-1:0] scan_slot;
  logic [CONTRIBUTOR_W-1:0] scan_contributor;

  initial begin
    if (WINDOW_ELEMENTS < 1 || WINDOW_ELEMENTS > 65535
        || MAX_INTERVALS < 2 || (MAX_INTERVALS & (MAX_INTERVALS - 1)) != 0
        || CONTRIBUTORS < 2 || CONTRIBUTOR_W < $clog2(CONTRIBUTORS) || CANDIDATES < 1)
      $fatal(1, "NumberGroup interval window requires bounded local resources");
  end

  // ------------------------------------------------------------ prepared
  // First step: the end of the interval. Second step: what the interval
  // meets in the window of each contributor.
  logic [31:0] first_a [0:CANDIDATES-1], first_b [0:CANDIDATES-1];
  logic [32:0] end_a [0:CANDIDATES-1], end_b [0:CANDIDATES-1];
  logic [CANDIDATES-1:0] filled_a, range_b, ends_at_total_b;
  logic [CONTRIBUTORS-1:0] in_window_b [0:CANDIDATES-1];
  logic [CONTRIBUTORS-1:0] overlap_b [0:CANDIDATES-1];
  logic [CONTRIBUTORS-1:0] at_watermark_b [0:CANDIDATES-1];
  logic [CONTRIBUTORS-1:0] free_b, pending_b;
  logic [ENTRY_W-1:0] free_slot_b [0:CONTRIBUTORS-1];

  for (genvar candidate = 0; candidate < CANDIDATES; candidate++) begin : gen_candidate
    logic [CONTRIBUTORS-1:0] in_window, overlap, at_watermark;
    always_ff @(posedge clk) begin
      first_a[candidate] <= s_first_element[candidate*32 +: 32];
      end_a[candidate] <= {1'b0, s_first_element[candidate*32 +: 32]}
          + 33'(s_element_count[candidate*16 +: 16]);
      filled_a[candidate] <= s_element_count[candidate*16 +: 16] != 0;

      first_b[candidate] <= first_a[candidate];
      end_b[candidate] <= end_a[candidate];
      range_b[candidate] <= filled_a[candidate] && s_total_elements != 0
          && end_a[candidate] <= {1'b0, s_total_elements}
          && (!total_known || total_elements_reg == s_total_elements)
          && s_window_elements != 0 && int'(s_window_elements) <= WINDOW_ELEMENTS;
      ends_at_total_b[candidate] <= end_a[candidate] == {1'b0, s_total_elements};
      in_window_b[candidate] <= in_window;
      overlap_b[candidate] <= overlap;
      at_watermark_b[candidate] <= at_watermark;
    end
    for (genvar contributor = 0; contributor < CONTRIBUTORS; contributor++) begin : at_contributor
      assign in_window[contributor] = end_a[candidate]
          <= {1'b0, watermark[contributor]} + 33'(s_window_elements);
      assign at_watermark[contributor] = first_a[candidate] == watermark[contributor];
      always_comb begin
        overlap[contributor] = first_a[candidate] < watermark[contributor];
        for (integer index = 0; index < MAX_INTERVALS; index++) begin
          if (interval_valid[contributor][index]
              && first_a[candidate] < interval_end[contributor][index]
              && end_a[candidate] > {1'b0, interval_first[contributor][index]})
            overlap[contributor] = 1'b1;
        end
      end
    end
  end
  // The free interval entry of a contributor does not depend on the frame.
  for (genvar contributor = 0; contributor < CONTRIBUTORS; contributor++) begin : gen_free
    logic free;
    logic [ENTRY_W-1:0] slot;
    always_comb begin
      free = 1'b0;
      slot = '0;
      for (integer index = 0; index < MAX_INTERVALS; index++) begin
        if (!interval_valid[contributor][index] && !free) begin
          free = 1'b1;
          slot = ENTRY_W'(index);
        end
      end
    end
    always_ff @(posedge clk) begin
      free_b[contributor] <= free;
      free_slot_b[contributor] <= slot;
      pending_b[contributor] <= interval_count[contributor] != 0;
    end
  end

  // ------------------------------------------------------------- decision
  logic [CANDIDATE_W-1:0] offered_candidate;
  logic [CONTRIBUTOR_W-1:0] offered_slot;
  logic offered_last;
  logic range_valid, overlapping, at_mark, free_found, scan_needed;
  logic [ENTRY_W-1:0] free_slot;
  logic [1:0] decided_reason, reason_reg;
  logic [31:0] offered_first;
  logic [32:0] offered_end;

  assign offered_first = first_b[offered_candidate];
  assign offered_end = end_b[offered_candidate];
  assign range_valid = range_b[offered_candidate]
      && offered_last == ends_at_total_b[offered_candidate]
      && int'(offered_slot) < CONTRIBUTORS
      && in_window_b[offered_candidate][offered_slot];
  assign overlapping = overlap_b[offered_candidate][offered_slot];
  assign at_mark = at_watermark_b[offered_candidate][offered_slot];
  assign free_found = free_b[offered_slot];
  assign free_slot = free_slot_b[offered_slot];
  always_comb begin
    if (!range_valid) decided_reason = INVALID_RANGE;
    else if (overlapping) decided_reason = OVERLAP;
    else if (!at_mark && !free_found) decided_reason = NO_CREDIT;
    else decided_reason = ACCEPT;
  end
  // An admitted frame that moves the watermark may release stored intervals;
  // its result is reported after that scan.
  assign scan_needed = decided_reason == ACCEPT && at_mark && pending_b[offered_slot];

  assign s_ready = state == IDLE && !s_release;
  assign s_release_ready = state == IDLE && !s_valid;
  assign m_valid = (state == DECIDE && !scan_needed) || state == REPORT;
  assign m_reason = state == DECIDE ? decided_reason : reason_reg;

  always_comb begin
    m_complete = '0;
    m_watermarks = '0;
    for (integer contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
      m_watermarks[contributor*32 +: 32] = watermark[contributor];
      m_complete[contributor] = total_known && last_seen[contributor]
          && watermark[contributor] == total_elements_reg;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE;
      reason_reg <= ACCEPT;
      last_seen <= '0;
      total_elements_reg <= '0;
      total_known <= 1'b0;
      scan_slot <= '0;
      scan_contributor <= '0;
      offered_candidate <= '0;
      offered_slot <= '0;
      offered_last <= 1'b0;
      for (integer contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
        watermark[contributor] <= '0;
        interval_valid[contributor] <= '0;
        interval_count[contributor] <= '0;
      end
    end else begin
      case (state)
        IDLE: begin
          if (s_release && s_release_ready) begin
            last_seen <= '0;
            total_elements_reg <= '0;
            total_known <= 1'b0;
            for (integer contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
              watermark[contributor] <= '0;
              interval_valid[contributor] <= '0;
              interval_count[contributor] <= '0;
            end
          end else if (s_valid && s_ready) begin
            offered_candidate <= s_candidate;
            offered_slot <= s_contributor_slot;
            offered_last <= s_last;
            state <= DECIDE;
          end
        end
        DECIDE: begin
          reason_reg <= decided_reason;
          state <= m_ready ? IDLE : REPORT;
          if (decided_reason == ACCEPT) begin
            total_elements_reg <= s_total_elements;
            total_known <= 1'b1;
            if (offered_last) last_seen[offered_slot] <= 1'b1;
            if (at_mark) begin
              watermark[offered_slot] <= offered_end[31:0];
              if (scan_needed) begin
                scan_contributor <= offered_slot;
                scan_slot <= '0;
                state <= SCAN;
              end
            end else begin
              interval_valid[offered_slot][free_slot] <= 1'b1;
              interval_first[offered_slot][free_slot] <= offered_first;
              interval_end[offered_slot][free_slot] <= offered_end[31:0];
              interval_count[offered_slot]
                  <= interval_count[offered_slot] + COUNT_W'(1);
            end
          end
        end
        SCAN: begin
          if (interval_valid[scan_contributor][scan_slot]
              && interval_first[scan_contributor][scan_slot]
                  == watermark[scan_contributor]) begin
            watermark[scan_contributor]
                <= interval_end[scan_contributor][scan_slot];
            interval_valid[scan_contributor][scan_slot] <= 1'b0;
            interval_count[scan_contributor]
                <= interval_count[scan_contributor] - COUNT_W'(1);
            scan_slot <= '0;
            if (interval_count[scan_contributor] == COUNT_W'(1)) state <= REPORT;
          end else if (scan_slot == ENTRY_W'(MAX_INTERVALS-1)) begin
            state <= REPORT;
          end else scan_slot <= scan_slot + ENTRY_W'(1);
        end
        REPORT: if (m_ready) state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end

endmodule
