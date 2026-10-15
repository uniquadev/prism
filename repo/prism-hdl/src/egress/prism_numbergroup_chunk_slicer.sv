//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_chunk_slicer.sv
// Module: prism_numbergroup_chunk_slicer
// Description: Cuts an encoded tile into fixed-size chunks for the frame store.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// A tile of s_bytes bytes that belongs at s_offset of a frame body leaves as
// chunks of at most CHUNK_BYTES bytes at increasing offsets, one per cycle
// while credit is given. The next tile is taken in the cycle in which the
// last chunk leaves, so tiles of one chunk pass at one per cycle.
//
// A tile comes in two parts. The second part, s_tail, starts s_tail_skip
// whole chunks into the tile; inside its first chunk it is already at its
// place, with zero bytes where the first part ends. The two parts are then
// joined chunk by chunk without moving either. Bytes of the first part
// beyond its end and of the tile beyond s_bytes must be zero.
//
// Nothing here is steered by a signal shared across the tile. Every slice
// of CONTROL_BITS bits has its own copy of the handshake: whether a tile is
// waiting, how many chunks it has, and whether a chunk may leave. The copies
// receive equal inputs in every cycle and therefore take the tile in the
// same cycle, each from registers of its own. A tile may be offered only
// when both of its parts are present; the take of a slice pops what feeds
// that slice.
//
// The store keeps frames in words of WORD_BYTES bytes and the body starts
// PHASE_BYTES into the first word. Each chunk is delivered already moved to
// its position inside a word, so the store only merges it with the bytes of
// the word it has so far. The output does not stall: a chunk leaves only
// with credit, which the consumer withdraws in time.
module prism_numbergroup_chunk_slicer #(
    parameter int unsigned TILE_BYTES = 1458,
    parameter int unsigned TAIL_BYTES = 128,
    parameter int unsigned CHUNK_BYTES = 128,
    parameter int unsigned WORD_BYTES = 64,
    parameter int unsigned PHASE_BYTES = 56,
    // Data bits served by one copy of the handshake.
    parameter int unsigned CONTROL_BITS = 256,
    localparam int unsigned LENGTH_W = $clog2(CHUNK_BYTES + 1),
    localparam int unsigned WINDOW_W = (CHUNK_BYTES + WORD_BYTES) * 8,
    localparam int unsigned WIDTH = TILE_BYTES * 8,
    localparam int unsigned TAIL_W = TAIL_BYTES * 8,
    localparam int unsigned COPIES = (WIDTH + CONTROL_BITS - 1) / CONTROL_BITS,
    localparam int unsigned TAIL_COPIES = (TAIL_W + CONTROL_BITS - 1) / CONTROL_BITS,
    localparam int unsigned WINDOW_COPIES = (WINDOW_W + CONTROL_BITS - 1) / CONTROL_BITS,
    localparam int unsigned CHUNKS_W
        = $clog2((TILE_BYTES + TAIL_BYTES + CHUNK_BYTES - 1) / CHUNK_BYTES + 1),
    localparam int unsigned SKIP_W = $clog2(TILE_BYTES / CHUNK_BYTES + 1),
    localparam int unsigned PHASE_W = $clog2(WORD_BYTES)
) (
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic [WIDTH-1:0]                  s_data,
    input  logic [TAIL_W-1:0]                 s_tail,
    // One copy per slice of the first part: a tile is waiting, a chunk may
    // leave, the chunks of the tile and its position inside a word.
    input  logic [COPIES-1:0]                 s_valid,
    input  logic [COPIES-1:0]                 s_credit,
    // What s_valid and s_credit will be in the next cycle. A copy decides one
    // cycle ahead whether it takes a tile, so the take is a register: it also
    // pops the source of the tile, which may lie far from the slicer.
    input  logic [COPIES-1:0]                 s_valid_next,
    input  logic [COPIES-1:0]                 s_credit_next,
    input  logic [COPIES*CHUNKS_W-1:0]        s_chunks,
    input  logic [COPIES*PHASE_W-1:0]         s_phase,
    output logic [COPIES-1:0]                 s_take,
    // The same per slice of the second part, with the chunks before it.
    input  logic [TAIL_COPIES-1:0]            s_tail_valid,
    input  logic [TAIL_COPIES-1:0]            s_tail_credit,
    input  logic [TAIL_COPIES-1:0]            s_tail_valid_next,
    input  logic [TAIL_COPIES-1:0]            s_tail_credit_next,
    input  logic [TAIL_COPIES*CHUNKS_W-1:0]   s_tail_chunks,
    input  logic [TAIL_COPIES*SKIP_W-1:0]     s_tail_skip,
    output logic [TAIL_COPIES-1:0]            s_tail_take,
    // One more copy with what describes the chunks.
    input  logic                              s_plan_valid,
    input  logic                              s_plan_credit,
    input  logic                              s_plan_valid_next,
    input  logic                              s_plan_credit_next,
    input  logic [CHUNKS_W-1:0]               s_plan_chunks,
    input  logic [15:0]                       s_bytes,
    input  logic [15:0]                       s_offset,
    input  logic                              s_bank,
    output logic                              s_plan_take,
    output logic [WINDOW_W-1:0]               m_window,
    output logic [LENGTH_W-1:0]               m_bytes,
    // Store words that the chunk completes.
    output logic [1:0]                        m_flush,
    output logic [15:0]                       m_offset,
    output logic                              m_bank,
    output logic                              m_valid,
    // Copies of m_valid, one per CONTROL_BITS of the window.
    output logic [WINDOW_COPIES-1:0]          m_window_valid
);

  localparam int unsigned CHUNK_BITS = CHUNK_BYTES * 8;

  initial begin
    if (TILE_BYTES < CHUNK_BYTES || TAIL_BYTES < CHUNK_BYTES || CHUNK_BYTES == 0
        || CONTROL_BITS == 0 || CHUNK_BITS % CONTROL_BITS != 0
        || WORD_BYTES < 2 || (WORD_BYTES & (WORD_BYTES - 1)) != 0
        || CHUNK_BYTES % WORD_BYTES != 0 || PHASE_BYTES >= WORD_BYTES)
      $fatal(1, "prism_numbergroup_chunk_slicer needs whole words per chunk");
  end

  logic [WIDTH-1:0] data, moved;
  logic [TAIL_W-1:0] tail, tail_moved;
  logic [CHUNK_BITS-1:0] chunk;
  // The decisions of every copy stay nets and registers of that copy.
  (* dont_touch = "true" *) logic [COPIES-1:0] take, advance;
  (* dont_touch = "true" *) logic [TAIL_COPIES-1:0] tail_take, tail_advance, tail_started;
  (* dont_touch = "true" *) logic [CHUNKS_W-1:0] left [0:COPIES-1];
  (* dont_touch = "true" *) logic [CHUNKS_W-1:0] tail_left [0:TAIL_COPIES-1];
  (* dont_touch = "true" *) logic [SKIP_W-1:0] tail_wait [0:TAIL_COPIES-1];
  (* dont_touch = "true" *) logic [CHUNKS_W-1:0] plan_left;

  assign moved = data >> CHUNK_BITS;
  assign tail_moved = tail >> CHUNK_BITS;
  assign s_take = take;
  assign s_tail_take = tail_take;

  // A copy counts the chunks of its tile that have not left. It takes the
  // next tile when it holds none, or in the cycle its last chunk leaves. The
  // take of a cycle is decided in the cycle before, from the count, the
  // waiting tile and the credit of that next cycle.
  for (genvar copy = 0; copy < COPIES; copy++) begin : control_copy
    localparam int unsigned LOW = copy * CONTROL_BITS;
    localparam int unsigned SIZE = (WIDTH - LOW) < CONTROL_BITS ? WIDTH - LOW : CONTROL_BITS;
    logic [CHUNKS_W-1:0] left_next;
    assign advance[copy] = s_credit[copy] && left[copy] != 0;
    always_comb begin
      left_next = left[copy];
      if (take[copy]) left_next = s_chunks[copy*CHUNKS_W +: CHUNKS_W];
      else if (advance[copy]) left_next = left[copy] - CHUNKS_W'(1);
    end
    always_ff @(posedge clk) begin
      if (!rst_n) begin
        left[copy] <= '0;
        take[copy] <= 1'b0;
      end else begin
        left[copy] <= left_next;
        take[copy] <= s_valid_next[copy]
            && (left_next == 0 || (s_credit_next[copy] && left_next == CHUNKS_W'(1)));
      end
    end
    // synthesis translate_off
    always_ff @(posedge clk) begin
      if (rst_n) assert (take[copy] == (s_valid[copy]
          && (left[copy] == 0 || (advance[copy] && left[copy] == CHUNKS_W'(1)))));
    end
    // synthesis translate_on
    always_ff @(posedge clk) begin
      if (take[copy]) data[LOW +: SIZE] <= s_data[LOW +: SIZE];
      else if (advance[copy]) data[LOW +: SIZE] <= moved[LOW +: SIZE];
    end
  end

  // The second part waits until the chunks before it have left, then moves
  // down chunk by chunk like the first.
  for (genvar copy = 0; copy < TAIL_COPIES; copy++) begin : tail_copy
    localparam int unsigned LOW = copy * CONTROL_BITS;
    localparam int unsigned SIZE = (TAIL_W - LOW) < CONTROL_BITS ? TAIL_W - LOW : CONTROL_BITS;
    logic [CHUNKS_W-1:0] tail_left_next;
    assign tail_advance[copy] = s_tail_credit[copy] && tail_left[copy] != 0;
    always_comb begin
      tail_left_next = tail_left[copy];
      if (tail_take[copy]) tail_left_next = s_tail_chunks[copy*CHUNKS_W +: CHUNKS_W];
      else if (tail_advance[copy]) tail_left_next = tail_left[copy] - CHUNKS_W'(1);
    end
    always_ff @(posedge clk) begin
      if (!rst_n) begin
        tail_left[copy] <= '0;
        tail_take[copy] <= 1'b0;
      end else begin
        tail_left[copy] <= tail_left_next;
        tail_take[copy] <= s_tail_valid_next[copy] && (tail_left_next == 0
            || (s_tail_credit_next[copy] && tail_left_next == CHUNKS_W'(1)));
      end
    end
    // synthesis translate_off
    always_ff @(posedge clk) begin
      if (rst_n) assert (tail_take[copy] == (s_tail_valid[copy] && (tail_left[copy] == 0
          || (tail_advance[copy] && tail_left[copy] == CHUNKS_W'(1)))));
    end
    // synthesis translate_on
    always_ff @(posedge clk) begin
      if (tail_take[copy]) begin
        tail_wait[copy] <= s_tail_skip[copy*SKIP_W +: SKIP_W];
        tail_started[copy] <= s_tail_skip[copy*SKIP_W +: SKIP_W] == 0;
      end else if (tail_advance[copy] && tail_wait[copy] != 0) begin
        tail_wait[copy] <= tail_wait[copy] - SKIP_W'(1);
        tail_started[copy] <= tail_wait[copy] == SKIP_W'(1);
      end
    end
    always_ff @(posedge clk) begin
      if (tail_take[copy]) tail[LOW +: SIZE] <= s_tail[LOW +: SIZE];
      else if (tail_advance[copy] && tail_started[copy])
        tail[LOW +: SIZE] <= tail_moved[LOW +: SIZE];
    end
    if (LOW < CHUNK_BITS) begin : in_chunk
      assign chunk[LOW +: CONTROL_BITS] = data[LOW +: CONTROL_BITS]
          | (tail_started[copy] ? tail[LOW +: CONTROL_BITS] : '0);
    end
  end

  // The copy that describes the chunks: their lengths and offsets.
  (* dont_touch = "true" *) logic plan_advance, plan_take;
  logic [CHUNKS_W-1:0] plan_left_next;
  logic [LENGTH_W-1:0] last_bytes;
  logic [1:0] last_flush;
  logic [LENGTH_W:0] last_reach;
  logic [PHASE_W-1:0] plan_phase;
  // The position inside a word wraps at the word; the sum is kept that wide.
  assign plan_phase = PHASE_W'(s_offset) + PHASE_W'(PHASE_BYTES);
  assign last_reach = (LENGTH_W+1)'(plan_phase)
      + (LENGTH_W+1)'((s_bytes - 16'd1) % 16'(CHUNK_BYTES)) + (LENGTH_W+1)'(1);
  assign plan_advance = s_plan_credit && plan_left != 0;
  assign s_plan_take = plan_take;
  always_comb begin
    plan_left_next = plan_left;
    if (plan_take) plan_left_next = s_plan_chunks;
    else if (plan_advance) plan_left_next = plan_left - CHUNKS_W'(1);
  end
  assign m_valid = plan_advance;
  assign m_bytes = plan_left == CHUNKS_W'(1) ? last_bytes : LENGTH_W'(CHUNK_BYTES);
  // A full chunk completes two words; the last chunk of a tile as many as its
  // bytes and the bytes in front of it in the word reach.
  assign m_flush = plan_left != CHUNKS_W'(1) ? 2'(CHUNK_BYTES / WORD_BYTES) : last_flush;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      plan_left <= '0;
      plan_take <= 1'b0;
    end else begin
      plan_left <= plan_left_next;
      plan_take <= s_plan_valid_next
          && (plan_left_next == 0 || (s_plan_credit_next && plan_left_next == CHUNKS_W'(1)));
    end
  end
  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (rst_n) assert (plan_take == (s_plan_valid
        && (plan_left == 0 || (plan_advance && plan_left == CHUNKS_W'(1)))));
  end
  // synthesis translate_on
  always_ff @(posedge clk) begin
    if (s_plan_take) begin
      m_offset <= s_offset;
      m_bank <= s_bank;
      last_bytes <= LENGTH_W'((s_bytes - 16'd1) % 16'(CHUNK_BYTES)) + LENGTH_W'(1);
      last_flush <= 2'(int'(last_reach) / WORD_BYTES);
    end else if (plan_advance) begin
      m_offset <= m_offset + 16'(CHUNK_BYTES);
    end
  end

  // Chunks advance by whole words, so every chunk of a tile sits at the same
  // position inside a word. The move is one fixed-distance step per bit of
  // that position, computed once for the window; each slice picks the result
  // with its own copy of the bit, loaded by the control copy next to it.
  (* dont_touch = "true" *) logic [PHASE_W-1:0] phase [0:WINDOW_COPIES-1];
  for (genvar copy = 0; copy < WINDOW_COPIES; copy++) begin : phase_copy
    localparam int unsigned CONTROL = copy < COPIES ? copy : COPIES - 1;
    always_ff @(posedge clk) begin
      if (take[CONTROL])
        phase[copy] <= s_phase[CONTROL*PHASE_W +: PHASE_W];
    end
    assign m_window_valid[copy] = advance[CONTROL];
  end
  logic [WINDOW_W-1:0] window_step [0:PHASE_W];
  assign window_step[0] = WINDOW_W'(chunk);
  for (genvar step = 0; step < PHASE_W; step++) begin : gen_window_step
    logic [WINDOW_W-1:0] moved_up;
    assign moved_up = window_step[step] << (8 << step);
    for (genvar copy = 0; copy < WINDOW_COPIES; copy++) begin : gen_slice
      localparam int unsigned LOW = copy * CONTROL_BITS;
      localparam int unsigned SIZE = (WINDOW_W - LOW) < CONTROL_BITS ? WINDOW_W - LOW : CONTROL_BITS;
      assign window_step[step+1][LOW +: SIZE] = phase[copy][step]
          ? moved_up[LOW +: SIZE] : window_step[step][LOW +: SIZE];
    end
  end
  assign m_window = window_step[PHASE_W];

  // synthesis translate_off
  // The copies hold the same state and decide alike.
  always_ff @(posedge clk) begin
    if (rst_n) begin
      for (int copy = 0; copy < COPIES; copy++) begin
        assert (left[copy] == plan_left);
        assert (take[copy] == s_plan_take && advance[copy] == plan_advance);
      end
      for (int copy = 0; copy < TAIL_COPIES; copy++) begin
        assert (tail_left[copy] == plan_left);
        assert (tail_take[copy] == s_plan_take && tail_advance[copy] == plan_advance);
      end
    end
  end
  // synthesis translate_on

endmodule
