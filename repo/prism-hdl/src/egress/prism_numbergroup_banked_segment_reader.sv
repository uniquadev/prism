//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_banked_segment_reader.sv
// Module: prism_numbergroup_banked_segment_reader
// Description: Stores result tiles in per-lane memories and reads MTU-bounded segments.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// The values of a tile are written once, each lane into its own memory, and
// stay there while the scheduler works on the formats alone. A segment is
// then read in registered steps: its descriptor, the bank words selected by
// column, the same words once more, and the words rotated to the segment
// start. The repeated step lets the words travel from the memories of the
// lanes to the place where the lanes are rotated against each other.
module prism_numbergroup_banked_segment_reader #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned LANES = 16,
    // Tiles held between acceptance and the read of their last segment. The
    // number covers the steps in between, so a tile can be accepted every cycle.
    parameter int unsigned SLOTS = 32,
    // With reserved input a slot is taken with s_reserve before the tile
    // exists, for instance when its values are requested; the tile itself is
    // then never refused. Otherwise a tile takes its slot when it is accepted.
    parameter bit RESERVED_INPUT = 1'b0
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic                            s_clear,
    input  logic                            s_reserve,
    output logic                            s_reserve_ready,
    input  logic [15:0]                     s_mtu,
    input  logic [15:0]                     s_kulisch_bits,
    input  logic [31:0]                     s_first_element,
    input  logic [LANES-1:0]                s_keep,
    input  logic [LANES*8-1:0]             s_formats,
    // Each value in its chosen native format and as FP32; the FP32 form is
    // sent when the scheduler groups the whole tile as FP32.
    input  logic [LANES*32-1:0]            s_native_bits,
    input  logic [LANES*32-1:0]            s_fp32_bits,
    input  logic                            s_fp32_eligible,
    input  logic [LANES*8-1:0]             s_tags,
    input  logic [LANES*KULISCH_W-1:0]     s_integers,
    input  logic                            s_error,
    input  logic                            s_valid,
    // Copies of s_valid, one per lane, for reserved input: each lane writes
    // its memory from its own copy.
    input  logic [LANES-1:0]                s_lane_valid,
    output logic                            s_ready,
    output logic [31:0]                     m_first_element,
    output logic [$clog2(LANES+1)-1:0]     m_count,
    output logic [LANES*8-1:0]             m_formats,
    output logic [LANES*32-1:0]            m_native_bits,
    output logic [LANES*8-1:0]             m_tags,
    output logic [LANES*KULISCH_W-1:0]     m_integers,
    output logic                            m_valid,
    input  logic                            m_ready,
    output logic                            m_fault
);

  localparam int unsigned BANK_LANES = 16;
  localparam int unsigned COLUMNS = LANES / BANK_LANES;
  localparam int unsigned SLOT_W = $clog2(SLOTS);
  localparam int unsigned COLUMN_W = COLUMNS > 1 ? $clog2(COLUMNS) : 1;
  localparam int unsigned COUNT_W = $clog2(LANES + 1);
  localparam int unsigned WIDE_W = KULISCH_W + 8;
  localparam int unsigned OUTPUT_W = 32 + COUNT_W + LANES*40 + BANK_LANES*WIDE_W;

  typedef struct packed {
    logic [SLOT_W-1:0] slot;
    logic [COUNT_W-1:0] cursor;
    logic [COUNT_W-1:0] count;
    logic [31:0] first;
    logic last;
    logic [LANES*8-1:0] formats;
  } descriptor_t;
  localparam int unsigned BANK_STAGE_W = 32 + COUNT_W + LANES*40 + BANK_LANES*WIDE_W;
  localparam int unsigned NATIVE_SLICE_LANES = 8;
  localparam int unsigned NATIVE_SLICES = LANES / NATIVE_SLICE_LANES;
  descriptor_t read_descriptor;
  logic [SLOT_W-1:0] write_slot, issue_slot;
  logic [$clog2(SLOTS+1)-1:0] occupied, occupied_next;
  logic schedule_ready, storage_ready;
  logic segment_valid, segment_last, segment_group;
  logic read_valid, read_ready, read_load;
  logic bank_load, bank_valid;
  logic accept_tile, reserve_tile, release_tile;
  logic [31:0] segment_first;
  logic [COUNT_W-1:0] segment_count;
  logic [COUNT_W-1:0] segment_cursor;
  logic [LANES*8-1:0] segment_formats;
  logic [LANES*32-1:0] native_row, selected_native;
  logic [BANK_LANES*WIDE_W-1:0] bank_values, selected_wide;
  // The registers between the memories and the alignment are there to cover
  // distance: each has to stay a register of its own, not part of a shift
  // register primitive.
  (* shreg_extract = "no" *) logic [LANES*32-1:0] banked_native, moved_native, held_native;
  (* shreg_extract = "no" *) logic [BANK_LANES*WIDE_W-1:0] banked_values, moved_values, held_values;
  (* shreg_extract = "no" *) logic [31:0] banked_first, moved_first, held_first;
  (* shreg_extract = "no" *) logic [COUNT_W-1:0] banked_count, banked_cursor, moved_count, moved_cursor,
      held_count;
  (* shreg_extract = "no" *) logic [LANES*8-1:0] banked_formats, moved_formats, held_formats;
  logic [OUTPUT_W-1:0] output_word;
  logic [BANK_LANES*WIDE_W-1:0] output_wide;
  // Copies of the fields that steer wide selections, one per lane, bank or
  // slice, so that each select net stays inside what it steers.
  (* dont_touch = "true" *) logic [SLOT_W-1:0] write_slot_lane [0:LANES-1];
  (* dont_touch = "true" *) logic [LANES-1:0] storage_ready_lane;
  (* dont_touch = "true" *) logic [SLOT_W-1:0] slot_lane [0:LANES-1];
  (* dont_touch = "true" *) logic [LANES-1:0] group_lane;
  (* dont_touch = "true" *) logic [COUNT_W-1:0] cursor_bank [0:BANK_LANES-1];
  (* dont_touch = "true" *) logic [3:0] rotate_lane [0:BANK_LANES-1];
  (* dont_touch = "true" *) logic [COUNT_W-1:0] native_shift [0:NATIVE_SLICES-1];

  initial begin
    if (LANES < 16 || LANES > 128 || (LANES & (LANES-1)) != 0
        || SLOTS < 4 || (SLOTS & (SLOTS-1)) != 0)
      $fatal(1,"illegal banked segment geometry");
  end

  // Every stored tile also holds a place in the scheduler, whose queue is as
  // deep as the storage: free storage implies that the scheduler accepts.
  assign s_reserve_ready = storage_ready && !s_clear && !m_fault;
  assign s_ready = RESERVED_INPUT ? 1'b1 : s_reserve_ready;
  assign accept_tile = s_valid && s_ready;
  assign reserve_tile = RESERVED_INPUT ? s_reserve && s_reserve_ready : accept_tile;

  prism_numbergroup_segment_scheduler #(
      .KULISCH_W(KULISCH_W), .LANES(LANES), .QUEUE_DEPTH(SLOTS)
  ) u_schedule (
      .clk(clk), .rst_n(rst_n), .s_clear(s_clear),
      .s_mtu(s_mtu), .s_kulisch_bits(s_kulisch_bits),
      .s_first_element(s_first_element), .s_keep(s_keep), .s_formats(s_formats),
      .s_fp32_eligible(s_fp32_eligible), .s_error(s_error),
      .s_valid(accept_tile), .s_ready(schedule_ready),
      .m_first_element(segment_first), .m_count(segment_count),
      .m_cursor(segment_cursor), .m_last(segment_last),
      .m_formats(segment_formats), .m_group_fp32(segment_group),
      .m_valid(segment_valid), .m_ready(read_ready), .m_fault(m_fault)
  );

  // The read path never stalls. A segment is taken from the scheduler when
  // the output queue has room for it, and then moves one step per cycle:
  // descriptor, bank words, the same words again, alignment, one more
  // register, output queue. No
  // register on the way has an enable, and the last two steps are plain
  // registers back to back, which is where the path may cross to another
  // part of the device.
  //
  // Descriptor step: the segment descriptor and the copies of its slot,
  // group choice and cursor that address the banks. Segments leave the
  // scheduler in tile order, so the slot advances with the last segment.
  localparam int unsigned OUTPUT_DEPTH = 16;
  logic output_credit, output_taken, moved_valid, held_valid, aligned_valid, crossing_valid;
  logic [$clog2(OUTPUT_DEPTH+1)-1:0] outstanding, outstanding_next;
  assign read_ready = output_credit;
  assign read_load = segment_valid && output_credit;
  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      read_valid <= 1'b0;
      bank_valid <= 1'b0;
      moved_valid <= 1'b0;
      held_valid <= 1'b0;
      aligned_valid <= 1'b0;
      crossing_valid <= 1'b0;
    end else begin
      read_valid <= read_load;
      bank_valid <= read_valid;
      moved_valid <= bank_valid;
      held_valid <= moved_valid;
      aligned_valid <= held_valid;
      crossing_valid <= aligned_valid;
    end
  end
  always_ff @(posedge clk) begin
    read_descriptor.slot <= issue_slot;
    read_descriptor.cursor <= segment_cursor;
    read_descriptor.count <= segment_count;
    read_descriptor.first <= segment_first;
    read_descriptor.last <= segment_last;
    read_descriptor.formats <= segment_formats;
    for (int lane = 0; lane < LANES; lane++) begin
      slot_lane[lane] <= issue_slot;
      group_lane[lane] <= segment_group;
    end
    for (int bank = 0; bank < BANK_LANES; bank++) cursor_bank[bank] <= segment_cursor;
  end
  assign bank_load = read_valid;
  assign release_tile = bank_load && read_descriptor.last;
  // Each lane writes one stationary word per admitted tile. Exact readout
  // selects one column per modulo-16 bank; only the final 16-lane rotation
  // crosses banks. Native readout retains the full configured lane width.
  for (genvar bank=0; bank<BANK_LANES; bank++) begin : gen_bank
    logic [COLUMNS*WIDE_W-1:0] exact_columns;
    logic [COUNT_W-1:0] read_column;
    assign read_column = (cursor_bank[bank] >> 4)
        + COUNT_W'(bank < int'(cursor_bank[bank][3:0]));
    for (genvar column=0; column<COLUMNS; column++) begin : gen_column
      localparam int unsigned LANE = column*BANK_LANES+bank;
      // Each physical lane has a one-write/one-read memory. Keep the array
      // local to this generate instance: Vivado 2022.1 does not infer RAM
      // reliably from the equivalent [column][slot] multidimensional array.
      logic [WIDE_W-1:0] exact_words [0:SLOTS-1];
      logic [31:0] native_words [0:SLOTS-1];
      logic [31:0] fp32_words [0:SLOTS-1];
      (* dont_touch = "true" *) logic write;
      // A write during s_clear is harmless: the slot counters restart.
      if (RESERVED_INPUT) begin : gen_reserved_write
        assign write = s_lane_valid[LANE];
      end else begin : gen_accepted_write
        assign write = s_valid && storage_ready_lane[LANE] && !m_fault;
      end
      always_ff @(posedge clk) begin
        if (write) begin
          exact_words[write_slot_lane[LANE]] <= {
              s_tags[LANE*8+:8], s_integers[LANE*KULISCH_W+:KULISCH_W]};
          native_words[write_slot_lane[LANE]] <= s_native_bits[LANE*32+:32];
          fp32_words[write_slot_lane[LANE]] <= s_fp32_bits[LANE*32+:32];
        end
      end
      assign native_row[LANE*32+:32] = group_lane[LANE]
          ? fp32_words[slot_lane[LANE]] : native_words[slot_lane[LANE]];
      assign exact_columns[column*WIDE_W+:WIDE_W] = exact_words[slot_lane[LANE]];
    end
    assign bank_values[bank*WIDE_W+:WIDE_W] = int'(read_column)<COLUMNS
        ? exact_columns[int'(COLUMN_W'(read_column))*WIDE_W+:WIDE_W] : '0;
  end
  // Bank step: the column-selected exact words and the native row of the
  // slot. Storage is released when this step holds the last segment of a
  // tile. The words are then registered twice more on their way from the
  // memories of the lanes, which lie all over the block, to the alignment;
  // the second of these steps adds the copies of the cursor that steer it.
  always_ff @(posedge clk) begin
    banked_first <= read_descriptor.first;
    banked_count <= read_descriptor.count;
    banked_cursor <= read_descriptor.cursor;
    banked_formats <= read_descriptor.formats;
    banked_native <= native_row;
    banked_values <= bank_values;

    moved_first <= banked_first;
    moved_count <= banked_count;
    moved_cursor <= banked_cursor;
    moved_formats <= banked_formats;
    moved_native <= banked_native;
    moved_values <= banked_values;

    held_first <= moved_first;
    held_count <= moved_count;
    held_formats <= moved_formats;
    held_native <= moved_native;
    held_values <= moved_values;
    for (int lane = 0; lane < BANK_LANES; lane++)
      rotate_lane[lane] <= moved_cursor[3:0];
    for (int slice = 0; slice < NATIVE_SLICES; slice++)
      native_shift[slice] <= moved_cursor;
  end
  // Both alignments move the row through one fixed-distance step per cursor
  // bit. A step is computed once for the whole row; each slice or lane picks
  // its result with its own copy of the cursor bit, so the copies add no logic.
  logic [LANES*32-1:0] native_step [0:COUNT_W];
  assign native_step[0] = held_native;
  for (genvar step=0; step<COUNT_W; step++) begin : gen_native_step
    logic [LANES*32-1:0] moved;
    if ((1 << step) < LANES) begin : in_range
      assign moved = native_step[step] >> ((1 << step)*32);
    end else begin : past_row
      assign moved = '0;
    end
    for (genvar slice=0; slice<NATIVE_SLICES; slice++) begin : gen_slice
      assign native_step[step+1][slice*NATIVE_SLICE_LANES*32 +: NATIVE_SLICE_LANES*32]
          = native_shift[slice][step]
              ? moved[slice*NATIVE_SLICE_LANES*32 +: NATIVE_SLICE_LANES*32]
              : native_step[step][slice*NATIVE_SLICE_LANES*32 +: NATIVE_SLICE_LANES*32];
    end
  end
  assign selected_native = native_step[COUNT_W];

  logic [BANK_LANES*WIDE_W-1:0] rotate_step [0:4];
  assign rotate_step[0] = held_values;
  for (genvar step=0; step<4; step++) begin : gen_rotate_step
    for (genvar lane=0; lane<BANK_LANES; lane++) begin : gen_lane
      localparam int unsigned SOURCE = (lane + (1 << step)) % BANK_LANES;
      assign rotate_step[step+1][lane*WIDE_W+:WIDE_W] = rotate_lane[lane][step]
          ? rotate_step[step][SOURCE*WIDE_W+:WIDE_W]
          : rotate_step[step][lane*WIDE_W+:WIDE_W];
    end
  end
  assign selected_wide = rotate_step[4];
  // Alignment step and the register after it, then the output queue. The
  // consumer reads the head of the queue: its ready moves the read pointer
  // and no data register, so it should register what it takes.
  logic [OUTPUT_W-1:0] aligned_word, crossing_word;
  logic unused_queue_ready;
  assign output_word = {held_first, held_count, held_formats,
      selected_native, selected_wide};
  always_ff @(posedge clk) begin
    aligned_word <= output_word;
    crossing_word <= aligned_word;
  end
  prism_elastic_fifo #(
      .WIDTH(OUTPUT_W), .DEPTH(OUTPUT_DEPTH), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
  ) u_queue (
      .clk(clk), .rst_n(rst_n && !s_clear),
      .s_data(crossing_word), .s_valid(crossing_valid), .s_ready(unused_queue_ready),
      .m_data({m_first_element,m_count,m_formats,m_native_bits,output_wide}),
      .m_valid(m_valid), .m_ready(m_ready), .occupancy()
  );
  // A segment holds a place in the output queue from the cycle it is taken
  // until the consumer has it.
  assign output_taken = m_valid && m_ready;
  always_comb begin
    outstanding_next = outstanding;
    case ({read_load, output_taken})
      2'b10: outstanding_next = outstanding + 1'b1;
      2'b01: outstanding_next = outstanding - 1'b1;
      default: ;
    endcase
  end
  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      outstanding <= '0;
      output_credit <= 1'b1;
    end else begin
      outstanding <= outstanding_next;
      output_credit <= int'(outstanding_next) < OUTPUT_DEPTH;
    end
  end  for (genvar lane=0; lane<LANES; lane++) begin : gen_output
    if (lane<BANK_LANES) begin : wide_lane
      assign m_integers[lane*KULISCH_W+:KULISCH_W]
          = output_wide[lane*WIDE_W+:KULISCH_W];
      assign m_tags[lane*8+:8] = output_wide[lane*WIDE_W+KULISCH_W+:8];
    end else begin : native_lane
      // The scheduler keeps exact values on the sixteen low lanes of a segment.
      // Native values have no tag or exact integer field on the wire.
      assign m_integers[lane*KULISCH_W+:KULISCH_W] = '0;
      assign m_tags[lane*8+:8] = '0;
    end
  end

  always_comb begin
    occupied_next = occupied;
    case ({reserve_tile, release_tile})
      2'b10: occupied_next = occupied + 1'b1;
      2'b01: occupied_next = occupied - 1'b1;
      default: ;
    endcase
  end
  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      write_slot <= '0;
      issue_slot <= '0;
      occupied <= '0;
      storage_ready <= 1'b1;
      storage_ready_lane <= '1;
      for (int lane = 0; lane < LANES; lane++) write_slot_lane[lane] <= '0;
    end else begin
      if (accept_tile) begin
        write_slot <= write_slot + SLOT_W'(1);
        for (int lane = 0; lane < LANES; lane++)
          write_slot_lane[lane] <= write_slot + SLOT_W'(1);
      end
      occupied <= occupied_next;
      storage_ready <= int'(occupied_next) < SLOTS;
      storage_ready_lane <= {LANES{int'(occupied_next) < SLOTS}};
      if (read_load && segment_last) issue_slot <= issue_slot + SLOT_W'(1);
    end
  end

  // synthesis translate_off
  // Independent tracking of every tile from its write to its last read.
  logic [COUNT_W-1:0] verification_tile_count [0:SLOTS-1];
  logic [COUNT_W-1:0] verification_cursor;
  always_ff @(posedge clk) begin
    if (!rst_n || s_clear) begin
      verification_cursor <= '0;
    end else begin
      if (accept_tile)
        verification_tile_count[write_slot] <= COUNT_W'($countones(s_keep));
      if (read_load) begin
        assert (segment_cursor == verification_cursor);
        assert (segment_last == (verification_cursor + segment_count
            == verification_tile_count[issue_slot]));
        verification_cursor <= segment_last ? '0 : verification_cursor + segment_count;
      end
    end
  end
  always_ff @(posedge clk) begin
    if (rst_n && !s_clear) begin
      assert (occupied <= $bits(occupied)'(SLOTS));
      assert (!(crossing_valid && !unused_queue_ready));
      assert (!accept_tile || schedule_ready || m_fault);
      if (RESERVED_INPUT) begin
        assert (!s_valid || s_lane_valid == '1);
        assert (!accept_tile || occupied != 0);
      end
      assert (!(accept_tile && bank_load && write_slot == read_descriptor.slot));
      for (int lane = 0; lane < LANES; lane++)
        assert (write_slot_lane[lane] == write_slot);
      if (bank_load) begin
        assert (occupied != 0);
        assert (read_descriptor.cursor + read_descriptor.count
            <= verification_tile_count[read_descriptor.slot]);
        for (int lane=16; lane<LANES; lane++)
          assert (lane>=int'(read_descriptor.count)
              || read_descriptor.formats[lane*8+:8] != prism_pkg::PRISM_FORMAT_KULISCH);
      end
    end
  end
  // synthesis translate_on
endmodule
