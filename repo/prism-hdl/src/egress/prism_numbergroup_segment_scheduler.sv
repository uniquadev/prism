//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_segment_scheduler.sv
// Module: prism_numbergroup_segment_scheduler
// Description: Splits the lanes of each tile into segments that fit the MTU.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// The scheduler sees only the formats of a tile, never its values. For each
// accepted tile it emits one or more segments in order: a first lane, a lane
// count and the formats of those lanes. A segment is a whole number of
// values and its NumberGroup body fits the packet.
//
// A tile whose lanes are all exact in FP32 is sent as one FP32 group when
// that costs fewer bytes than the formats chosen lane by lane; m_group_fp32
// tells the reader to take the FP32 form of the values.
//
// Three parts follow each other:
//   1. a geometry pipeline without stalls, which turns formats into byte
//      costs, the tables the splitting needs and the first segment;
//   2. a queue of prepared tiles;
//   3. loops that find the later segments of a tile, two cycles each, and
//      a collector that takes the segments in the order of the tiles.
// A tile with a single segment takes one cycle of a loop, so such tiles pass
// at one per cycle. With two loops, tiles of several segments yield more than
// one segment per cycle between them, which is what the reader can take.
module prism_numbergroup_segment_scheduler #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned LANES = 16,
    // Tiles accepted and not yet started. At least the number of steps of
    // the geometry pipeline is needed to accept a tile every cycle.
    parameter int unsigned QUEUE_DEPTH = 32,
    // Tiles whose later segments are found at the same time.
    parameter int unsigned LOOPS = 2,
    localparam int unsigned COUNT_W = $clog2(LANES + 1)
) (
    input  logic                 clk,
    input  logic                 rst_n,
    input  logic                 s_clear,
    input  logic [15:0]          s_mtu,
    input  logic [15:0]          s_kulisch_bits,
    input  logic [31:0]          s_first_element,
    input  logic [LANES-1:0]     s_keep,
    input  logic [LANES*8-1:0]   s_formats,
    input  logic                 s_fp32_eligible,
    input  logic                 s_error,
    input  logic                 s_valid,
    output logic                 s_ready,
    output logic [31:0]          m_first_element,
    output logic [COUNT_W-1:0]   m_count,
    output logic [COUNT_W-1:0]   m_cursor,
    output logic                 m_last,
    output logic [LANES*8-1:0]   m_formats,
    output logic                 m_group_fp32,
    output logic                 m_valid,
    input  logic                 m_ready,
    output logic                 m_fault
);

  import prism_numbergroup_geometry_pkg::*;

  localparam int unsigned BANKS = (LANES + 15) / 16;
  localparam int unsigned BYTE_W = byte_width(KULISCH_W, LANES);
  localparam int unsigned GEO_W = geometry_width(KULISCH_W, LANES);
  localparam int unsigned SUMMARY_W = summary_width(KULISCH_W, LANES);
  // Padded costs are multiples of four, so packet limits are kept in words.
  // The width covers the legal MTU range even for a one-lane instance.
  localparam int unsigned LIMIT_W = BYTE_W < 10 ? 10 : BYTE_W;
  localparam int unsigned INDEX_W = LANES > 1 ? $clog2(LANES) : 1;
  localparam int unsigned SCAN_LEVELS = $clog2(LANES);
  localparam int unsigned FIRST_SCAN_LEVELS = (SCAN_LEVELS + 1) / 2;
  localparam int unsigned OUTPUT_DEPTH = 16;

  // Steps of the geometry pipeline, counted from the accepting clock edge.
  localparam int unsigned GEOMETRY_STEP = 1 + RUN_GEOMETRY_STEPS;
  localparam int unsigned GROUP_STEP = GEOMETRY_STEP + scan_steps(BANKS) + 1;
  localparam int unsigned JOIN_STEP = GEOMETRY_STEP + join_steps(BANKS);
  localparam int unsigned COST_STEP = JOIN_STEP + 1;
  localparam int unsigned TABLE_STEP = COST_STEP + 1;
  localparam int unsigned QUEUE_STEP = TABLE_STEP + 2;

  initial begin
    if (GROUP_STEP + 2 != JOIN_STEP || LANES < 16 || QUEUE_DEPTH < 2 || LOOPS < 1)
      $fatal(1, "segment scheduler steps are not aligned");
  end

  // ---------------------------------------------------------------- input
  logic accept, legal, tile_credit, output_credit;
  logic [15:0] body_budget;
  logic [QUEUE_STEP:1] valid;
  logic [31:0] first_1;
  logic [LANES-1:0] keep_1;
  logic [LANES*8-1:0] formats_1;
  logic eligible_1, forward_1;
  logic [15:0] kulisch_bits_1;
  logic [LIMIT_W-1:0] budget_1;

  // The kept lanes are the low lanes of the tile, without gaps.
  if (LANES > 1) begin : gen_keep_check
    assign legal = !s_error && s_keep[0] && !(|(s_keep[LANES-1:1] & ~s_keep[LANES-2:0]))
        && s_mtu >= 16'd576 && s_mtu <= 16'd1500;
  end else begin : gen_single_keep
    assign legal = !s_error && s_keep[0] && s_mtu >= 16'd576 && s_mtu <= 16'd1500;
  end
  assign s_ready = tile_credit && !s_clear && !m_fault;
  assign accept = s_valid && s_ready;
  assign body_budget = s_mtu
      - 16'(prism_pkg::PRISM_CONTROL_WORD_BYTES + prism_pkg::PRISM_DATA_HEADER_BYTES);

  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) valid <= '0;
    else valid <= {valid[QUEUE_STEP-1:1], accept && legal};
  end
  always_ff @(posedge clk) begin
    first_1 <= s_first_element;
    keep_1 <= s_keep;
    formats_1 <= s_formats;
    eligible_1 <= s_fp32_eligible;
    kulisch_bits_1 <= s_kulisch_bits;
    forward_1 <= int'(s_kulisch_bits) > KULISCH_W;
    budget_1 <= LIMIT_W'(body_budget >> 2);
  end

  // ------------------------------------------------------ bank geometry
  logic [COUNT_W-1:0] count_2;
  logic [GEO_W-1:0] local_geometry, joined_geometry;
  logic [BANKS*SUMMARY_W-1:0] active_summaries;
  logic [SUMMARY_W-1:0] active_total;
  always_ff @(posedge clk) count_2 <= COUNT_W'($countones(keep_1));

  prism_numbergroup_local_geometry #(.KULISCH_W(KULISCH_W), .LANES(LANES)) u_local (
      .clk(clk), .s_formats(formats_1), .s_keep(keep_1), .s_kulisch_bits(kulisch_bits_1),
      .m_geometry(local_geometry), .m_active_summaries(active_summaries)
  );
  prism_numbergroup_summary_scan #(
      .BANKS(BANKS), .BYTE_W(BYTE_W), .COUNT_W(COUNT_W)
  ) u_total (
      .clk(clk), .s_summaries(active_summaries), .m_prefix(), .m_suffix(),
      .m_total(active_total)
  );

  // ---------------------------------------------------------- FP32 group
  // One FP32 group costs a descriptor and four bytes per value.
  logic [COUNT_W-1:0] group_count, count_group, count_cost;
  logic group_eligible, group;
  logic [LANES-1:0] keep_group;
  logic [LANES*8-1:0] formats_group, formats_final;
  prism_delay_line #(.WIDTH(COUNT_W), .STEPS(GROUP_STEP - 3)) u_count_total (
      .clk(clk), .s_data(count_2), .m_data(group_count)
  );
  prism_delay_line #(.WIDTH(1), .STEPS(GROUP_STEP - 2)) u_eligible_total (
      .clk(clk), .s_data(eligible_1), .m_data(group_eligible)
  );
  always_ff @(posedge clk) begin
    group <= group_count != 0 && group_eligible
        && BYTE_W'(4 + 4 * int'(group_count)) < active_total[SUMMARY_W-2 -: BYTE_W];
    count_group <= group_count;
  end
  prism_delay_line #(.WIDTH(LANES + LANES*8), .STEPS(GROUP_STEP - 1)) u_formats_group (
      .clk(clk), .s_data({keep_1, formats_1}), .m_data({keep_group, formats_group})
  );
  always_ff @(posedge clk) begin
    for (int lane = 0; lane < LANES; lane++)
      formats_final[lane*8 +: 8] <= group && keep_group[lane]
          ? prism_pkg::PRISM_FORMAT_FP32 : formats_group[lane*8 +: 8];
  end

  // ------------------------------------- first Kulisch lane from each lane
  // Two steps: the formats are final one step after the group decision.
  logic [COUNT_W-1:0] count_final;
  logic [LANES-1:0] wide_found [0:SCAN_LEVELS];
  logic [LANES*COUNT_W-1:0] wide_index [0:SCAN_LEVELS];
  logic [LANES-1:0] wide_found_half;
  logic [LANES*COUNT_W-1:0] wide_index_half, first_wide_cost;
  prism_delay_line #(.WIDTH(COUNT_W), .STEPS(1)) u_count_final (
      .clk(clk), .s_data(count_group), .m_data(count_final)
  );
  for (genvar level = 0; level <= SCAN_LEVELS; level++) begin : gen_wide_scan
    for (genvar lane = 0; lane < LANES; lane++) begin : at_lane
      if (level == 0) begin : leaf
        assign wide_found[0][lane] = COUNT_W'(lane) < count_final
            && formats_final[lane*8 +: 8] == prism_pkg::PRISM_FORMAT_KULISCH;
        assign wide_index[0][lane*COUNT_W +: COUNT_W] = COUNT_W'(lane);
      end else if (level == FIRST_SCAN_LEVELS + 1 && lane + (1 << (level-1)) < LANES) begin : resume
        localparam int unsigned NEXT = lane + (1 << (level-1));
        assign wide_found[level][lane] = wide_found_half[lane] || wide_found_half[NEXT];
        assign wide_index[level][lane*COUNT_W +: COUNT_W] = wide_found_half[lane]
            ? wide_index_half[lane*COUNT_W +: COUNT_W]
            : wide_index_half[NEXT*COUNT_W +: COUNT_W];
      end else if (level == FIRST_SCAN_LEVELS + 1) begin : resume_copy
        assign wide_found[level][lane] = wide_found_half[lane];
        assign wide_index[level][lane*COUNT_W +: COUNT_W]
            = wide_index_half[lane*COUNT_W +: COUNT_W];
      end else if (lane + (1 << (level-1)) < LANES) begin : combine
        localparam int unsigned NEXT = lane + (1 << (level-1));
        assign wide_found[level][lane] = wide_found[level-1][lane] || wide_found[level-1][NEXT];
        assign wide_index[level][lane*COUNT_W +: COUNT_W] = wide_found[level-1][lane]
            ? wide_index[level-1][lane*COUNT_W +: COUNT_W]
            : wide_index[level-1][NEXT*COUNT_W +: COUNT_W];
      end else begin : copy
        assign wide_found[level][lane] = wide_found[level-1][lane];
        assign wide_index[level][lane*COUNT_W +: COUNT_W]
            = wide_index[level-1][lane*COUNT_W +: COUNT_W];
      end
    end
  end
  logic [LANES-1:0] wide_found_end;
  logic [LANES*COUNT_W-1:0] wide_index_end;
  if (FIRST_SCAN_LEVELS == SCAN_LEVELS) begin : gen_short_scan
    assign wide_found_end = wide_found_half;
    assign wide_index_end = wide_index_half;
  end else begin : gen_long_scan
    assign wide_found_end = wide_found[SCAN_LEVELS];
    assign wide_index_end = wide_index[SCAN_LEVELS];
  end
  always_ff @(posedge clk) begin
    wide_found_half <= wide_found[FIRST_SCAN_LEVELS];
    wide_index_half <= wide_index[FIRST_SCAN_LEVELS];
    for (int lane = 0; lane < LANES; lane++)
      first_wide_cost[lane*COUNT_W +: COUNT_W] <= wide_found_end[lane]
          ? wide_index_end[lane*COUNT_W +: COUNT_W] : COUNT_W'(LANES);
  end

  // ------------------------------------------------------- tile geometry
  logic [LANES*8-1:0] formats_geometry;
  logic group_join;
  logic [LANES*BYTE_W-1:0] joined_cost, cost;
  logic [LANES*COUNT_W-1:0] joined_origin, origin;
  logic [LANES*2-1:0] joined_pad, joined_end, pad, end_pad;
  prism_delay_line #(.WIDTH(LANES*8), .STEPS(GEOMETRY_STEP - 1)) u_formats_geometry (
      .clk(clk), .s_data(formats_1), .m_data(formats_geometry)
  );
  prism_numbergroup_join_geometry #(.KULISCH_W(KULISCH_W), .LANES(LANES)) u_join (
      .clk(clk), .s_formats(formats_geometry), .s_geometry(local_geometry),
      .m_geometry(joined_geometry)
  );
  prism_delay_line #(.WIDTH(1), .STEPS(JOIN_STEP - GROUP_STEP)) u_group_join (
      .clk(clk), .s_data(group), .m_data(group_join)
  );
  assign {joined_cost, joined_origin, joined_pad, joined_end} = joined_geometry;
  always_ff @(posedge clk) begin
    for (int lane = 0; lane < LANES; lane++)
      cost[lane*BYTE_W +: BYTE_W] <= group_join
          ? BYTE_W'(4 + 4 * (lane + 1)) : joined_cost[lane*BYTE_W +: BYTE_W];
    origin <= group_join ? '0 : joined_origin;
    pad <= group_join ? '0 : joined_pad;
    end_pad <= group_join ? '0 : joined_end;
  end

  // ------------------------------------------------- tables of the tile
  // Everything the splitting reads, indexed by lane or by cursor.
  typedef struct packed {
    logic forward;
    logic [COUNT_W-1:0] count;
    logic [LANES*LIMIT_W-1:0] words;
    logic [LANES*COUNT_W-1:0] origin;
    logic [LANES*2-1:0] padding;
    logic [LANES*2-1:0] end_padding;
    logic [LANES*LIMIT_W-1:0] limit;
    logic [LANES-1:0] run_head;
    logic [LANES*COUNT_W-1:0] first_wide;
    logic [LIMIT_W-1:0] last_words;
    logic [COUNT_W-1:0] last_origin;
    logic [1:0] last_padding;
  } tile_t;
  localparam int unsigned TILE_W = $bits(tile_t);
  // What the output needs of a tile once its segments are known.
  typedef struct packed {
    logic [31:0] first;
    logic group;
    logic [LANES*8-1:0] formats;
  } context_t;
  localparam int unsigned CONTEXT_W = $bits(context_t);

  logic [31:0] first_cost;
  logic group_cost, forward_cost;
  logic [LIMIT_W-1:0] budget_cost;
  logic [LANES*8-1:0] formats_cost;
  logic [INDEX_W-1:0] last_index;
  tile_t table_next, table_reg;
  context_t context_cost, context_chosen;
  prism_delay_line #(.WIDTH(32 + 1 + LIMIT_W), .STEPS(COST_STEP - 1)) u_context_cost (
      .clk(clk), .s_data({first_1, forward_1, budget_1}),
      .m_data({first_cost, forward_cost, budget_cost})
  );
  prism_delay_line #(.WIDTH(COUNT_W + LANES*8), .STEPS(COST_STEP - GROUP_STEP - 1))
  u_formats_cost (
      .clk(clk), .s_data({count_final, formats_final}), .m_data({count_cost, formats_cost})
  );
  prism_delay_line #(.WIDTH(1), .STEPS(COST_STEP - JOIN_STEP)) u_group_cost (
      .clk(clk), .s_data(group_join), .m_data(group_cost)
  );
  assign last_index = INDEX_W'(count_cost - COUNT_W'(1));
  always_comb begin
    table_next = '0;
    table_next.forward = forward_cost;
    table_next.count = count_cost;
    table_next.origin = origin;
    table_next.padding = pad;
    table_next.end_padding = end_pad;
    table_next.first_wide = first_wide_cost;
    for (int lane = 0; lane < LANES; lane++) begin
      table_next.words[lane*LIMIT_W +: LIMIT_W] = LIMIT_W'(cost[lane*BYTE_W +: BYTE_W] >> 2);
      table_next.run_head[lane] = origin[lane*COUNT_W +: COUNT_W] == COUNT_W'(lane);
      // Words left for a segment that starts at this lane: the words spent
      // before it do not count, and continuing a run costs a new descriptor.
      table_next.limit[lane*LIMIT_W +: LIMIT_W]
          = (lane == 0 ? LIMIT_W'(0) : LIMIT_W'(cost[(lane == 0 ? 0 : lane-1)*BYTE_W +: BYTE_W] >> 2))
          + budget_cost
          - (origin[lane*COUNT_W +: COUNT_W] == COUNT_W'(lane) ? LIMIT_W'(0) : LIMIT_W'(1));
    end
    table_next.last_words = LIMIT_W'(cost[int'(last_index)*BYTE_W +: BYTE_W] >> 2);
    table_next.last_origin = origin[int'(last_index)*COUNT_W +: COUNT_W];
    table_next.last_padding = pad[int'(last_index)*2 +: 2];
    context_cost.first = first_cost;
    context_cost.group = group_cost;
    context_cost.formats = formats_cost;
  end
  always_ff @(posedge clk) table_reg <= table_next;
  prism_delay_line #(.WIDTH(CONTEXT_W), .STEPS(QUEUE_STEP - COST_STEP)) u_context_chosen (
      .clk(clk), .s_data(context_cost), .m_data(context_chosen)
  );

  // ------------------------------------------- first segment of the tile
  typedef struct packed {
    logic [LANES-1:0] admitted;
    logic [LANES-1:0] beyond_far;
    logic last_admitted;
    logic cursor_admitted;
    logic wide_at_cursor;
    logic no_far;
    logic one_left;
    logic [COUNT_W-1:0] far_wide;
    logic [COUNT_W-1:0] cursor_plus_one;
  } admission_t;
  typedef struct packed {
    logic [COUNT_W-1:0] segment_end;
    logic last;
    logic valid;
  } choice_t;

  admission_t first_admission, first_admission_reg;
  choice_t first_choice, first_choice_reg;
  tile_t table_admitted, table_chosen;

  prism_numbergroup_segment_admission #(.LANES(LANES), .LIMIT_W(LIMIT_W)) u_first_admission (
      .s_cursor('0), .s_total(table_reg.count), .s_forward_wide(table_reg.forward),
      .s_words(table_reg.words), .s_origin(table_reg.origin), .s_padding(table_reg.padding),
      .s_end_padding(table_reg.end_padding), .s_limit(table_reg.limit),
      .s_run_head(table_reg.run_head), .s_first_wide(table_reg.first_wide),
      .s_last_words(table_reg.last_words), .s_last_origin(table_reg.last_origin),
      .s_last_padding(table_reg.last_padding),
      .m_admitted(first_admission.admitted), .m_beyond_far(first_admission.beyond_far),
      .m_last_admitted(first_admission.last_admitted),
      .m_cursor_admitted(first_admission.cursor_admitted),
      .m_wide_at_cursor(first_admission.wide_at_cursor),
      .m_no_far(first_admission.no_far), .m_one_left(first_admission.one_left),
      .m_far_wide(first_admission.far_wide),
      .m_cursor_plus_one(first_admission.cursor_plus_one)
  );
  always_ff @(posedge clk) begin
    first_admission_reg <= first_admission;
    table_admitted <= table_reg;
  end
  prism_numbergroup_segment_choice #(.LANES(LANES)) u_first_choice (
      .s_admitted(first_admission_reg.admitted),
      .s_beyond_far(first_admission_reg.beyond_far),
      .s_last_admitted(first_admission_reg.last_admitted),
      .s_cursor_admitted(first_admission_reg.cursor_admitted),
      .s_wide_at_cursor(first_admission_reg.wide_at_cursor),
      .s_no_far(first_admission_reg.no_far), .s_one_left(first_admission_reg.one_left),
      .s_far_wide(first_admission_reg.far_wide),
      .s_cursor_plus_one(first_admission_reg.cursor_plus_one),
      .s_forward_wide(table_admitted.forward),
      .m_end(first_choice.segment_end), .m_last(first_choice.last),
      .m_valid(first_choice.valid)
  );
  always_ff @(posedge clk) begin
    first_choice_reg <= first_choice;
    table_chosen <= table_admitted;
  end

  // --------------------------------------------------------------- queues
  // The tables of a tile wait for a free loop; what the output needs of the
  // tile waits until its last segment has been collected.
  tile_t queue_tile;
  choice_t queue_choice;
  context_t queue_context;
  logic queue_valid, queue_ready, start, context_done;
  logic context_ready, context_valid;
  prism_elastic_fifo #(
      .WIDTH(TILE_W + $bits(choice_t)), .DEPTH(QUEUE_DEPTH),
      .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
  ) u_tiles (
      .clk(clk), .rst_n(rst_n && !s_clear),
      .s_data({table_chosen, first_choice_reg}), .s_valid(valid[QUEUE_STEP]),
      .s_ready(queue_ready),
      .m_data({queue_tile, queue_choice}), .m_valid(queue_valid), .m_ready(start),
      .occupancy()
  );
  prism_elastic_fifo #(
      .WIDTH(CONTEXT_W), .DEPTH(QUEUE_DEPTH), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
  ) u_contexts (
      .clk(clk), .rst_n(rst_n && !s_clear),
      .s_data(context_chosen), .s_valid(valid[QUEUE_STEP]), .s_ready(context_ready),
      .m_data(queue_context), .m_valid(context_valid), .m_ready(context_done),
      .occupancy()
  );

  // ---------------------------------------------------------------- loops
  // A loop holds one tile and finds its later segments, two cycles each.
  // Tiles enter the loops in turn and their segments are collected in the
  // same turn, which keeps the order of the tiles. While a loop is idle its
  // register follows the head of the queue, so a tile is in place one cycle
  // after it enters.
  localparam int unsigned TURN_W = LOOPS > 1 ? $clog2(LOOPS) : 1;
  localparam int unsigned FOUND_DEPTH = 8;
  localparam int unsigned LOAD_BITS = 256;
  localparam int unsigned LOAD_COPIES = (TILE_W + LOAD_BITS - 1) / LOAD_BITS;
  typedef struct packed {
    logic [COUNT_W-1:0] cursor;
    logic [COUNT_W-1:0] segment_end;
    logic last;
  } segment_t;
  logic [TILE_W-1:0] queue_bits;
  logic [TURN_W-1:0] turn_in, turn_out;
  logic [LOOPS-1:0] loop_enter, loop_stuck, found_valid, found_take;
  segment_t found [0:LOOPS-1];
  assign queue_bits = queue_tile;
  assign start = |loop_enter;

  for (genvar loop = 0; loop < LOOPS; loop++) begin : gen_loop
    (* dont_touch = "true" *) logic [LOAD_COPIES-1:0] idle;
    logic [TILE_W-1:0] loop_bits;
    tile_t loop_tile;
    admission_t admission, admission_reg;
    choice_t choice;
    segment_t found_next;
    logic busy, scheduled, credit, my_turn, enter, emit, found_ready;
    logic [COUNT_W-1:0] cursor;
    logic [$clog2(FOUND_DEPTH+1)-1:0] held, held_next;

    for (genvar copy = 0; copy < LOAD_COPIES; copy++) begin : gen_load
      localparam int unsigned LOW = copy * LOAD_BITS;
      localparam int unsigned SIZE = (TILE_W - LOW) < LOAD_BITS ? TILE_W - LOW : LOAD_BITS;
      always_ff @(posedge clk) begin
        if (idle[copy]) loop_bits[LOW +: SIZE] <= queue_bits[LOW +: SIZE];
      end
    end
    assign loop_tile = loop_bits;

    prism_numbergroup_segment_admission #(.LANES(LANES), .LIMIT_W(LIMIT_W)) u_admission (
        .s_cursor(cursor), .s_total(loop_tile.count), .s_forward_wide(loop_tile.forward),
        .s_words(loop_tile.words), .s_origin(loop_tile.origin), .s_padding(loop_tile.padding),
        .s_end_padding(loop_tile.end_padding), .s_limit(loop_tile.limit),
        .s_run_head(loop_tile.run_head), .s_first_wide(loop_tile.first_wide),
        .s_last_words(loop_tile.last_words), .s_last_origin(loop_tile.last_origin),
        .s_last_padding(loop_tile.last_padding),
        .m_admitted(admission.admitted), .m_beyond_far(admission.beyond_far),
        .m_last_admitted(admission.last_admitted),
        .m_cursor_admitted(admission.cursor_admitted),
        .m_wide_at_cursor(admission.wide_at_cursor),
        .m_no_far(admission.no_far), .m_one_left(admission.one_left),
        .m_far_wide(admission.far_wide), .m_cursor_plus_one(admission.cursor_plus_one)
    );
    always_ff @(posedge clk) begin
      if (busy && !scheduled) admission_reg <= admission;
    end
    prism_numbergroup_segment_choice #(.LANES(LANES)) u_choice (
        .s_admitted(admission_reg.admitted), .s_beyond_far(admission_reg.beyond_far),
        .s_last_admitted(admission_reg.last_admitted),
        .s_cursor_admitted(admission_reg.cursor_admitted),
        .s_wide_at_cursor(admission_reg.wide_at_cursor),
        .s_no_far(admission_reg.no_far), .s_one_left(admission_reg.one_left),
        .s_far_wide(admission_reg.far_wide),
        .s_cursor_plus_one(admission_reg.cursor_plus_one),
        .s_forward_wide(loop_tile.forward),
        .m_end(choice.segment_end), .m_last(choice.last), .m_valid(choice.valid)
    );

    // A tile enters the loop whose turn it is, when that loop is free; its
    // first segment was chosen by the pipeline. A segment that admits no
    // lane cannot be sent: the tile stays where it is and the fault is
    // reported.
    assign my_turn = queue_valid && turn_in == TURN_W'(loop) && !busy;
    assign enter = my_turn && credit && queue_choice.valid;
    assign emit = busy && scheduled && credit && choice.valid;
    assign loop_enter[loop] = enter;
    assign loop_stuck[loop] = (my_turn && !queue_choice.valid)
        || (busy && scheduled && !choice.valid);
    always_comb begin
      found_next.cursor = busy ? cursor : '0;
      found_next.segment_end = busy ? choice.segment_end : queue_choice.segment_end;
      found_next.last = busy ? choice.last : queue_choice.last;
    end
    prism_elastic_fifo #(
        .WIDTH($bits(segment_t)), .DEPTH(FOUND_DEPTH), .READY_ON_POP(1'b0),
        .REGISTER_READY(1'b1)
    ) u_found (
        .clk(clk), .rst_n(rst_n && !s_clear),
        .s_data(found_next), .s_valid(enter || emit), .s_ready(found_ready),
        .m_data(found[loop]), .m_valid(found_valid[loop]), .m_ready(found_take[loop]),
        .occupancy()
    );
    // A segment holds a place among the found segments of its loop from the
    // cycle it is found until it is collected.
    always_comb begin
      held_next = held;
      case ({enter || emit, found_take[loop]})
        2'b10: held_next = held + 1'b1;
        2'b01: held_next = held - 1'b1;
        default: ;
      endcase
    end
    always_ff @(posedge clk) begin
      if (!rst_n || s_clear) begin
        busy <= 1'b0;
        idle <= '1;
        scheduled <= 1'b0;
        cursor <= '0;
        held <= '0;
        credit <= 1'b1;
      end else begin
        if (enter && !queue_choice.last) begin
          busy <= 1'b1;
          idle <= '0;
          scheduled <= 1'b0;
          cursor <= queue_choice.segment_end;
        end
        if (busy && !scheduled) scheduled <= 1'b1;
        if (emit) begin
          scheduled <= 1'b0;
          if (choice.last) begin
            busy <= 1'b0;
            idle <= '1;
          end else begin
            cursor <= choice.segment_end;
          end
        end
        held <= held_next;
        credit <= int'(held_next) < FOUND_DEPTH;
      end
    end
    // synthesis translate_off
    always_ff @(posedge clk) begin
      if (rst_n && !s_clear) assert (!((enter || emit) && !found_ready));
    end
    // synthesis translate_on
  end

  // ----------------------------------------------------------- collection
  // One segment per cycle is taken from the loops in the order of the
  // tiles. Then its formats: lanes outside the segment cleared and the
  // segment moved to lane zero in two steps.
  segment_t taken;
  logic take, taken_valid, masked_valid, masked_last, masked_group;
  logic moved_valid, moved_last, moved_group;
  logic [31:0] masked_first, moved_first;
  logic [COUNT_W-1:0] masked_cursor, masked_count, moved_cursor, moved_count;
  logic [LANES*8-1:0] masked_formats, moved_formats, aligned_formats;

  assign take = found_valid[turn_out] && output_credit;
  for (genvar loop = 0; loop < LOOPS; loop++) begin : gen_take
    assign found_take[loop] = take && turn_out == TURN_W'(loop);
  end
  assign context_done = taken_valid && taken.last;

  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      turn_in <= '0;
      turn_out <= '0;
      taken_valid <= 1'b0;
      masked_valid <= 1'b0;
      moved_valid <= 1'b0;
      m_fault <= 1'b0;
    end else begin
      taken_valid <= take;
      masked_valid <= taken_valid;
      moved_valid <= masked_valid;
      if (start) turn_in <= int'(turn_in) == LOOPS - 1 ? '0 : turn_in + TURN_W'(1);
      if (take && found[turn_out].last)
        turn_out <= int'(turn_out) == LOOPS - 1 ? '0 : turn_out + TURN_W'(1);
      if (accept && !legal) m_fault <= 1'b1;
      if (|loop_stuck) m_fault <= 1'b1;
    end
  end
  always_ff @(posedge clk) begin
    taken <= found[turn_out];

    masked_first <= queue_context.first + 32'(taken.cursor);
    masked_cursor <= taken.cursor;
    masked_count <= taken.segment_end - taken.cursor;
    masked_last <= taken.last;
    masked_group <= queue_context.group;
    for (int lane = 0; lane < LANES; lane++)
      masked_formats[lane*8 +: 8]
          <= COUNT_W'(lane) >= taken.cursor && COUNT_W'(lane) < taken.segment_end
              ? queue_context.formats[lane*8 +: 8] : 8'd0;

    moved_first <= masked_first;
    moved_cursor <= masked_cursor;
    moved_count <= masked_count;
    moved_last <= masked_last;
    moved_group <= masked_group;
    moved_formats <= masked_formats >> (int'(masked_cursor[2:0]) * 8);
  end
  if (COUNT_W > 3) begin : gen_far_move
    assign aligned_formats = moved_formats >> (int'(moved_cursor[COUNT_W-1:3]) * 64);
  end else begin : gen_near_move
    assign aligned_formats = moved_formats;
  end

  // -------------------------------------------------------------- output
  localparam int unsigned OUTPUT_W = 32 + 2*COUNT_W + 2 + LANES*8;
  logic unused_output_ready;
  prism_elastic_fifo #(
      .WIDTH(OUTPUT_W), .DEPTH(OUTPUT_DEPTH), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
  ) u_segments (
      .clk(clk), .rst_n(rst_n && !s_clear),
      .s_data({moved_first, moved_count, moved_cursor, moved_last, moved_group,
          aligned_formats}),
      .s_valid(moved_valid), .s_ready(unused_output_ready),
      .m_data({m_first_element, m_count, m_cursor, m_last, m_group_fp32, m_formats}),
      .m_valid(m_valid), .m_ready(m_ready),
      .occupancy()
  );

  // ------------------------------------------------------------- credits
  // A tile holds a credit from acceptance until its last segment has been
  // collected; a segment from the cycle it is collected until the consumer
  // takes it. The queues are therefore never written when full.
  logic [$clog2(QUEUE_DEPTH+1)-1:0] tiles, tiles_next;
  logic [$clog2(OUTPUT_DEPTH+1)-1:0] segments, segments_next;
  always_comb begin
    tiles_next = tiles;
    case ({accept && legal, context_done})
      2'b10: tiles_next = tiles + 1'b1;
      2'b01: tiles_next = tiles - 1'b1;
      default: ;
    endcase
    segments_next = segments;
    case ({take, m_valid && m_ready})
      2'b10: segments_next = segments + 1'b1;
      2'b01: segments_next = segments - 1'b1;
      default: ;
    endcase
  end
  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      tiles <= '0;
      segments <= '0;
      tile_credit <= 1'b1;
      output_credit <= 1'b1;
    end else begin
      tiles <= tiles_next;
      segments <= segments_next;
      tile_credit <= int'(tiles_next) < QUEUE_DEPTH;
      output_credit <= int'(segments_next) < OUTPUT_DEPTH;
    end
  end

  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (rst_n && !s_clear) begin
      assert (!(valid[QUEUE_STEP] && !(queue_ready && context_ready)));
      assert (!(context_done && !context_valid));
      assert (!(moved_valid && !unused_output_ready));
      // The admission compares "words < limit" for "words <= limit - 1".
      if (valid[TABLE_STEP])
        for (int lane = 0; lane < LANES; lane++)
          assert (table_reg.limit[lane*LIMIT_W +: LIMIT_W] != 0);
    end
  end
  // synthesis translate_on

endmodule
