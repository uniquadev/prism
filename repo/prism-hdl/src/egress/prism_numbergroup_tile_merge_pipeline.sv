//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_tile_merge_pipeline.sv
// Module: prism_numbergroup_tile_merge_pipeline
// Description: Byte-concatenation tree that compacts variable-length lane segments.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Each tree level is one free-running register stage: words advance every
// cycle and never stall, so the stages have no enable. A word leaving the
// tree enters a small FIFO, and the input is accepted only while the tree
// and the FIFO together hold fewer words than the FIFO can store.
//
// The output word is stored and handed over in slices of SLICE_BITS bits,
// data in the low bits, then the length, then the meta bits. Each slice has
// its own queue and its own take input, so the consumer can steer every
// slice from registers next to it. A word may be taken once m_arrived has
// announced it, in the order of arrival; all slices of a word are taken in
// the same cycle.
//
// A level whose nodes are SPLIT_BYTES wide or wider takes two cycles: the
// right child moves by the low bits of the amount, is registered, and moves
// by the high bits. The shift of the widest levels is then half as deep, and
// its wires are cut once.
module prism_numbergroup_tile_merge_pipeline #(
    parameter int unsigned LANES = 128,
    parameter int unsigned SEGMENT_BYTES = 8,
    parameter int unsigned CAP_BYTES = 1458,
    parameter int unsigned META_W = 64,
    // Words the output queue holds. The producer keeps the words inside the
    // tree and the queue together below this number.
    parameter int unsigned FIFO_DEPTH = 32,
    // Nodes of at least this many bytes are merged in two cycles.
    parameter int unsigned SPLIT_BYTES = 512
) (
    input logic clk,
    input logic rst_n,
    input logic [LANES*SEGMENT_BYTES*8-1:0] s_lane_data,
    input logic [LANES*$clog2(SEGMENT_BYTES+1)-1:0] s_lane_length,
    input logic [META_W-1:0] s_meta,
    input logic s_valid,
    output logic s_ready,
    output logic [((LANES*SEGMENT_BYTES < CAP_BYTES)
        ? LANES*SEGMENT_BYTES : CAP_BYTES)*8-1:0] m_data,
    output logic [15:0] m_length,
    output logic [META_W-1:0] m_meta,
    output logic m_valid,
    // One pulse per word: from this cycle on the word can be taken.
    output logic m_arrived,
    input logic [(((LANES*SEGMENT_BYTES < CAP_BYTES) ? LANES*SEGMENT_BYTES : CAP_BYTES)*8
        +16+META_W+255)/256-1:0] m_take
);
    localparam int unsigned LEAF_LENGTH_W = $clog2(SEGMENT_BYTES+1);
    localparam int unsigned LEVELS = $clog2(LANES);
    localparam int unsigned LEAVES = 1 << LEVELS;
    localparam int unsigned DATA_W = LEAVES*SEGMENT_BYTES*8;
    localparam int unsigned LENGTH_W = LEAVES*16;
    localparam int unsigned OUT_BYTES = LANES*SEGMENT_BYTES < CAP_BYTES
        ? LANES*SEGMENT_BYTES : CAP_BYTES;
    localparam int unsigned OUT_W = OUT_BYTES*8+16+META_W;
    // Bits served by one copy of a shift amount or of the output handshake.
    localparam int unsigned SLICE_BITS = 256;
    localparam int unsigned CREDIT_W = $clog2(FIFO_DEPTH+1);

    logic [DATA_W-1:0] input_data;
    logic [LENGTH_W-1:0] input_length;
    logic [DATA_W-1:0] stage_data [1:LEVELS];
    logic [LENGTH_W-1:0] stage_length [1:LEVELS];
    logic [META_W-1:0] stage_meta [1:LEVELS];
    logic [LEVELS:1] stage_valid;
    logic accept, deliver, ready_reg;
    // The valid that the last level takes in the next cycle.
    logic final_valid;
    logic [1:0] arriving;
    logic [CREDIT_W-1:0] inflight, inflight_next;

    initial begin
        if (LANES < 2 || SEGMENT_BYTES < 1 || CAP_BYTES < 1 || META_W < 1
            || LANES*SEGMENT_BYTES > 65535 || SLICE_BITS != 256)
            $fatal(1, "illegal compaction geometry");
    end

    assign s_ready = ready_reg;
    assign accept = s_valid && s_ready;
    assign deliver = m_take[0];
    assign inflight_next = inflight + CREDIT_W'(accept) - CREDIT_W'(deliver);
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            inflight <= '0;
            ready_reg <= 1'b1;
        end else begin
            inflight <= inflight_next;
            ready_reg <= inflight_next < CREDIT_W'(FIFO_DEPTH);
        end
    end

    assign input_data = DATA_W'(s_lane_data);
    for (genvar lane = 0; lane < LEAVES; lane++) begin : input_lane
        if (lane < LANES) begin : active_lane
            assign input_length[lane*16 +: 16] = 16'(s_lane_length[lane*LEAF_LENGTH_W +: LEAF_LENGTH_W]);
        end else begin : padding_lane
            assign input_length[lane*16 +: 16] = '0;
        end
    end

    for (genvar level = 1; level <= LEVELS; level++) begin : merge_level
        localparam int unsigned SPAN = 1 << level;
        localparam int unsigned NODES = LEAVES / SPAN;
        localparam int unsigned SLOT_BYTES = SPAN*SEGMENT_BYTES;
        localparam int unsigned CHILD_BYTES = (SPAN/2)*SEGMENT_BYTES < CAP_BYTES
            ? (SPAN/2)*SEGMENT_BYTES : CAP_BYTES;
        localparam int unsigned PARENT_BYTES = SLOT_BYTES < CAP_BYTES
            ? SLOT_BYTES : CAP_BYTES;
        localparam int unsigned COPIES = (PARENT_BYTES*8+SLICE_BITS-1)/SLICE_BITS;
        localparam int unsigned SHIFT_W = $clog2(CHILD_BYTES+1);
        localparam bit SPLIT = level > 1 && PARENT_BYTES >= SPLIT_BYTES;
        // Amount bits applied before the register of a split level.
        localparam int unsigned FIRST_STEPS = SPLIT ? (SHIFT_W + 1) / 2 : SHIFT_W;
        localparam int unsigned LATE_STEPS = SHIFT_W - FIRST_STEPS;
        logic [DATA_W-1:0] previous_data, next_data;
        logic [LENGTH_W-1:0] previous_length, next_length, level_length;
        logic [META_W-1:0] previous_meta, level_meta;
        logic previous_valid, level_valid;
        if (level == 1) begin : from_input
            assign previous_data = input_data;
            assign previous_length = input_length;
            assign previous_meta = s_meta;
            assign previous_valid = accept;
        end else begin : from_stage
            assign previous_data = stage_data[level-1];
            assign previous_length = stage_length[level-1];
            assign previous_meta = stage_meta[level-1];
            assign previous_valid = stage_valid[level-1];
        end
        for (genvar node = 0; node < NODES; node++) begin : at_node
            logic [CHILD_BYTES*8-1:0] left_data, right_data;
            logic [15:0] left_length, right_length;
            logic [PARENT_BYTES*8-1:0] left_word, right_word, merged;
            assign left_data = previous_data[node*SLOT_BYTES*8 +: CHILD_BYTES*8];
            assign right_data = previous_data[(node*SLOT_BYTES+SLOT_BYTES/2)*8
                +: CHILD_BYTES*8];
            assign left_length = previous_length[(2*node)*16 +: 16];
            assign right_length = previous_length[(2*node+1)*16 +: 16];
            assign left_word = (PARENT_BYTES*8)'(left_data);
            assign right_word = (PARENT_BYTES*8)'(right_data);
            // The right child moves up by the length of the left one through
            // one fixed-distance step per amount bit. Every step is computed
            // once for the whole word; a slice of its output is steered by
            // its own copy of the amount bit, so the copies add no logic.
            logic [PARENT_BYTES*8-1:0] shift_step [0:SHIFT_W];
            logic [PARENT_BYTES*8-1:0] left_final;
            // The half-moved right child, the left child and the copies of
            // the amount bits still to apply, one cycle later (split levels).
            localparam int unsigned LATE_W = LATE_STEPS > 0 ? LATE_STEPS : 1;
            logic [PARENT_BYTES*8-1:0] right_half, left_half;
            (* dont_touch = "true" *) logic [COPIES*LATE_W-1:0] late_amount;
            assign shift_step[0] = right_word;
            if (SPLIT) begin : held
                always_ff @(posedge clk) begin
                    right_half <= shift_step[FIRST_STEPS];
                    left_half <= left_word;
                    for (int copy = 0; copy < COPIES; copy++)
                        late_amount[copy*LATE_STEPS +: LATE_STEPS]
                            <= merge_level[level-1].amounts.left_amount[node]
                                [copy*SHIFT_W + FIRST_STEPS +: LATE_STEPS];
                end
                assign left_final = left_half;
            end else begin : direct
                assign left_final = left_word;
            end
            for (genvar step = 0; step < SHIFT_W; step++) begin : shift_stage
                logic [PARENT_BYTES*8-1:0] source, moved;
                if (SPLIT && step == FIRST_STEPS) begin : from_register
                    assign source = right_half;
                end else begin : from_step
                    assign source = shift_step[step];
                end
                assign moved = source << (8 << step);
                for (genvar copy = 0; copy < COPIES; copy++) begin : shift_slice
                    localparam int unsigned LOW = copy*SLICE_BITS;
                    localparam int unsigned SIZE = PARENT_BYTES*8-LOW < SLICE_BITS
                        ? PARENT_BYTES*8-LOW : SLICE_BITS;
                    logic take;
                    if (level == 1) begin : amount_from_input
                        assign take = left_length[step];
                    end else if (SPLIT && step >= FIRST_STEPS) begin : amount_from_late_register
                        assign take = late_amount[copy*LATE_STEPS + step - FIRST_STEPS];
                    end else begin : amount_from_register
                        assign take = merge_level[level-1].amounts.left_amount[node]
                            [copy*SHIFT_W + step];
                    end
                    assign shift_step[step+1][LOW +: SIZE] = take
                        ? moved[LOW +: SIZE] : source[LOW +: SIZE];
                end
            end
            assign merged = shift_step[SHIFT_W] | left_final;
            assign next_data[node*SLOT_BYTES*8 +: SLOT_BYTES*8] = (SLOT_BYTES*8)'(merged);
            // A node sums exactly 2**level leaf lengths. Make that bound
            // explicit across the register; unreachable high carry bits must
            // not survive as state and control downstream barrel shifters.
            assign next_length[node*16 +: 16]
                = 16'((LEAF_LENGTH_W+level)'(left_length+right_length));
        end
        assign next_length[LENGTH_W-1:NODES*16] = '0;
        // What travels beside the data of a split level waits one cycle too.
        if (SPLIT) begin : beside
            logic [LENGTH_W-1:0] length_half;
            logic [META_W-1:0] meta_half;
            logic valid_half;
            always_ff @(posedge clk) begin
                length_half <= next_length;
                meta_half <= previous_meta;
            end
            always_ff @(posedge clk) begin
                if (!rst_n) valid_half <= 1'b0;
                else valid_half <= previous_valid;
            end
            assign level_length = length_half;
            assign level_meta = meta_half;
            assign level_valid = valid_half;
        end else begin : beside
            assign level_length = next_length;
            assign level_meta = previous_meta;
            assign level_valid = previous_valid;
        end
        // The next level shifts by the length of each left child. One copy
        // of that length is registered here for every slice it will steer.
        if (level < LEVELS) begin : amounts
            localparam int unsigned NEXT_BYTES = 2*SLOT_BYTES < CAP_BYTES
                ? 2*SLOT_BYTES : CAP_BYTES;
            localparam int unsigned NEXT_COPIES = (NEXT_BYTES*8+SLICE_BITS-1)/SLICE_BITS;
            localparam int unsigned NEXT_SHIFT_W = $clog2(PARENT_BYTES+1);
            (* dont_touch = "true" *)
            logic [NEXT_COPIES*NEXT_SHIFT_W-1:0] left_amount [0:NODES/2-1];
            for (genvar pair = 0; pair < NODES/2; pair++) begin : at_pair
                always_ff @(posedge clk) begin
                    left_amount[pair]
                        <= {NEXT_COPIES{NEXT_SHIFT_W'(level_length[(2*pair)*16 +: 16])}};
                end
            end
        end
        always_ff @(posedge clk) begin
            stage_data[level] <= next_data;
            stage_length[level] <= level_length;
            stage_meta[level] <= level_meta;
        end
        always_ff @(posedge clk) begin
            if (!rst_n) stage_valid[level] <= 1'b0;
            else stage_valid[level] <= level_valid;
        end
        if (level == LEVELS) begin : last_level
            assign final_valid = level_valid;
        end
    end
    // The output word is stored and handed over in slices, each with its own
    // pointers, valid flag and copy of the valid of the last level, so no
    // control net spans the word. A word that
    // leaves the tree is in the output register of every slice two cycles
    // later, or as soon as the words before it have been taken.
    localparam int unsigned OUT_SLICES = (OUT_W+SLICE_BITS-1)/SLICE_BITS;
    logic [OUT_W-1:0] tree_word, out_word;
    logic [OUT_SLICES-1:0] stored_valid, stage_ready, slice_valid;
    assign tree_word = {stage_meta[LEVELS], stage_length[LEVELS][0 +: 16],
        stage_data[LEVELS][0 +: OUT_BYTES*8]};
    for (genvar slice = 0; slice < OUT_SLICES; slice++) begin : output_slice
        localparam int unsigned LOW = slice*SLICE_BITS;
        localparam int unsigned SIZE = OUT_W-LOW < SLICE_BITS ? OUT_W-LOW : SLICE_BITS;
        logic [SIZE-1:0] stored_word;
        logic unused_ready;
        (* dont_touch = "true" *) logic push;
        // Each slice has its own registered reset, one cycle behind that of
        // the tree. A word needs more cycles than that through the tree, and
        // whoever takes the words is reset with the tree.
        (* dont_touch = "true" *) logic slice_rst_n;
        always_ff @(posedge clk) slice_rst_n <= rst_n;
        always_ff @(posedge clk) begin
            if (!slice_rst_n) push <= 1'b0;
            else push <= final_valid;
        end
        logic [CREDIT_W-1:0] unused_occupancy;
        (* dont_touch = "true" *) prism_elastic_fifo #(
            .WIDTH(SIZE), .DEPTH(FIFO_DEPTH), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
        ) u_store (
            .clk(clk), .rst_n(slice_rst_n),
            .s_data(tree_word[LOW +: SIZE]), .s_valid(push), .s_ready(unused_ready),
            .m_data(stored_word), .m_valid(stored_valid[slice]), .m_ready(stage_ready[slice]),
            .occupancy(unused_occupancy)
        );
        (* dont_touch = "true" *) prism_elastic_register #(.WIDTH(SIZE)) u_output (
            .clk(clk), .rst_n(slice_rst_n),
            .s_data(stored_word), .s_valid(stored_valid[slice]), .s_ready(stage_ready[slice]),
            .m_data(out_word[LOW +: SIZE]), .m_valid(slice_valid[slice]), .m_ready(m_take[slice])
        );
        // synthesis translate_off
        always_ff @(posedge clk) begin
            if (rst_n && slice_rst_n) assert (!(m_take[slice] && !slice_valid[slice]));
        end
        // synthesis translate_on
    end
    assign {m_meta, m_length, m_data} = out_word;
    assign m_valid = slice_valid[0];
    always_ff @(posedge clk) begin
        if (!rst_n) arriving <= '0;
        else arriving <= {arriving[0], stage_valid[LEVELS]};
    end
    assign m_arrived = arriving[1];
endmodule
