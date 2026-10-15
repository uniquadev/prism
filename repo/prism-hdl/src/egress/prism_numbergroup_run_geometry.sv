//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_run_geometry.sv
// Module: prism_numbergroup_run_geometry
// Description: Computes prefix byte costs, run origins and padding for one lane bank.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// A run is a maximal sequence of lanes with the same format; on the wire it
// is one NumberGroup: a four-byte descriptor and its values padded to a
// four-byte boundary. For every lane the module reports the padded byte cost
// of the bank up to and including that lane, the first lane of its run, the
// padding that would close the run at that lane, and the padding that closes
// the run at its real end.
//
// The module never stalls. Results appear RUN_GEOMETRY_STEPS cycles after
// the inputs.
module prism_numbergroup_run_geometry #(
    parameter int unsigned LANES = 16,
    parameter int unsigned BYTE_W = 12,
    parameter int unsigned COUNT_W = 7,
    parameter int unsigned BASE = 0,
    localparam int unsigned SUMMARY_W = BYTE_W + COUNT_W + 22,
    localparam int unsigned PREFIX_STAGES = $clog2(LANES)
) (
    input  logic                                 clk,
    input  logic [LANES*8-1:0]                   s_formats,
    input  logic [15:0]                          s_kulisch_bits,
    input  logic [LANES-1:0]                     s_keep,
    output logic [LANES*(BYTE_W+COUNT_W+4)-1:0]  m_geometry,
    output logic [SUMMARY_W-1:0]                 m_active_summary
);

  localparam int unsigned INDEX_W = LANES > 1 ? $clog2(LANES) : 1;
  localparam int unsigned FIRST_LEVELS = (PREFIX_STAGES + 1) / 2;

  function automatic int unsigned width_for(input logic [7:0] format, input logic [15:0] wire_bits);
    case (format)
      prism_pkg::PRISM_FORMAT_INT8: return 1;
      prism_pkg::PRISM_FORMAT_FP16, prism_pkg::PRISM_FORMAT_BF16: return 2;
      prism_pkg::PRISM_FORMAT_FP32: return 4;
      prism_pkg::PRISM_FORMAT_KULISCH: return 1 + (int'(wire_bits) + 7) / 8;
      default: return 0;
    endcase
  endfunction

  // Step 1: value widths, run boundaries and the first lane of every run.
  logic [LANES*BYTE_W-1:0] width, width_1;
  logic [LANES-1:0] head, head_1, run_end, run_end_1, keep_1;
  logic [LANES*COUNT_W-1:0] origin_scan [0:PREFIX_STAGES];
  logic [LANES-1:0] origin_found [0:PREFIX_STAGES];
  logic [LANES*COUNT_W-1:0] origin_1;
  logic [LANES*8-1:0] formats_1;
  for (genvar lane = 0; lane < LANES; lane++) begin : gen_boundary
    assign width[lane*BYTE_W +: BYTE_W]
        = BYTE_W'(width_for(s_formats[lane*8 +: 8], s_kulisch_bits));
    if (lane == 0) begin : first
      assign head[lane] = 1'b1;
    end else begin : following
      assign head[lane] = s_formats[lane*8 +: 8] != s_formats[(lane-1)*8 +: 8];
    end
    if (lane + 1 == LANES) begin : final_end
      assign run_end[lane] = 1'b1;
    end else begin : next_end
      assign run_end[lane] = s_formats[lane*8 +: 8] != s_formats[(lane+1)*8 +: 8];
    end
    assign origin_found[0][lane] = head[lane];
    assign origin_scan[0][lane*COUNT_W +: COUNT_W] = COUNT_W'(lane);
  end
  for (genvar level = 1; level <= PREFIX_STAGES; level++) begin : gen_origin_scan
    for (genvar lane = 0; lane < LANES; lane++) begin : at_lane
      if (lane >= (1 << (level-1))) begin : combine
        localparam int unsigned PREVIOUS = lane - (1 << (level-1));
        assign origin_found[level][lane]
            = origin_found[level-1][lane] || origin_found[level-1][PREVIOUS];
        assign origin_scan[level][lane*COUNT_W +: COUNT_W] = origin_found[level-1][lane]
            ? origin_scan[level-1][lane*COUNT_W +: COUNT_W]
            : origin_scan[level-1][PREVIOUS*COUNT_W +: COUNT_W];
      end else begin : copy
        assign origin_found[level][lane] = origin_found[level-1][lane];
        assign origin_scan[level][lane*COUNT_W +: COUNT_W]
            = origin_scan[level-1][lane*COUNT_W +: COUNT_W];
      end
    end
  end
  always_ff @(posedge clk) begin
    width_1 <= width;
    head_1 <= head;
    run_end_1 <= run_end;
    keep_1 <= s_keep;
    origin_1 <= origin_scan[PREFIX_STAGES];
    formats_1 <= s_formats;
  end

  // Step 2: padding, the bytes each lane adds, and the padding at the end
  // of every run.
  logic [LANES*2-1:0] padding, padding_2;
  logic [LANES*BYTE_W-1:0] added, added_2;
  logic [LANES*2-1:0] end_scan [0:PREFIX_STAGES];
  logic [LANES-1:0] end_found [0:PREFIX_STAGES];
  logic [LANES*2-1:0] end_padding_2;
  logic [LANES*COUNT_W-1:0] origin_2;
  logic [LANES*8-1:0] formats_2;
  logic [INDEX_W-1:0] last_active, last_active_2;
  logic active_2;
  for (genvar lane = 0; lane < LANES; lane++) begin : gen_padding
    logic [1:0] residue;
    assign residue = (2'(lane+1) - 2'(origin_1[lane*COUNT_W +: COUNT_W]))
        * width_1[lane*BYTE_W +: 2];
    assign padding[lane*2 +: 2] = 2'b00 - residue;
    if (lane == 0) begin : initial_cost
      assign added[lane*BYTE_W +: BYTE_W] = width_1[lane*BYTE_W +: BYTE_W] + BYTE_W'(4);
    end else begin : incremental_cost
      assign added[lane*BYTE_W +: BYTE_W] = width_1[lane*BYTE_W +: BYTE_W]
          + (head_1[lane] ? BYTE_W'(4) + BYTE_W'(padding[(lane-1)*2 +: 2]) : BYTE_W'(0));
    end
    assign end_found[0][lane] = run_end_1[lane];
    assign end_scan[0][lane*2 +: 2] = padding[lane*2 +: 2];
  end
  for (genvar level = 1; level <= PREFIX_STAGES; level++) begin : gen_end_scan
    for (genvar lane = 0; lane < LANES; lane++) begin : at_lane
      if (lane + (1 << (level-1)) < LANES) begin : combine
        localparam int unsigned NEXT = lane + (1 << (level-1));
        assign end_found[level][lane] = end_found[level-1][lane] || end_found[level-1][NEXT];
        assign end_scan[level][lane*2 +: 2] = end_found[level-1][lane]
            ? end_scan[level-1][lane*2 +: 2] : end_scan[level-1][NEXT*2 +: 2];
      end else begin : copy
        assign end_found[level][lane] = end_found[level-1][lane];
        assign end_scan[level][lane*2 +: 2] = end_scan[level-1][lane*2 +: 2];
      end
    end
  end
  assign last_active = (|keep_1) ? INDEX_W'($countones(keep_1) - 1) : '0;
  always_ff @(posedge clk) begin
    padding_2 <= padding;
    added_2 <= added;
    end_padding_2 <= end_scan[PREFIX_STAGES];
    origin_2 <= origin_1;
    formats_2 <= formats_1;
    last_active_2 <= last_active;
    active_2 <= |keep_1;
  end

  // Steps 3 and 4: prefix sum of the added bytes, half of the levels each.
  logic [LANES*BYTE_W-1:0] first_sum [0:FIRST_LEVELS];
  logic [LANES*BYTE_W-1:0] second_sum [FIRST_LEVELS:PREFIX_STAGES];
  logic [LANES*BYTE_W-1:0] sum_3, sum_4;
  logic [LANES*2-1:0] padding_3, padding_4, end_padding_3, end_padding_4;
  logic [LANES*COUNT_W-1:0] origin_3, origin_4;
  logic [LANES*8-1:0] formats_3, formats_4;
  logic [INDEX_W-1:0] last_active_3, last_active_4;
  logic active_3, active_4;
  assign first_sum[0] = added_2;
  assign second_sum[FIRST_LEVELS] = sum_3;
  for (genvar level = 1; level <= PREFIX_STAGES; level++) begin : gen_sum
    for (genvar lane = 0; lane < LANES; lane++) begin : at_lane
      if (level <= FIRST_LEVELS) begin : first_half
        if (lane >= (1 << (level-1))) begin : combine
          assign first_sum[level][lane*BYTE_W +: BYTE_W]
              = first_sum[level-1][lane*BYTE_W +: BYTE_W]
              + first_sum[level-1][(lane-(1 << (level-1)))*BYTE_W +: BYTE_W];
        end else begin : copy
          assign first_sum[level][lane*BYTE_W +: BYTE_W]
              = first_sum[level-1][lane*BYTE_W +: BYTE_W];
        end
      end else begin : second_half
        if (lane >= (1 << (level-1))) begin : combine
          assign second_sum[level][lane*BYTE_W +: BYTE_W]
              = second_sum[level-1][lane*BYTE_W +: BYTE_W]
              + second_sum[level-1][(lane-(1 << (level-1)))*BYTE_W +: BYTE_W];
        end else begin : copy
          assign second_sum[level][lane*BYTE_W +: BYTE_W]
              = second_sum[level-1][lane*BYTE_W +: BYTE_W];
        end
      end
    end
  end
  always_ff @(posedge clk) begin
    sum_3 <= first_sum[FIRST_LEVELS];
    padding_3 <= padding_2;
    end_padding_3 <= end_padding_2;
    origin_3 <= origin_2;
    formats_3 <= formats_2;
    last_active_3 <= last_active_2;
    active_3 <= active_2;
    sum_4 <= second_sum[PREFIX_STAGES];
    padding_4 <= padding_3;
    end_padding_4 <= end_padding_3;
    origin_4 <= origin_3;
    formats_4 <= formats_3;
    last_active_4 <= last_active_3;
    active_4 <= active_3;
  end

  // Step 5: padded prefix costs and the summary of the active lanes.
  logic [LANES*BYTE_W-1:0] cost;
  logic [COUNT_W-1:0] last_origin;
  logic [1:0] first_residue, last_residue;
  for (genvar lane = 0; lane < LANES; lane++) begin : gen_cost
    assign cost[lane*BYTE_W +: BYTE_W] = sum_4[lane*BYTE_W +: BYTE_W]
        + BYTE_W'(padding_4[lane*2 +: 2]);
  end
  assign last_origin = origin_4[int'(last_active_4)*COUNT_W +: COUNT_W];
  assign last_residue = 2'b00 - padding_4[int'(last_active_4)*2 +: 2];
  assign first_residue = last_origin == 0 ? last_residue : 2'b00 - end_padding_4[0 +: 2];
  always_ff @(posedge clk) begin
    m_geometry <= {cost, origin_4, padding_4, end_padding_4};
    m_active_summary <= active_4
        ? {1'b1, cost[int'(last_active_4)*BYTE_W +: BYTE_W], formats_4[0 +: 8],
           formats_4[int'(last_active_4)*8 +: 8], first_residue, last_residue,
           last_origin == 0, COUNT_W'(BASE) + last_origin}
        : '0;
  end

endmodule
