//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_tile_encoder.sv
// Module: prism_numbergroup_tile_encoder
// Description: Encodes the lanes of a tile as NumberGroup byte segments.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Each lane becomes a short byte segment: its value, preceded by a group
// descriptor on the first lane of a run and followed by padding on the last.
// Native values need at most eight bytes per lane; Kulisch values travel on
// the sixteen low lanes with wider segments. The segments, their lengths and
// the size of the tile leave four cycles after the tile; the module never
// stalls, and s_user travels with the tile.
//
// A tile with a Kulisch value is encoded in two parts: its sixteen low
// lanes as wide segments, and the lanes above them, which are native, as
// native segments. The parts are compacted separately and the second
// follows the first in the frame. So that it can be joined to the first
// without a shift, the native part is preceded by as many empty bytes as
// the wide part has beyond a whole number of JOIN_BYTES: the unused native
// segments of the low lanes report those bytes as their length.
module prism_numbergroup_tile_encoder #(
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_KULISCH_BITS = 4096,
    parameter int unsigned LANES = 16,
    parameter int unsigned USER_W = 1,
    // The native part of a tile is joined to the wide part at a multiple of
    // this many bytes. The low lanes can report eight bytes each.
    parameter int unsigned JOIN_BYTES = 128,
    localparam int unsigned COUNT_W = $clog2(LANES + 1),
    localparam int unsigned WIDE_LANES = LANES < 16 ? LANES : 16,
    localparam int unsigned INTEGER_BYTES = (KULISCH_W + 7) / 8,
    localparam int unsigned SEGMENT_BYTES = INTEGER_BYTES + 8,
    localparam int unsigned NATIVE_SEGMENT_BYTES = 8,
    localparam int unsigned WIDE_LENGTH_W = $clog2(SEGMENT_BYTES + 1),
    localparam int unsigned JOIN_W = $clog2(WIDE_LANES * SEGMENT_BYTES / JOIN_BYTES + 1)
) (
    input  logic                                          clk,
    input  logic                                          rst_n,
    input  logic [15:0]                                   s_kulisch_bits,
    input  logic [COUNT_W-1:0]                            s_count,
    input  logic [LANES*8-1:0]                            s_formats,
    input  logic [LANES*32-1:0]                           s_native_bits,
    input  logic [LANES*8-1:0]                            s_tags,
    input  logic [LANES*KULISCH_W-1:0]                    s_integers,
    input  logic [USER_W-1:0]                             s_user,
    input  logic                                          s_valid,
    output logic                                          m_valid,
    output logic [USER_W-1:0]                             m_user,
    output logic [15:0]                                   m_kulisch_bits,
    output logic [15:0]                                   m_count,
    // Encoded size of the tile and number of groups it starts.
    output logic [15:0]                                   m_bytes,
    output logic [7:0]                                    m_groups,
    output logic [7:0]                                    m_format,
    output logic                                          m_uniform,
    // The last run of the tile ends with padding (used for uniform tiles).
    output logic                                          m_padded,
    output logic                                          m_encoding_valid,
    output logic                                          m_has_kulisch,
    // Whole multiples of JOIN_BYTES in the wide part of a tile with both parts.
    output logic [JOIN_W-1:0]                             m_join,
    // A Kulisch value wider than the datapath is sent alone from its own fields.
    output logic                                          m_extended_wire,
    output logic [7:0]                                    m_extension_tag,
    output logic [KULISCH_W-1:0]                          m_extension_integer,
    output logic [LANES*NATIVE_SEGMENT_BYTES*8-1:0]       m_native_data,
    output logic [LANES*4-1:0]                            m_native_lengths,
    output logic [WIDE_LANES*SEGMENT_BYTES*8-1:0]         m_wide_data,
    output logic [WIDE_LANES*WIDE_LENGTH_W-1:0]           m_wide_lengths
);

  import prism_pkg::*;

  localparam int unsigned RUN_STAGES = $clog2(LANES);

  localparam int unsigned JOIN_BITS = $clog2(JOIN_BYTES);
  // Whether a tile can have a native part after a wide one.
  localparam bit TWO_PARTS = LANES > WIDE_LANES;

  initial begin
    if (KULISCH_W < 278 || KULISCH_W > 320
        || MAX_KULISCH_BITS < 278 || MAX_KULISCH_BITS > 4096)
      $fatal(1, "tile encoder requires bounded SINGLE geometry");
    if (JOIN_BYTES != (1 << JOIN_BITS) || JOIN_BYTES > WIDE_LANES * NATIVE_SEGMENT_BYTES)
      $fatal(1, "tile encoder cannot report the join offset on its low lanes");
  end

  function automatic int unsigned width_for(
      input logic [7:0] format, input logic [15:0] wire_bits);
    case (format)
      PRISM_FORMAT_INT8: return 1;
      PRISM_FORMAT_FP16, PRISM_FORMAT_BF16: return 2;
      PRISM_FORMAT_FP32: return 4;
      // Every admitted width 278..280 occupies 35 integer bytes. Expose
      // the existing build bound instead of carrying a dynamic byte geometry.
      // Out-of-range contexts still fault before planner/frame admission.
      PRISM_FORMAT_KULISCH: return MAX_KULISCH_BITS <= 280
          ? 36 : 1 + (int'(wire_bits) + 7) / 8;
      default: return 0;
    endcase
  endfunction

  logic [3:0] valid;
  always_ff @(posedge clk) begin
    if (!rst_n) valid <= '0;
    else valid <= {valid[2:0], s_valid};
  end
  assign m_valid = valid[3];

  // Input step: the tile is registered as it arrives, so the sender may
  // present it straight from a memory.
  logic [COUNT_W-1:0] in_count;
  // Kept apart from the equal register of the tile source, which sits in
  // another part of the device.
  (* dont_touch = "true" *) logic [15:0] in_kulisch_bits;
  logic [LANES*8-1:0] in_formats;
  logic [LANES*32-1:0] in_native_bits;
  logic [WIDE_LANES*8-1:0] in_tags;
  logic [WIDE_LANES*KULISCH_W-1:0] in_integers;
  logic [USER_W-1:0] in_user;
  always_ff @(posedge clk) begin
    in_count <= s_count;
    in_kulisch_bits <= s_kulisch_bits;
    in_formats <= s_formats;
    in_native_bits <= s_native_bits;
    in_tags <= s_tags[0 +: WIDE_LANES*8];
    in_integers <= s_integers[0 +: WIDE_LANES*KULISCH_W];
    in_user <= s_user;
  end

  // ------------------------------------------------ step 1: runs and checks
  logic [(LANES+1)*8-1:0] formats_with_sentinel;
  logic [LANES-1:0] run_heads, kulisch_lanes;
  logic input_uniform, source_extended;
  logic [KULISCH_W-1:0] sign_extension_mask;
  assign formats_with_sentinel = {8'b0, in_formats};

  for (genvar lane = 0; lane < LANES; lane++) begin : run_boundary
    if (lane == 0) begin : first_lane
      assign run_heads[lane] = in_count != 0;
    end else begin : following_lane
      assign run_heads[lane] = lane < int'(in_count)
          && in_formats[lane*8 +: 8] != in_formats[(lane-1)*8 +: 8];
    end
    assign kulisch_lanes[lane] = lane < int'(in_count)
        && in_formats[lane*8 +: 8] == PRISM_FORMAT_KULISCH;
  end

  // Run boundaries use logarithmic-depth scans. End indices are ordered by
  // lane: a present left end precedes every right end, so validity selects
  // the suffix minimum without carry compares. The run start needs only its
  // position modulo four, which is all the padding depends on.
  for (genvar level = 0; level <= RUN_STAGES; level++) begin : run_scan
    logic [LANES*COUNT_W-1:0] ends;
    logic [LANES-1:0] has_end;
    logic [LANES*2-1:0] starts;
    logic [LANES-1:0] has_head;
    for (genvar lane = 0; lane < LANES; lane++) begin : at_lane
      if (level == 0) begin : boundary
        assign ends[lane*COUNT_W +: COUNT_W] = lane >= int'(in_count)
            ? COUNT_W'(LANES+1)
            : lane + 1 >= int'(in_count)
                || in_formats[lane*8 +: 8] != formats_with_sentinel[(lane+1)*8 +: 8]
            ? COUNT_W'(lane+1) : COUNT_W'(LANES+1);
        assign has_end[lane] = ends[lane*COUNT_W +: COUNT_W] != COUNT_W'(LANES+1);
        assign starts[lane*2 +: 2] = 2'(lane);
        if (lane == 0) begin : first_head
          assign has_head[lane] = 1'b1;
        end else begin : format_head
          assign has_head[lane] = in_formats[lane*8 +: 8] != in_formats[(lane-1)*8 +: 8];
        end
      end else begin : scan
        localparam int unsigned DISTANCE = 1 << (level-1);
        if (lane + DISTANCE < LANES) begin : right_neighbor
          assign ends[lane*COUNT_W +: COUNT_W] = run_scan[level-1].has_end[lane]
              ? run_scan[level-1].ends[lane*COUNT_W +: COUNT_W]
              : run_scan[level-1].ends[(lane+DISTANCE)*COUNT_W +: COUNT_W];
          assign has_end[lane] = run_scan[level-1].has_end[lane]
              || run_scan[level-1].has_end[(lane+DISTANCE)];
        end else begin : last_lanes
          assign ends[lane*COUNT_W +: COUNT_W] = run_scan[level-1].ends[lane*COUNT_W +: COUNT_W];
          assign has_end[lane] = run_scan[level-1].has_end[lane];
        end
        if (lane >= DISTANCE) begin : left_neighbor
          assign has_head[lane] = run_scan[level-1].has_head[lane]
              || run_scan[level-1].has_head[lane-DISTANCE];
          assign starts[lane*2 +: 2] = run_scan[level-1].has_head[lane]
              ? run_scan[level-1].starts[lane*2 +: 2]
              : run_scan[level-1].starts[(lane-DISTANCE)*2 +: 2];
        end else begin : first_lanes
          assign has_head[lane] = run_scan[level-1].has_head[lane];
          assign starts[lane*2 +: 2] = run_scan[level-1].starts[lane*2 +: 2];
        end
      end
    end
  end

  always_comb begin
    input_uniform = in_count != 0 && int'(in_count) <= LANES
        && int'(in_kulisch_bits) <= KULISCH_W;
    for (int lane = 1; lane < LANES; lane++)
      if (lane < int'(in_count)
          && in_formats[lane*8 +: 8] != in_formats[7:0]) input_uniform = 1'b0;
  end
  assign source_extended = MAX_KULISCH_BITS > KULISCH_W
      && int'(in_kulisch_bits) > KULISCH_W && in_formats[7:0] == PRISM_FORMAT_KULISCH;

  // A signed value fits the wire width exactly when every bit from its wire
  // sign bit upward equals the stored sign. The mask is shared by the lanes.
  // The mask depends only on the wire width of the operation, so it is
  // registered with the tile instead of being decoded in front of the check.
  always_ff @(posedge clk) begin
    for (int bit_index = 0; bit_index < KULISCH_W; bit_index++)
      sign_extension_mask[bit_index] <= bit_index + 1 >= int'(s_kulisch_bits);
  end
  // The check of an exact value looks at all of its bits twice: whether the
  // value is zero, and whether the bits above the wire width repeat the sign.
  // Both are taken in two steps: here one flag per group of bits, registered,
  // and the verdict of the lane in the next step.
  localparam int unsigned CHECK_GROUPS = 8;
  localparam int unsigned CHECK_BITS = (KULISCH_W + CHECK_GROUPS - 1) / CHECK_GROUPS;
  logic [WIDE_LANES*CHECK_GROUPS-1:0] value_groups, excess_groups;
  logic [WIDE_LANES-1:0] exact_lane;
  logic [LANES-1:0] native_valid;
  for (genvar lane = 0; lane < LANES; lane++) begin : validate_lane
    logic [7:0] format;
    logic [31:0] native_bits;
    assign format = in_formats[lane*8 +: 8];
    assign native_bits = in_native_bits[lane*32 +: 32];
    always_comb begin
      case (format)
        PRISM_FORMAT_INT8: native_valid[lane] = native_bits[31:8] == 0;
        PRISM_FORMAT_FP16, PRISM_FORMAT_BF16: native_valid[lane] = native_bits[31:16] == 0;
        PRISM_FORMAT_FP32: native_valid[lane] = 1'b1;
        default: native_valid[lane] = 1'b0;
      endcase
    end
    if (lane < WIDE_LANES) begin : wide_lane
      logic [KULISCH_W-1:0] integer_bits, excess_sign_bits;
      assign integer_bits = in_integers[lane*KULISCH_W +: KULISCH_W];
      assign excess_sign_bits = (integer_bits ^ {KULISCH_W{integer_bits[KULISCH_W-1]}})
          & sign_extension_mask;
      assign exact_lane[lane] = format == PRISM_FORMAT_KULISCH;
      for (genvar group = 0; group < CHECK_GROUPS; group++) begin : check_group
        localparam int unsigned LOW = group * CHECK_BITS;
        localparam int unsigned SIZE = LOW + CHECK_BITS <= KULISCH_W
            ? CHECK_BITS : KULISCH_W - LOW;
        assign value_groups[lane*CHECK_GROUPS + group] = |integer_bits[LOW +: SIZE];
        assign excess_groups[lane*CHECK_GROUPS + group] = |excess_sign_bits[LOW +: SIZE];
      end
    end
  end

  logic [COUNT_W-1:0] count_1;
  logic [15:0] kulisch_bits_1;
  logic [LANES*8-1:0] formats_1;
  logic [LANES*32-1:0] native_1;
  logic [WIDE_LANES*8-1:0] tags_1;
  logic [WIDE_LANES*KULISCH_W-1:0] integers_1;
  logic [LANES*COUNT_W-1:0] ends_1;
  logic [LANES*2-1:0] starts_1;
  logic [LANES-1:0] heads_1, lane_valid_1, native_valid_1;
  logic [WIDE_LANES*CHECK_GROUPS-1:0] value_groups_1, excess_groups_1;
  logic [WIDE_LANES-1:0] exact_lane_1;
  logic bits_fit_1, bits_none_1;
  // Per lane: the lane holds a value, and it holds the last value of the
  // tile. Each lane reads its own flags instead of comparing the count.
  logic [LANES-1:0] present_1, final_1;
  logic has_kulisch_1, uniform_1, extended_1;
  logic [USER_W-1:0] user_1, user_2;
  always_ff @(posedge clk) begin
    count_1 <= in_count;
    kulisch_bits_1 <= in_kulisch_bits;
    formats_1 <= in_formats;
    native_1 <= in_native_bits;
    tags_1 <= in_tags[0 +: WIDE_LANES*8];
    integers_1 <= in_integers[0 +: WIDE_LANES*KULISCH_W];
    ends_1 <= run_scan[RUN_STAGES].ends;
    starts_1 <= run_scan[RUN_STAGES].starts;
    heads_1 <= run_heads;
    for (int lane = 0; lane < LANES; lane++) begin
      present_1[lane] <= lane < int'(in_count);
      final_1[lane] <= lane + 1 == int'(in_count);
    end
    native_valid_1 <= native_valid;
    value_groups_1 <= value_groups;
    excess_groups_1 <= excess_groups;
    exact_lane_1 <= exact_lane;
    bits_fit_1 <= int'(in_kulisch_bits) <= KULISCH_W;
    bits_none_1 <= in_kulisch_bits == 0;
    has_kulisch_1 <= |kulisch_lanes;
    uniform_1 <= input_uniform;
    extended_1 <= source_extended;
    user_1 <= in_user;
  end

  // ------------------------------------------------------ step 2: segments
  logic [(LANES+1)*8-1:0] formats_1_with_sentinel;
  logic [LANES*NATIVE_SEGMENT_BYTES*8-1:0] native_segments, native_data_2;
  logic [LANES*4-1:0] native_lengths, native_lengths_2;
  logic [WIDE_LANES*SEGMENT_BYTES*8-1:0] wide_segments, wide_data_2;
  logic [WIDE_LANES*16-1:0] wide_lengths, wide_lengths_2;
  logic [7:0] groups, groups_2, format_2, tag_2;
  logic encoding_valid, encoding_valid_2, has_kulisch_2, uniform_2, extended_2, padded_2;
  logic [15:0] extension_bytes, extension_bytes_2, kulisch_bits_2, count_2;
  logic [KULISCH_W-1:0] integer_2;
  assign formats_1_with_sentinel = {8'b0, formats_1};

  // A native lane needs at most eight bytes including descriptor and padding.
  // The low lanes of a tile with a Kulisch value travel as wide segments.
  for (genvar lane = 0; lane < LANES; lane++) begin : native_lane
    logic [7:0] format;
    logic [2:0] width;
    logic [1:0] count_mod, padding;
    logic [3:0] length;
    logic [31:0] payload;
    logic [63:0] segment;
    logic [15:0] run_count;
    assign format = formats_1[lane*8 +: 8];
    assign count_mod = 2'(lane+1) - starts_1[lane*2 +: 2];
    assign run_count = 16'(ends_1[lane*COUNT_W +: COUNT_W] - COUNT_W'(lane));
    always_comb begin
      width = '0;
      payload = '0;
      case (format)
        PRISM_FORMAT_INT8: begin
          width = 3'd1;
          payload[7:0] = native_1[lane*32 +: 8];
        end
        PRISM_FORMAT_FP16, PRISM_FORMAT_BF16: begin
          width = 3'd2;
          payload[15:0] = native_1[lane*32 +: 16];
        end
        PRISM_FORMAT_FP32: begin
          width = 3'd4;
          payload = native_1[lane*32 +: 32];
        end
        default: begin end
      endcase
      segment = '0;
      length = '0;
      padding = '0;
      if (present_1[lane] && width != 0 && !(lane < WIDE_LANES && has_kulisch_1)) begin
        if (final_1[lane]
            || formats_1_with_sentinel[(lane+1)*8 +: 8] != format)
          padding = 2'b00 - count_mod*2'(width);
        length = 4'(width) + 4'(padding);
        if (heads_1[lane]) begin
          segment = {payload, 32'b0};
          segment[7:0] = format;
          segment[23:16] = run_count[15:8];
          segment[31:24] = run_count[7:0];
          length += 4'd4;
        end else segment = {32'b0, payload};
      end
    end
    assign native_segments[lane*NATIVE_SEGMENT_BYTES*8 +: NATIVE_SEGMENT_BYTES*8] = segment;
    assign native_lengths[lane*4 +: 4] = length;
  end

  // Wide lanes carry any format: a run of native values next to Kulisch
  // values stays in lane order. A run that continues on the native lanes
  // above is counted whole by its descriptor and closed there.
  for (genvar lane = 0; lane < WIDE_LANES; lane++) begin : wide_lane
    logic [7:0] format, tag;
    logic [31:0] native_bits;
    logic [KULISCH_W-1:0] integer_bits;
    logic [1:0] count_mod, run_padding;
    logic [15:0] run_count;
    logic descriptor, run_closes;
    logic [SEGMENT_BYTES*8-1:0] value_segment, segment;
    logic [15:0] length;
    assign format = formats_1[lane*8 +: 8];
    assign tag = tags_1[lane*8 +: 8];
    assign native_bits = native_1[lane*32 +: 32];
    assign integer_bits = integers_1[lane*KULISCH_W +: KULISCH_W];
    assign count_mod = 2'(lane+1) - starts_1[lane*2 +: 2];
    assign run_padding = 2'b00 - count_mod*2'(width_for(format, kulisch_bits_1));
    assign run_count = 16'(ends_1[lane*COUNT_W +: COUNT_W] - COUNT_W'(lane));
    if (lane == 0) begin : first_descriptor
      assign descriptor = 1'b1;
    end else begin : run_descriptor
      assign descriptor = format != formats_1[(lane-1)*8 +: 8];
    end
    assign run_closes = final_1[lane]
        || formats_1_with_sentinel[(lane+1)*8 +: 8] != format;
    always_comb begin
      int unsigned width;
      width = width_for(format, kulisch_bits_1);
      value_segment = '0;
      for (int byte_index = 0; byte_index < INTEGER_BYTES + 1; byte_index++) begin
        if (byte_index < int'(width)) begin
          if (format == PRISM_FORMAT_KULISCH)
            value_segment[byte_index*8 +: 8] = byte_index == 0
                ? tag : 8'(integer_bits >> ((byte_index-1)*8));
          else value_segment[byte_index*8 +: 8] = 8'(native_bits >> (byte_index*8));
        end
      end
      segment = '0;
      length = '0;
      if (present_1[lane] && !extended_1) begin
        if (descriptor) begin
          segment = value_segment << 32;
          segment[0 +: 8] = format;
          segment[8 +: 8] = 8'd0;
          segment[16 +: 8] = run_count[15:8];
          segment[24 +: 8] = run_count[7:0];
        end else segment = value_segment;
        length = 16'((descriptor ? 4 : 0) + width + (run_closes ? int'(run_padding) : 0));
      end
    end
    assign wide_segments[lane*SEGMENT_BYTES*8 +: SEGMENT_BYTES*8] = segment;
    assign wide_lengths[lane*16 +: 16] = length;
  end

  // The verdict of every lane: a lane without a value passes, a native value
  // must fit its format, and an exact value must fit the wire width with a
  // tag that agrees with it.
  for (genvar lane = 0; lane < LANES; lane++) begin : lane_verdict
    if (lane < WIDE_LANES) begin : wide_lane
      logic [7:0] tag;
      logic nonzero, exact_valid;
      assign tag = tags_1[lane*8 +: 8];
      assign nonzero = |value_groups_1[lane*CHECK_GROUPS +: CHECK_GROUPS];
      assign exact_valid = bits_fit_1 && tag <= 8'd5 && ((tag == 0) == nonzero)
          && (bits_none_1 || !(|excess_groups_1[lane*CHECK_GROUPS +: CHECK_GROUPS]));
      assign lane_valid_1[lane] = !present_1[lane]
          || (exact_lane_1[lane] ? exact_valid : native_valid_1[lane]);
    end else begin : native_only_lane
      assign lane_valid_1[lane] = !present_1[lane] || native_valid_1[lane];
    end
  end

  always_comb begin
    groups = 8'($countones(heads_1));
    encoding_valid = count_1 != 0 && int'(count_1) <= LANES && (&lane_valid_1);
    extension_bytes = '0;
    if (extended_1) begin
      groups = 8'd1;
      encoding_valid = count_1 == COUNT_W'(1)
          && kulisch_bits_1 <= 16'(MAX_KULISCH_BITS)
          && tags_1[7:0] <= 8'd5
          && ((tags_1[7:0] == 0) == (integers_1[0 +: KULISCH_W] != 0))
          && (tags_1[7:0] == 0 || integers_1[0 +: KULISCH_W] == 0);
      extension_bytes
          = 16'((4 + width_for(PRISM_FORMAT_KULISCH, kulisch_bits_1) + 3) & ~3);
    end
  end

  always_ff @(posedge clk) begin
    native_data_2 <= native_segments;
    native_lengths_2 <= native_lengths;
    wide_data_2 <= wide_segments;
    wide_lengths_2 <= wide_lengths;
    groups_2 <= groups;
    encoding_valid_2 <= encoding_valid;
    extension_bytes_2 <= extension_bytes;
    has_kulisch_2 <= has_kulisch_1;
    uniform_2 <= uniform_1;
    padded_2 <= 2'(count_1) * 2'(width_for(formats_1[7:0], kulisch_bits_1)) != 2'd0;
    extended_2 <= extended_1;
    kulisch_bits_2 <= kulisch_bits_1;
    count_2 <= 16'(count_1);
    format_2 <= formats_1[7:0];
    tag_2 <= tags_1[7:0];
    integer_2 <= integers_1[0 +: KULISCH_W];
    user_2 <= user_1;
  end

  // ---------------------------------------------------------- step 3: size
  // The tile is its native part, preceded by its wide part when it has a
  // Kulisch value.
  logic [(LANES+WIDE_LANES)*16-1:0] sizes;
  logic [15:0] tile_bytes, wide_bytes;
  logic [WIDE_LANES*4-1:0] join_lengths;
  for (genvar lane = 0; lane < LANES; lane++) begin : native_size
    assign sizes[lane*16 +: 16] = {12'b0, native_lengths_2[lane*4 +: 4]};
  end
  for (genvar lane = 0; lane < WIDE_LANES; lane++) begin : wide_size
    assign sizes[(LANES+lane)*16 +: 16] = has_kulisch_2 ? wide_lengths_2[lane*16 +: 16] : 16'd0;
  end
  prism_numbergroup_size_sum #(.INPUTS(LANES + WIDE_LANES)) u_tile_bytes (
      .s_values(sizes), .m_sum(tile_bytes)
  );
  prism_numbergroup_size_sum #(.INPUTS(WIDE_LANES)) u_wide_bytes (
      .s_values(wide_lengths_2), .m_sum(wide_bytes)
  );
  // The bytes of the wide part beyond whole multiples of JOIN_BYTES, spread
  // over the unused native segments of the low lanes, eight bytes each.
  for (genvar lane = 0; lane < WIDE_LANES; lane++) begin : join_length
    logic [JOIN_BITS-1:0] offset;
    assign offset = wide_bytes[0 +: JOIN_BITS];
    assign join_lengths[lane*4 +: 4] = !(TWO_PARTS && has_kulisch_2 && !extended_2) ? 4'd0
        : int'(offset) >= 8 * (lane + 1) ? 4'd8
        : int'(offset) > 8 * lane ? 4'(offset - JOIN_BITS'(8 * lane)) : 4'd0;
  end
  always_ff @(posedge clk) begin
    m_user <= user_2;
    m_kulisch_bits <= kulisch_bits_2;
    m_count <= count_2;
    m_bytes <= extended_2 ? extension_bytes_2 : tile_bytes;
    m_join <= TWO_PARTS && has_kulisch_2 && !extended_2
        ? JOIN_W'(wide_bytes >> JOIN_BITS) : '0;
    m_groups <= groups_2;
    m_format <= format_2;
    m_uniform <= uniform_2;
    m_padded <= padded_2;
    m_encoding_valid <= encoding_valid_2;
    m_has_kulisch <= has_kulisch_2;
    m_extended_wire <= extended_2;
    m_extension_tag <= tag_2;
    m_extension_integer <= integer_2;
    m_native_data <= native_data_2;
    m_native_lengths <= native_lengths_2;
    if (has_kulisch_2) m_native_lengths[0 +: WIDE_LANES*4] <= join_lengths;
    m_wide_data <= wide_data_2;
    for (int lane = 0; lane < WIDE_LANES; lane++)
      m_wide_lengths[lane*WIDE_LENGTH_W +: WIDE_LENGTH_W]
          <= wide_lengths_2[lane*16 +: WIDE_LENGTH_W];
  end

endmodule
