//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_mixed_tile_streamer.sv
// Module: prism_numbergroup_mixed_tile_streamer
// Description: Packs concrete mixed-format tiles into bounded NumberGroup frames.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_mixed_tile_streamer #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_KULISCH_BITS = 4096,
    parameter int unsigned MTU_BYTES = 1500,
    parameter int unsigned LANES = 16,
    parameter prism_pkg::prism_opcode_e PACKET_CLASS = prism_pkg::PRISM_OP_COL_DATA
) (
    input  logic                                 clk,
    input  logic                                 rst_n,
    input  logic                                 s_reset,
    input  prism_pkg::prism_numbergroup_header_t s_header,
    input  logic [31:0]                          s_total_elements,
    input  logic [15:0]                          s_mtu,
    input  logic [15:0]                          s_kulisch_bits,
    input  logic [7:0]                           s_first_frame_tiles,
    input  logic [31:0]                          s_tile_first_element,
    input  logic [$clog2(LANES+1)-1:0]           s_tile_count,
    input  logic [LANES*8-1:0]                   s_formats,
    input  logic [LANES*32-1:0]                  s_native_bits,
    input  logic [LANES*8-1:0]                   s_tags,
    input  logic [LANES*KULISCH_W-1:0]           s_integers,
    input  logic                                 s_tile_valid,
    output logic                                 s_tile_ready,
    output logic [511:0]                         m_axis_tdata,
    output logic [63:0]                          m_axis_tkeep,
    output logic                                 m_axis_tlast,
    output logic [15:0]                          m_frame_bytes,
    output logic [31:0]                          m_packet_id,
    output logic                                 m_last_frame_done,
    output logic                                 m_axis_tvalid,
    input  logic                                 m_axis_tready,
    output logic                                 m_fault
);

  import prism_pkg::*;

  localparam int unsigned INTEGER_BYTES = (KULISCH_W + 7) / 8;
  // The configured MTU excludes the 14-byte Ethernet header.
  localparam int unsigned TILE_BYTES = MTU_BYTES
      - PRISM_CONTROL_WORD_BYTES - PRISM_DATA_HEADER_BYTES;
  localparam int unsigned SEGMENT_BYTES = INTEGER_BYTES + 8;
  localparam int unsigned NATIVE_SEGMENT_BYTES = 8;
  localparam int unsigned WIDE_LANES = LANES < 16 ? LANES : 16;
  localparam int unsigned ENCODE_BYTES =
      (LANES*SEGMENT_BYTES > 520 ? LANES*SEGMENT_BYTES : 520) < TILE_BYTES
      ? (LANES*SEGMENT_BYTES > 520 ? LANES*SEGMENT_BYTES : 520)
      : TILE_BYTES;
  localparam int unsigned WRITE_BYTES = LANES >= 128 ? 128 : 64;
  localparam int unsigned NATIVE_ENCODE_BYTES =
      LANES*NATIVE_SEGMENT_BYTES < TILE_BYTES
      ? LANES*NATIVE_SEGMENT_BYTES : TILE_BYTES;
  localparam int unsigned WIDE_ENCODE_BYTES =
      WIDE_LANES*SEGMENT_BYTES < TILE_BYTES
      ? WIDE_LANES*SEGMENT_BYTES : TILE_BYTES;
  localparam int unsigned MAX_BEATS =
      (PRISM_ETH_HEADER_BYTES + MTU_BYTES + 63) / 64;
  localparam int unsigned BEAT_W = $clog2(MAX_BEATS + 1);
  localparam int unsigned HALF_BEATS = (MAX_BEATS + 1) / 2;
  localparam int unsigned WORD_INDEX_W = $clog2(HALF_BEATS);
  localparam int unsigned COUNT_W = $clog2(LANES + 1);
  localparam int unsigned RUN_STAGES = $clog2(LANES);

  localparam int unsigned WIDE_LENGTH_W=$clog2(SEGMENT_BYTES+1);
  logic [NATIVE_ENCODE_BYTES*8-1:0] packed_native_bits;
  logic [WIDE_ENCODE_BYTES*8-1:0] packed_wide_bits;
  logic [15:0] packed_native_bytes,packed_wide_bytes;
  logic unused_wide_meta;

  initial begin
    if (KULISCH_W < 278 || KULISCH_W > 320
        || MAX_KULISCH_BITS < 278 || MAX_KULISCH_BITS > 4096
        || MTU_BYTES < 576 || MTU_BYTES > 1500
        || PACKET_CLASS != PRISM_OP_COL_DATA
            && PACKET_CLASS != PRISM_OP_COL_RES)
      $fatal(1, "mixed tile streamer requires bounded SINGLE geometry");
  end
  // A tile with a Kulisch value has a wide part, from the sixteen low lanes,
  // and a native part from the lanes above. The native part is joined to the
  // wide one at a multiple of JOIN_BYTES; the encoder leaves the remaining
  // bytes of the offset empty in front of the native part.
  localparam int unsigned JOIN_BYTES = 128;
  localparam int unsigned JOIN_W = $clog2(WIDE_LANES*SEGMENT_BYTES/JOIN_BYTES + 1);
  localparam bit TWO_PARTS = LANES > WIDE_LANES;
  typedef struct packed {
    logic has_kulisch,extended_wire;
    logic [15:0] kulisch_bits;
    logic [KULISCH_W-1:0] extension_integer;
    logic [7:0] extension_tag;
  } encode_context_t;
  encode_context_t input_context, encoded_context;
  typedef struct packed {
    logic bank, strip_descriptor;
    logic [15:0] offset, bytes;
  } plan_context_t;
  plan_context_t planned_context;
  // The plan queue covers every tile that the merge trees can hold.
  localparam int unsigned PLAN_DEPTH = 32;
  logic plan_valid, plan_input_ready, planner_input_ready;
  logic accept_tile, issue;
  logic native_ready,wide_ready,native_valid,wide_valid;
  logic fork_valid,source_needs_wide;
  logic planner_tile_valid,planner_tile_ready,planner_bank,planner_strip;
  logic [15:0] planner_offset,planner_bytes;
  logic planner_patch_valid,planner_patch_ready,planner_patch_bank;
  logic [15:0] planner_patch_offset,planner_patch_count;
  logic [1:0] planner_frame_valid,planner_frame_ready,planner_bank_busy,planner_frame_last;
  localparam int unsigned HEADER_CONTEXT_W=$bits(prism_numbergroup_header_t);
  logic [2*HEADER_CONTEXT_W-1:0] planner_headers;
  logic [895:0] wire_headers;
  logic [63:0] planner_packet_ids,planner_first_elements;
  logic [31:0] planner_frame_elements,planner_frame_bytes;
  logic [15:0] planner_frame_groups;
  logic planner_fault,store_fault,internal_fault,release_valid,release_bank,context_reset;

  // A tile is encoded in three steps without stalls and then enters the
  // merge trees, which do not stall either. A tile is accepted only while
  // the encoder and the trees together hold fewer tiles than the queues
  // behind the trees can store, and while the plan request queue has room.
  // The number covers the tiles on their way at one tile per cycle: encoder,
  // trees, output registers and the issue of the ticket.
  localparam int unsigned TILE_CREDITS=32;
  localparam int unsigned REQUEST_DEPTH=16;
  typedef struct packed {
    prism_numbergroup_header_t header;
    logic [31:0] total_elements,first_element;
    logic [15:0] mtu;
    logic [7:0] first_frame_tiles;
  } tile_context_t;
  tile_context_t input_tile_context,encoded_tile_context;
  typedef struct packed {
    prism_numbergroup_header_t header;
    logic [31:0] total_elements,first_element;
    logic [15:0] mtu,kulisch_bits,count,bytes;
    logic [7:0] groups,first_frame_tiles,format;
    logic uniform,padded,encoding_valid;
  } plan_request_t;
  plan_request_t request_input,request_output,queued_request;
  logic queued_request_valid,queued_request_ready;
  logic request_valid,unused_request_ready;
  logic accept_input,tile_credit,request_credit,preparation_fault;
  logic [$clog2(TILE_CREDITS+1)-1:0] tiles_inside,tiles_inside_next;
  logic [$clog2(REQUEST_DEPTH+1)-1:0] requests_inside,requests_inside_next;
  logic tile_encoded,tile_uniform,tile_padded,tile_encoding_valid,tile_has_kulisch,tile_extended;
  logic [15:0] tile_kulisch_bits,tile_count,tile_size;
  logic [JOIN_W-1:0] tile_join;
  logic [7:0] tile_groups,tile_format,tile_extension_tag;
  logic [KULISCH_W-1:0] tile_extension_integer;
  logic [LANES*NATIVE_SEGMENT_BYTES*8-1:0] tile_native_data;
  logic [LANES*4-1:0] tile_native_lengths;
  logic [WIDE_LANES*SEGMENT_BYTES*8-1:0] tile_wide_data;
  logic [WIDE_LANES*WIDE_LENGTH_W-1:0] tile_wide_lengths;

  // A tile offered during s_reset is taken and dropped: the reset reaches
  // the single accept flag, not the ready that steers the sender's registers.
  assign s_tile_ready=tile_credit && request_credit;
  assign accept_input=s_tile_valid && s_tile_ready && !s_reset;
  assign input_tile_context.header=s_header;
  assign input_tile_context.total_elements=s_total_elements;
  assign input_tile_context.first_element=s_tile_first_element;
  assign input_tile_context.mtu=s_mtu;
  assign input_tile_context.first_frame_tiles=s_first_frame_tiles;
  prism_numbergroup_tile_encoder #(.KULISCH_W(KULISCH_W),.MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .LANES(LANES),.USER_W($bits(tile_context_t)),.JOIN_BYTES(JOIN_BYTES)) u_encode (
      .clk(clk),.rst_n(rst_n && !context_reset),.s_kulisch_bits(s_kulisch_bits),
      .s_count(s_tile_count),.s_formats(s_formats),.s_native_bits(s_native_bits),
      .s_tags(s_tags),.s_integers(s_integers),.s_user(input_tile_context),.s_valid(accept_input),
      .m_valid(tile_encoded),.m_user(encoded_tile_context),.m_kulisch_bits(tile_kulisch_bits),
      .m_count(tile_count),.m_bytes(tile_size),.m_groups(tile_groups),.m_format(tile_format),
      .m_uniform(tile_uniform),.m_padded(tile_padded),.m_encoding_valid(tile_encoding_valid),
      .m_has_kulisch(tile_has_kulisch),.m_join(tile_join),.m_extended_wire(tile_extended),
      .m_extension_tag(tile_extension_tag),.m_extension_integer(tile_extension_integer),
      .m_native_data(tile_native_data),.m_native_lengths(tile_native_lengths),
      .m_wide_data(tile_wide_data),.m_wide_lengths(tile_wide_lengths)
  );
  always_comb begin
    request_input.header=encoded_tile_context.header;
    request_input.total_elements=encoded_tile_context.total_elements;
    request_input.first_element=encoded_tile_context.first_element;
    request_input.mtu=encoded_tile_context.mtu;
    request_input.kulisch_bits=tile_kulisch_bits;
    request_input.count=tile_count;
    request_input.bytes=tile_size;
    request_input.groups=tile_groups;
    request_input.first_frame_tiles=encoded_tile_context.first_frame_tiles;
    request_input.format=tile_format;
    request_input.uniform=tile_uniform;
    request_input.padded=tile_padded;
    request_input.encoding_valid=tile_encoding_valid;
  end
  // The payload and its narrow planning request leave the encoder together
  // and retire independently. A fault is terminal and the parent stops the
  // output one cycle after it, so fault flags gate only the planner.
  prism_elastic_fifo #(.WIDTH($bits(plan_request_t)),.DEPTH(REQUEST_DEPTH),
      .READY_ON_POP(1'b0),.REGISTER_READY(1'b1)) u_requests (
      .clk(clk),.rst_n(rst_n && !context_reset),
      .s_data(request_input),.s_valid(tile_encoded),.s_ready(unused_request_ready),
      .m_data(queued_request),.m_valid(queued_request_valid),
      .m_ready(queued_request_ready),.occupancy()
  );
  // The planner reads the request at the head from a register, not from the
  // memory of the queue.
  prism_elastic_register #(.WIDTH($bits(plan_request_t))) u_request (
      .clk(clk),.rst_n(rst_n && !context_reset),
      .s_data(queued_request),.s_valid(queued_request_valid),.s_ready(queued_request_ready),
      .m_data(request_output),.m_valid(request_valid),.m_ready(planner_input_ready)
  );
  always_ff @(posedge clk) begin
    if(!rst_n || context_reset) preparation_fault<=1'b0;
    else if(tile_encoded && (!tile_encoding_valid || tile_kulisch_bits < 16'd278
        || tile_kulisch_bits > 16'(MAX_KULISCH_BITS)))
      preparation_fault<=1'b1;
  end
  always_comb begin
    tiles_inside_next=tiles_inside;
    case({accept_input,accept_tile})
      2'b10: tiles_inside_next=tiles_inside+1'b1;
      2'b01: tiles_inside_next=tiles_inside-1'b1;
      default: ;
    endcase
    requests_inside_next=requests_inside;
    case({accept_input,request_valid && planner_input_ready})
      2'b10: requests_inside_next=requests_inside+1'b1;
      2'b01: requests_inside_next=requests_inside-1'b1;
      default: ;
    endcase
  end
  always_ff @(posedge clk) begin
    if(!rst_n || context_reset) begin
      tiles_inside<='0;requests_inside<='0;tile_credit<=1'b1;request_credit<=1'b1;
    end else begin
      tiles_inside<=tiles_inside_next;requests_inside<=requests_inside_next;
      tile_credit<=int'(tiles_inside_next)<TILE_CREDITS;
      request_credit<=int'(requests_inside_next)<REQUEST_DEPTH;
    end
  end
  // The payload of a tile goes through the merge trees while its plan is
  // made. The two meet again in a ticket: a small record per tile that is
  // issued once the payload has left the trees and the plan exists. Every
  // slice of the tree outputs and of the slicer has its own queue of
  // tickets, written from registers one cycle after the ticket is issued,
  // and takes its part of the tile when its own ticket says so. No signal
  // shared across the tile takes part in that decision.
  assign input_context='{has_kulisch:tile_has_kulisch,extended_wire:tile_extended,
      kulisch_bits:tile_kulisch_bits,extension_integer:tile_extension_integer,
      extension_tag:tile_extension_tag};
  assign source_needs_wide=tile_has_kulisch && !tile_extended;
  assign planner_tile_ready=plan_input_ready;
  assign fork_valid=tile_encoded;
  // synthesis translate_off
  always_ff @(posedge clk) begin
    if(rst_n && !context_reset) begin
      assert(!(fork_valid && !native_ready));
      assert(!(fork_valid && source_needs_wide && !wide_ready));
      assert(!(tile_encoded && !unused_request_ready));
    end
  end
  // synthesis translate_on
  localparam bit EXTENSION = MAX_KULISCH_BITS > KULISCH_W;
  localparam int unsigned EXTENSION_BYTES = EXTENSION
      ? (5 + (MAX_KULISCH_BITS + 7) / 8 + 3) & ~3 : 0;
  localparam int unsigned LARGER_ENCODE_BYTES = WIDE_ENCODE_BYTES > EXTENSION_BYTES
      ? WIDE_ENCODE_BYTES : EXTENSION_BYTES;
  // The first part of an encoded tile is its wide part or, for a Kulisch
  // value wider than the datapath, the value alone; the second part is its
  // native part. A tile without a Kulisch value has only the second.
  localparam int unsigned SLICE_BYTES = LARGER_ENCODE_BYTES > 128 ? LARGER_ENCODE_BYTES : 128;
  localparam int unsigned TAIL_BYTES = NATIVE_ENCODE_BYTES > 128 ? NATIVE_ENCODE_BYTES : 128;
  localparam int unsigned SELECT_BITS = 256;
  localparam int unsigned SLICE_W = SLICE_BYTES*8;
  localparam int unsigned TAIL_W = TAIL_BYTES*8;
  localparam int unsigned SELECT_COPIES = (SLICE_W + SELECT_BITS - 1) / SELECT_BITS;
  localparam int unsigned TAIL_COPIES = (TAIL_W + SELECT_BITS - 1) / SELECT_BITS;
  localparam int unsigned WINDOW_COPIES = (1536 + SELECT_BITS - 1) / SELECT_BITS;
  localparam int unsigned CHUNKS_W = $clog2((SLICE_BYTES + TAIL_BYTES + JOIN_BYTES - 1) / JOIN_BYTES + 1);
  localparam int unsigned SKIP_W = $clog2(SLICE_BYTES / JOIN_BYTES + 1);
  localparam int unsigned WIDE_SLICES = (WIDE_ENCODE_BYTES*8 + 16 + 1 + 255) / 256;
  localparam int unsigned NATIVE_SLICES
      = (NATIVE_ENCODE_BYTES*8 + 16 + $bits(encode_context_t) + 255) / 256;

  // What is known of a tile when it leaves the encoder, in tile order.
  typedef struct packed {
    logic has_kulisch, extended;
    logic [JOIN_W-1:0] tail_skip;
  } kind_t;
  kind_t kind;
  logic unused_kind_ready, unused_kind_valid;
  prism_elastic_fifo #(.WIDTH($bits(kind_t)),.DEPTH(TILE_CREDITS),
      .READY_ON_POP(1'b0),.REGISTER_READY(1'b1)) u_kinds (
      .clk(clk),.rst_n(rst_n && !context_reset),
      .s_data({tile_has_kulisch,tile_extended,tile_join}),.s_valid(fork_valid),
      .s_ready(unused_kind_ready),
      .m_data(kind),.m_valid(unused_kind_valid),.m_ready(issue),.occupancy()
  );
  prism_elastic_fifo #(.WIDTH($bits(plan_context_t)),.DEPTH(PLAN_DEPTH),
      .READY_ON_POP(1'b0),.REGISTER_READY(1'b1)) u_plans (
      .clk(clk),.rst_n(rst_n && !context_reset),
      .s_data({planner_bank,planner_strip,planner_offset,planner_bytes}),
      .s_valid(planner_tile_valid),.s_ready(plan_input_ready),
      .m_data(planned_context),.m_valid(plan_valid),.m_ready(issue),.occupancy()
  );
  assign context_reset=s_reset && planner_bank_busy==0;
  assign m_fault=planner_fault || store_fault || internal_fault || preparation_fault;
  prism_numbergroup_frame_planner #(.MTU_BYTES(MTU_BYTES),.HEADER_W(HEADER_CONTEXT_W)) u_plan (
      .clk(clk),.rst_n(rst_n),.s_reset(s_reset),.s_header(request_output.header),
      .s_packet_id(request_output.header.packet_id),.s_total_elements(request_output.total_elements),.s_first_element(request_output.first_element),
      .s_mtu(request_output.mtu),.s_kulisch_bits(request_output.kulisch_bits),.s_count(request_output.count),.s_bytes(request_output.bytes),
      .s_groups(request_output.groups),.s_first_frame_tiles(request_output.first_frame_tiles),.s_format(request_output.format),
      .s_uniform(request_output.uniform),.s_padded(request_output.padded),.s_encoding_valid(request_output.encoding_valid),
      .s_valid(request_valid && !store_fault && !internal_fault && !preparation_fault),.s_ready(planner_input_ready),
      .m_tile_valid(planner_tile_valid),.m_tile_ready(planner_tile_ready),
      .m_tile_bank(planner_bank),.m_tile_strip_descriptor(planner_strip),
      .m_tile_offset(planner_offset),.m_tile_bytes(planner_bytes),
      .m_patch_valid(planner_patch_valid),.m_patch_ready(planner_patch_ready),.m_patch_bank(planner_patch_bank),
      .m_patch_offset(planner_patch_offset),.m_patch_count(planner_patch_count),
      .m_frame_valid(planner_frame_valid),.m_frame_ready(planner_frame_ready),.m_frame_header(planner_headers),
      .m_frame_packet_id(planner_packet_ids),.m_frame_first_element(planner_first_elements),
      .m_frame_elements(planner_frame_elements),.m_frame_bytes(planner_frame_bytes),
      .m_frame_groups(planner_frame_groups),.m_frame_last(planner_frame_last),.m_bank_busy(planner_bank_busy),
      .s_release_valid(release_valid),.s_release_bank(release_bank),.m_fault(planner_fault)
  );
  logic native_arrived, unused_wide_arrived;
  // A merge level whose nodes are at least this wide takes two steps.
  localparam int unsigned SPLIT_BYTES = 512;
  logic [NATIVE_SLICES-1:0] native_take;
  logic [WIDE_SLICES-1:0] wide_take;
  prism_numbergroup_tile_merge_pipeline #(.LANES(LANES),.SEGMENT_BYTES(NATIVE_SEGMENT_BYTES),
      .CAP_BYTES(NATIVE_ENCODE_BYTES),.META_W($bits(encode_context_t)),
      .FIFO_DEPTH(TILE_CREDITS),.SPLIT_BYTES(SPLIT_BYTES)) native_merge (
      .clk(clk),.rst_n(rst_n && !context_reset),.s_lane_data(tile_native_data),.s_lane_length(tile_native_lengths),
      .s_meta(input_context),.s_valid(fork_valid),.s_ready(native_ready),.m_data(packed_native_bits),
      .m_length(packed_native_bytes),.m_meta(encoded_context),.m_valid(native_valid),
      .m_arrived(native_arrived),.m_take(native_take)
  );
  prism_numbergroup_tile_merge_pipeline #(.LANES(WIDE_LANES),.SEGMENT_BYTES(SEGMENT_BYTES),
      .CAP_BYTES(WIDE_ENCODE_BYTES),.META_W(1),.FIFO_DEPTH(TILE_CREDITS),
      .SPLIT_BYTES(SPLIT_BYTES)) wide_merge (
      .clk(clk),.rst_n(rst_n && !context_reset),.s_lane_data(tile_wide_data),
      .s_lane_length(tile_wide_lengths),.s_meta(1'b0),.s_valid(fork_valid && source_needs_wide),
      .s_ready(wide_ready),.m_data(packed_wide_bits),.m_length(packed_wide_bytes),
      .m_meta(unused_wide_meta),.m_valid(wide_valid),
      .m_arrived(unused_wide_arrived),.m_take(wide_take)
  );
  // Cycles a tile spends in a merge tree: one per level, two for a level
  // whose nodes are at least SPLIT_BYTES wide.
  function automatic int unsigned tree_steps(
      input int unsigned lanes, input int unsigned segment, input int unsigned cap);
    int unsigned steps, node;
    steps = 0;
    for (int unsigned level = 1; level <= $clog2(lanes); level++) begin
      node = (segment << level) < cap ? (segment << level) : cap;
      steps += level > 1 && node >= SPLIT_BYTES ? 2 : 1;
    end
    return steps;
  endfunction
  initial begin
    // The ticket of a tile is issued when the native tree has delivered it
    // and reaches the slices four cycles later; the wide part must be in its
    // output registers by then, two cycles after it leaves its tree.
    if (tree_steps(WIDE_LANES, SEGMENT_BYTES, WIDE_ENCODE_BYTES)
        > tree_steps(LANES, NATIVE_SEGMENT_BYTES, NATIVE_ENCODE_BYTES) + 2)
      $fatal(1, "the wide tree delivers too late for the ticket of its tile");
  end

  // A ticket is issued for the oldest tile once its payload has left the
  // native tree, which is the slower one, and its plan is in the queue.
  typedef struct packed {
    logic strip, has_kulisch, extended;
    logic [CHUNKS_W-1:0] chunks;
    logic [SKIP_W-1:0] tail_skip;
    logic [5:0] phase;
  } ticket_t;
  localparam int unsigned TICKET_W = $bits(ticket_t);
  logic ticket_valid;
  ticket_t ticket_next, ticket;
  plan_context_t ticket_plan;
  logic [$clog2(TILE_CREDITS+1)-1:0] arrived_tiles;
  assign issue = plan_valid && arrived_tiles != 0;
  always_comb begin
    ticket_next.strip = planned_context.strip_descriptor;
    ticket_next.has_kulisch = kind.has_kulisch;
    ticket_next.extended = EXTENSION && kind.extended;
    ticket_next.chunks = CHUNKS_W'((planned_context.bytes + 16'(JOIN_BYTES - 1)) / 16'(JOIN_BYTES));
    ticket_next.tail_skip = SKIP_W'(kind.tail_skip);
    ticket_next.phase = 6'(planned_context.offset) + 6'd56;
  end
  always_ff @(posedge clk) begin
    if (!rst_n || context_reset) begin
      arrived_tiles <= '0;
      ticket_valid <= 1'b0;
    end else begin
      arrived_tiles <= arrived_tiles + $bits(arrived_tiles)'(native_arrived)
          - $bits(arrived_tiles)'(issue);
      ticket_valid <= issue;
    end
  end
  always_ff @(posedge clk) begin
    ticket <= ticket_next;
    ticket_plan <= planned_context;
  end

  // A chunk may leave the slicer while the queue behind it has room for it
  // and for the chunks already on their way; every slice has a registered
  // copy of that permission.
  logic credit;
  (* dont_touch = "true" *) logic [SELECT_COPIES-1:0] credit_wide;
  (* dont_touch = "true" *) logic [TAIL_COPIES-1:0] credit_tail;
  (* dont_touch = "true" *) logic credit_plan;
  always_ff @(posedge clk) begin
    credit_wide <= {SELECT_COPIES{credit}};
    credit_tail <= {TAIL_COPIES{credit}};
    credit_plan <= credit;
  end

  logic [ENCODE_BYTES*8-1:0] retired_extension_bits;
  logic [15:0] retired_extension_bytes;
  always_comb begin
    retired_extension_bits = '0;
    retired_extension_bits[7:0] = PRISM_FORMAT_KULISCH;
    retired_extension_bits[31:24] = 8'd1;
    retired_extension_bits[39:32] = encoded_context.extension_tag;
    for (int byte_index = 0; byte_index < 512; byte_index++)
      if (byte_index < (int'(encoded_context.kulisch_bits)+7)/8)
        retired_extension_bits[(5+byte_index)*8 +: 8] = byte_index < INTEGER_BYTES
            ? 8'(encoded_context.extension_integer >> (byte_index*8))
            : {8{encoded_context.extension_integer[KULISCH_W-1]}};
    retired_extension_bytes = 16'((5 + (int'(encoded_context.kulisch_bits)+7)/8 + 3) & ~3);
  end

  // Slices of the first part: each selects its source and drops the first
  // descriptor by the ticket in its own queue.
  logic [SLICE_W-1:0] extension_source, wide_source;
  logic [SLICE_W-1:0] selected_bits, stripped_bits, tile_bits;
  logic [TAIL_W-1:0] native_source, stripped_native, tail_bits;
  logic [SELECT_COPIES-1:0] wide_ticket_valid, wide_slice_take, wide_slice_pop;
  logic [SELECT_COPIES-1:0] wide_ticket_valid_next;
  logic [SELECT_COPIES*CHUNKS_W-1:0] wide_ticket_chunks;
  logic [SELECT_COPIES*6-1:0] wide_ticket_phase;
  logic [TAIL_COPIES-1:0] tail_ticket_valid, tail_slice_take, tail_ticket_valid_next;
  logic [TAIL_COPIES*CHUNKS_W-1:0] tail_ticket_chunks;
  logic [TAIL_COPIES*SKIP_W-1:0] tail_ticket_skip;
  assign extension_source = SLICE_W'(retired_extension_bits);
  assign wide_source = SLICE_W'(packed_wide_bits);
  assign native_source = TAIL_W'(packed_native_bits);
  assign stripped_bits = selected_bits >> 32;
  assign stripped_native = native_source >> 32;
  for (genvar copy = 0; copy < SELECT_COPIES; copy++) begin : gen_select
    localparam int unsigned LOW = copy * SELECT_BITS;
    localparam int unsigned SIZE = (SLICE_W - LOW) < SELECT_BITS ? SLICE_W - LOW : SELECT_BITS;
    (* dont_touch = "true" *) logic push;
    (* dont_touch = "true" *) ticket_t arriving;
    ticket_t head;
    logic tickets_ready;
    logic [$clog2(TILE_CREDITS+1)-1:0] waiting;
    always_ff @(posedge clk) begin
      if (!rst_n || context_reset) push <= 1'b0;
      else push <= ticket_valid;
    end
    always_ff @(posedge clk) arriving <= ticket;
    (* dont_touch = "true" *) prism_elastic_fifo #(
        .WIDTH(TICKET_W), .DEPTH(TILE_CREDITS), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
    ) u_tickets (
        .clk(clk), .rst_n(rst_n && !context_reset),
        .s_data(arriving), .s_valid(push), .s_ready(tickets_ready),
        .m_data(head), .m_valid(wide_ticket_valid[copy]), .m_ready(wide_slice_take[copy]),
        .occupancy(waiting)
    );
    // Whether a ticket waits in the next cycle: one is pushed now, or one
    // stays behind the one that leaves.
    assign wide_ticket_valid_next[copy] = (push && tickets_ready) || waiting > 1
        || (waiting == 1 && !wide_slice_take[copy]);
    assign wide_ticket_chunks[copy*CHUNKS_W +: CHUNKS_W] = head.chunks;
    assign wide_ticket_phase[copy*6 +: 6] = head.phase;
    assign wide_slice_pop[copy] = wide_slice_take[copy] && head.has_kulisch
        && !(EXTENSION && head.extended);
    assign selected_bits[LOW +: SIZE] = EXTENSION && head.extended
        ? extension_source[LOW +: SIZE]
        : head.has_kulisch ? wide_source[LOW +: SIZE] : '0;
    assign tile_bits[LOW +: SIZE] = head.strip ? stripped_bits[LOW +: SIZE]
        : selected_bits[LOW +: SIZE];
  end
  for (genvar slice = 0; slice < WIDE_SLICES; slice++) begin : gen_wide_take
    assign wide_take[slice] = wide_slice_pop[slice < SELECT_COPIES ? slice : SELECT_COPIES - 1];
  end
  for (genvar copy = 0; copy < TAIL_COPIES; copy++) begin : gen_tail
    localparam int unsigned LOW = copy * SELECT_BITS;
    localparam int unsigned SIZE = (TAIL_W - LOW) < SELECT_BITS ? TAIL_W - LOW : SELECT_BITS;
    (* dont_touch = "true" *) logic push;
    (* dont_touch = "true" *) ticket_t arriving;
    ticket_t head;
    logic tickets_ready;
    logic [$clog2(TILE_CREDITS+1)-1:0] waiting;
    always_ff @(posedge clk) begin
      if (!rst_n || context_reset) push <= 1'b0;
      else push <= ticket_valid;
    end
    always_ff @(posedge clk) arriving <= ticket;
    (* dont_touch = "true" *) prism_elastic_fifo #(
        .WIDTH(TICKET_W), .DEPTH(TILE_CREDITS), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
    ) u_tickets (
        .clk(clk), .rst_n(rst_n && !context_reset),
        .s_data(arriving), .s_valid(push), .s_ready(tickets_ready),
        .m_data(head), .m_valid(tail_ticket_valid[copy]), .m_ready(tail_slice_take[copy]),
        .occupancy(waiting)
    );
    // Whether a ticket waits in the next cycle: one is pushed now, or one
    // stays behind the one that leaves.
    assign tail_ticket_valid_next[copy] = (push && tickets_ready) || waiting > 1
        || (waiting == 1 && !tail_slice_take[copy]);
    assign tail_ticket_chunks[copy*CHUNKS_W +: CHUNKS_W] = head.chunks;
    assign tail_ticket_skip[copy*SKIP_W +: SKIP_W] = head.tail_skip;
    assign tail_bits[LOW +: SIZE] = head.strip ? stripped_native[LOW +: SIZE]
        : native_source[LOW +: SIZE];
  end
  // The copy that describes the chunks also holds the plan of the tile and
  // takes the length and the context from the native tree.
  logic plan_push, plan_ticket_valid, plan_ticket_valid_next, plan_tickets_ready;
  logic [$clog2(TILE_CREDITS+1)-1:0] plan_waiting;
  ticket_t plan_arriving, plan_head;
  plan_context_t plan_arriving_context, plan_head_context;
  always_ff @(posedge clk) begin
    if (!rst_n || context_reset) plan_push <= 1'b0;
    else plan_push <= ticket_valid;
  end
  always_ff @(posedge clk) begin
    plan_arriving <= ticket;
    plan_arriving_context <= ticket_plan;
  end
  prism_elastic_fifo #(
      .WIDTH(TICKET_W + $bits(plan_context_t)), .DEPTH(TILE_CREDITS), .READY_ON_POP(1'b0),
      .REGISTER_READY(1'b1)
  ) u_plan_tickets (
      .clk(clk), .rst_n(rst_n && !context_reset),
      .s_data({plan_arriving, plan_arriving_context}), .s_valid(plan_push),
      .s_ready(plan_tickets_ready),
      .m_data({plan_head, plan_head_context}), .m_valid(plan_ticket_valid),
      .m_ready(accept_tile), .occupancy(plan_waiting)
  );
  assign plan_ticket_valid_next = (plan_push && plan_tickets_ready) || plan_waiting > 1
      || (plan_waiting == 1 && !accept_tile);
  for (genvar slice = 0; slice < NATIVE_SLICES; slice++) begin : gen_native_take
    if (slice < TAIL_COPIES && (slice + 1) * 256 <= NATIVE_ENCODE_BYTES * 8) begin : with_data
      assign native_take[slice] = tail_slice_take[slice];
    end else begin : with_context
      assign native_take[slice] = accept_tile;
    end
  end

  // The native part counts the empty bytes in front of it, which together
  // with the whole multiples of JOIN_BYTES are the bytes of the wide part.
  logic [15:0] tile_bytes;
  always_comb begin
    if(EXTENSION && plan_head.extended) tile_bytes=retired_extension_bytes;
    else if(plan_head.has_kulisch && TWO_PARTS)
      tile_bytes=16'(int'(plan_head.tail_skip)*JOIN_BYTES)+packed_native_bytes;
    else if(plan_head.has_kulisch) tile_bytes=packed_wide_bytes;
    else tile_bytes=packed_native_bytes;
    if(plan_head.strip) tile_bytes=tile_bytes-16'd4;
  end
  // The encoded tile leaves for the frame store in chunks of at most 128
  // bytes. Tiles are not packed together: the store appends chunks of any
  // length, and each chunk arrives moved to its position inside a store word.
  logic chunk_valid,chunk_bank;
  logic [WINDOW_COPIES-1:0] chunk_window_valid;
  logic [7:0] chunk_bytes;
  logic [1:0] chunk_flush;
  logic [15:0] chunk_offset;
  logic [1535:0] chunk_window;
  prism_numbergroup_chunk_slicer #(.TILE_BYTES(SLICE_BYTES),.TAIL_BYTES(TAIL_BYTES),
      .CHUNK_BYTES(JOIN_BYTES)) u_slice (
      .clk(clk),.rst_n(rst_n && !context_reset),
      .s_data(tile_bits),.s_tail(tail_bits),
      .s_valid(wide_ticket_valid),.s_credit(credit_wide),.s_chunks(wide_ticket_chunks),
      .s_valid_next(wide_ticket_valid_next),.s_credit_next({SELECT_COPIES{credit}}),
      .s_phase(wide_ticket_phase),.s_take(wide_slice_take),
      .s_tail_valid(tail_ticket_valid),.s_tail_credit(credit_tail),
      .s_tail_valid_next(tail_ticket_valid_next),.s_tail_credit_next({TAIL_COPIES{credit}}),
      .s_tail_chunks(tail_ticket_chunks),.s_tail_skip(tail_ticket_skip),
      .s_tail_take(tail_slice_take),
      .s_plan_valid(plan_ticket_valid),.s_plan_credit(credit_plan),
      .s_plan_valid_next(plan_ticket_valid_next),.s_plan_credit_next(credit),
      .s_plan_chunks(plan_head.chunks),.s_bytes(plan_head_context.bytes),
      .s_offset(plan_head_context.offset),.s_bank(plan_head_context.bank),
      .s_plan_take(accept_tile),
      .m_window(chunk_window),.m_bytes(chunk_bytes),.m_flush(chunk_flush),
      .m_offset(chunk_offset),.m_bank(chunk_bank),
      .m_valid(chunk_valid),.m_window_valid(chunk_window_valid)
  );
  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (rst_n && !context_reset) begin
      assert (!(ticket_valid && !plan_tickets_ready));
      assert (!(fork_valid && !unused_kind_ready));
      assert (!(issue && !unused_kind_valid));
      // Every slice takes the tile in the same cycle, and the payload is there.
      assert (wide_slice_take == {SELECT_COPIES{accept_tile}});
      assert (tail_slice_take == {TAIL_COPIES{accept_tile}});
      if (accept_tile) begin
        assert (native_valid);
        assert (plan_head.has_kulisch == encoded_context.has_kulisch);
        assert (plan_head.extended == encoded_context.extended_wire);
        assert (!(plan_head.has_kulisch && !plan_head.extended) || wide_valid);
        // Only a uniform tile loses its descriptor, and a uniform tile has one
        // part: after a wide part the native part is then only its empty bytes.
        if (plan_head.strip && plan_head.has_kulisch && !plan_head.extended && TWO_PARTS)
          assert (packed_native_bytes == 16'(packed_wide_bytes[6:0]));
        if (plan_head.has_kulisch && !plan_head.extended && TWO_PARTS)
          assert (packed_wide_bytes[15:7] == 9'(plan_head.tail_skip)
              && packed_native_bytes >= 16'(packed_wide_bytes[6:0]));
      end
    end
  end
  // synthesis translate_on
  always_ff @(posedge clk)begin
    if(!rst_n || context_reset)internal_fault<=0;
    else if(accept_tile && tile_bytes!=plan_head_context.bytes)internal_fault<=1;
  end  for(genvar bank=0;bank<2;bank++)begin:final_header
    prism_numbergroup_header_t h;
    logic [447:0] network_order;
    always_comb begin
      h=planner_headers[bank*HEADER_CONTEXT_W+:HEADER_CONTEXT_W];
      h.ethertype=PRISM_ETHERTYPE;h.version=8'h20;h.packet_class=PACKET_CLASS;
      h.packet_id=planner_packet_ids[bank*32+:32];h.first_element=planner_first_elements[bank*32+:32];
      h.element_count=planner_frame_elements[bank*16+:16];h.group_count=planner_frame_groups[bank*8+:8];
      h.flags={7'd0,planner_frame_last[bank]};h.body_bytes=planner_frame_bytes[bank*16+:16];h.reserved=0;
      network_order={h.destination_mac,h.source_mac,h.ethertype,h.version,h.packet_class,h.key.job_id,
          h.key.group_id,h.key.group_generation,h.key.operation_id,h.key.operation_generation,
          h.source_endpoint,h.destination_endpoint,h.packet_id,h.first_element,h.element_count,
          h.group_count,h.flags,h.body_bytes,h.stream_id,h.reserved};
      for(int i=0;i<56;i++)wire_headers[bank*448+i*8+:8]=network_order[(55-i)*8+:8];
    end
  end
  // Chunks wait in a short queue for the frame store, which holds them up
  // for single cycles. The queue is kept in slices like the window, each
  // written by the copy of the slicer next to it, and a registered step
  // follows it so that the store appends from registers. A chunk holds a
  // place from the cycle it leaves the slicer until it leaves the queue.
  localparam int unsigned CHUNK_W = 1+16+8+2+1536;
  localparam int unsigned CHUNK_SLICES = (CHUNK_W + SELECT_BITS - 1) / SELECT_BITS;
  localparam int unsigned CHUNK_DEPTH = 8;
  logic [CHUNK_W-1:0] chunk_word, chunk_word_held, queued_word;
  logic [CHUNK_SLICES-1:0] queued_valid, queue_ready;
  logic chunk_ready, chunk_pop;
  logic [$clog2(CHUNK_DEPTH+1)-1:0] chunks_queued, chunks_queued_next;
  assign chunk_word = {chunk_bank,chunk_offset,chunk_bytes,chunk_flush,chunk_window};
  // A chunk is registered once between the slicer and the queue, so the
  // queue memories are written from registers. The place it holds is
  // counted from the slicer on, so the queue needs no change.
  always_ff @(posedge clk) chunk_word_held <= chunk_word;
  for (genvar slice = 0; slice < CHUNK_SLICES; slice++) begin : gen_chunk_queue
    localparam int unsigned LOW = slice * SELECT_BITS;
    localparam int unsigned SIZE = (CHUNK_W - LOW) < SELECT_BITS ? CHUNK_W - LOW : SELECT_BITS;
    logic push, push_held;
    if (slice < WINDOW_COPIES) begin : beside_window
      assign push = chunk_window_valid[slice];
    end else begin : beside_plan
      assign push = chunk_valid;
    end
    always_ff @(posedge clk) begin
      if (!rst_n || context_reset) push_held <= 1'b0;
      else push_held <= push;
    end
    (* dont_touch = "true" *) prism_elastic_fifo #(
        .WIDTH(SIZE), .DEPTH(CHUNK_DEPTH), .READY_ON_POP(1'b0), .REGISTER_READY(1'b1)
    ) u_queue (
        .clk(clk), .rst_n(rst_n && !context_reset),
        .s_data(chunk_word_held[LOW +: SIZE]), .s_valid(push_held),
        .s_ready(queue_ready[slice]),
        .m_data(queued_word[LOW +: SIZE]), .m_valid(queued_valid[slice]), .m_ready(chunk_ready),
        .occupancy()
    );
    // synthesis translate_off
    always_ff @(posedge clk) begin
      if (rst_n && !context_reset) begin
        assert (push == chunk_valid);
        assert (!(push_held && !queue_ready[slice]));
      end
    end
    // synthesis translate_on
  end
  assign chunk_pop = queued_valid[0] && chunk_ready;
  always_comb begin
    chunks_queued_next = chunks_queued;
    case ({chunk_valid, chunk_pop})
      2'b10: chunks_queued_next = chunks_queued + 1'b1;
      2'b01: chunks_queued_next = chunks_queued - 1'b1;
      default: ;
    endcase
  end
  // The copies of the credit are one cycle behind this flag and two chunks
  // may have left on the way, so four places stay free when it falls.
  always_ff @(posedge clk) begin
    if (!rst_n || context_reset) begin
      chunks_queued <= '0;
      credit <= 1'b0;
    end else begin
      chunks_queued <= chunks_queued_next;
      credit <= int'(chunks_queued_next) <= CHUNK_DEPTH - 4;
    end
  end
  logic store_chunk_valid,store_chunk_ready,store_chunk_bank;
  logic [15:0] store_chunk_offset;
  logic [7:0] store_chunk_bytes;
  logic [1:0] store_chunk_flush;
  logic [1535:0] store_chunk_window;
  prism_elastic_skid_buffer #(.WIDTH(CHUNK_W)) u_chunk (
      .clk(clk),.rst_n(rst_n && !context_reset),
      .s_data(queued_word),
      .s_valid(queued_valid[0]),.s_ready(chunk_ready),
      .m_data({store_chunk_bank,store_chunk_offset,store_chunk_bytes,store_chunk_flush,
          store_chunk_window}),
      .m_valid(store_chunk_valid),.m_ready(store_chunk_ready)
  );
  prism_numbergroup_committed_store #(.MTU_BYTES(MTU_BYTES)) u_store (
      .clk(clk),.rst_n(rst_n),.s_reset(s_reset),.s_bank_busy(planner_bank_busy),
      .s_frame_valid(planner_frame_valid),.s_frame_ready(planner_frame_ready),.s_frame_header(wire_headers),
      .s_frame_packet_id(planner_packet_ids),.s_frame_body_bytes(planner_frame_bytes),.s_frame_last(planner_frame_last),
      .s_chunk_valid(store_chunk_valid),.s_chunk_ready(store_chunk_ready),.s_chunk_bank(store_chunk_bank),
      .s_chunk_offset(store_chunk_offset),.s_chunk_bytes(store_chunk_bytes),
      .s_chunk_flush(store_chunk_flush),.s_chunk_window(store_chunk_window),
      .s_patch_valid(planner_patch_valid),.s_patch_ready(planner_patch_ready),.s_patch_bank(planner_patch_bank),
      .s_patch_offset(planner_patch_offset),.s_patch_count(planner_patch_count),
      .m_axis_tdata(m_axis_tdata),.m_axis_tkeep(m_axis_tkeep),.m_axis_tvalid(m_axis_tvalid),
      .m_axis_tlast(m_axis_tlast),.m_axis_tready(m_axis_tready),.m_frame_bytes(m_frame_bytes),
      .m_packet_id(m_packet_id),.m_last_frame_done(m_last_frame_done),
      .m_release_valid(release_valid),.m_release_bank(release_bank),.m_fault(store_fault)
  );
endmodule
