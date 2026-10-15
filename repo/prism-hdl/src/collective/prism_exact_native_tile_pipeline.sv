//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_exact_native_tile_pipeline.sv
// Module: prism_exact_native_tile_pipeline
// Description: Banked exact native tiles with one tile per cycle issue capacity.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_exact_native_tile_pipeline #(
    parameter int unsigned LANES = 16,
    parameter int unsigned RANGES = 256,
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_ORIGINAL_TERMS = 16,
    parameter int unsigned SLOT_W = $clog2(RANGES),
    parameter int unsigned STRIPE_BITS = 0,
    parameter int unsigned STRIPE_INDEX = 0
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic [SLOT_W-1:0]            s_slot,
    input  logic [31:0]                  s_first_element,
    input  logic [7:0]                   s_format,
    input  logic [511:0]                 s_element_bits,
    input  logic [LANES-1:0]             s_element_keep,
    input  logic                         s_valid,
    output logic                         s_ready,
    input  logic                         s_release,
    output logic                         s_release_ready,
    // Reading the results. A request is announced with s_result_read_arm,
    // at the latest in the cycle it is offered; from the next cycle on no
    // tile is taken until the release. A request is granted when the stages
    // are empty, and its result is valid for one cycle, two cycles after the
    // grant: the consumer has a place for every result it asks for.
    input  logic [SLOT_W-1:0]            s_result_slot,
    input  logic                         s_result_read_arm,
    input  logic                         s_result_read_valid,
    output logic                         s_result_read_ready,
    output logic [SLOT_W-1:0]            m_result_slot,
    output logic [LANES-1:0]             m_result_present,
    output logic [LANES*8-1:0]           m_result_tags,
    output logic [LANES*KULISCH_W-1:0]   m_result_integers,
    output logic                         m_result_valid,
    output logic [31:0]                  m_first_element,
    output logic [LANES-1:0]             m_element_keep,
    output logic [LANES*8-1:0]           m_kulisch_tags,
    output logic [LANES*KULISCH_W-1:0]   m_kulisch_integers,
    output logic [LANES*2-1:0]           m_errors,
    output logic                         m_valid,
    input  logic                         m_ready
);

  import prism_pkg::*;

  localparam int unsigned HALF_W = KULISCH_W / 2;
  logic advance, hazard, format_valid, accept, read_request;
  logic [SLOT_W-1:0] read_slot;
  logic reading, quiet, clear_present;
  // The bank takes tiles while it neither reads results nor clears. Both
  // conditions change rarely and serve many places in the bank; the ready
  // of the tiles uses this one flag of its own instead.
  (* dont_touch = "true" *) logic accepting;
  // What a granted request has fetched beside the memory.
  logic fetched_valid;
  logic [SLOT_W-1:0] fetched_slot;
  logic [LANES-1:0] fetched_present;
  logic [LANES*8-1:0] fetched_tags;
  // Stage 0 holds the wire tile, stage C its FP32 form with the stored tag
  // and presence, stage 1 the two operands, stage 2 the low half of the sum
  // and stage 3 the result.
  logic stage0_valid, stagec_valid, stage1_valid, stage2_valid, stage3_valid;
  logic [SLOT_W-1:0] stage0_slot, stagec_slot, stage1_slot, stage2_slot;
  logic [31:0] stage0_first, stagec_first, stage1_first, stage2_first, stage3_first;
  logic [7:0] stage0_format;
  logic [511:0] stage0_bits;
  logic [LANES-1:0] stage0_keep, stagec_keep, stage1_keep, stage2_keep, stage3_keep;
  logic [RANGES-1:0] present [0:LANES-1];
  logic [LANES-1:0] stagec_present, stage1_present, stage2_present;
  logic [31:0] stagec_native [0:LANES-1];
  logic [7:0] stagec_tag [0:LANES-1];
  logic [7:0] stage1_left_tag [0:LANES-1];
  logic [7:0] stage1_right_tag [0:LANES-1];
  logic [1:0] stage1_error [0:LANES-1];
  logic signed [KULISCH_W-1:0] ram_value [0:LANES-1];
  logic signed [KULISCH_W-1:0] stage1_left [0:LANES-1];
  logic signed [KULISCH_W-1:0] stage1_right [0:LANES-1];
  logic stage1_negate [0:LANES-1];
  // Sum stage: the complete sum is registered before the tag, the overflow
  // check and the memory write are derived from it.
  logic sum_valid;
  logic [SLOT_W-1:0] sum_slot;
  logic [31:0] sum_first;
  logic [LANES-1:0] sum_keep, sum_present, sum_overflow;
  // Whether each half of the sum is zero, found beside the adder: the
  // low half is already registered, and the high half is zero exactly
  // when every bit of the operands' XOR equals the carry that an all-zero
  // sum would produce below it, which is their OR one bit lower.
  logic [LANES-1:0] sum_low_zero, sum_high_zero;
  logic [KULISCH_W-1:0] sum_integer [0:LANES-1];
  logic [7:0] sum_left_tag [0:LANES-1];
  logic [7:0] sum_right_tag [0:LANES-1];
  logic [1:0] sum_error [0:LANES-1];
  logic [HALF_W-1:0] stage2_low [0:LANES-1];
  logic [HALF_W-1:0] stage2_left_high [0:LANES-1];
  logic [HALF_W-1:0] stage2_right_high [0:LANES-1];
  logic [LANES-1:0] stage2_carry;
  logic [7:0] stage2_left_tag [0:LANES-1];
  logic [7:0] stage2_right_tag [0:LANES-1];
  logic [1:0] stage2_error [0:LANES-1];
  logic [KULISCH_W-1:0] result_integer [0:LANES-1];
  logic [7:0] result_tag [0:LANES-1];
  logic [1:0] result_error [0:LANES-1];
  logic [LANES-1:0] result_write;
  logic [LANES*KULISCH_W-1:0] stage3_integers;
  logic [LANES*8-1:0] stage3_tags;
  logic [LANES*2-1:0] stage3_errors;

  function automatic logic [7:0] native_tag(
      input logic zero_value,
      input logic negative_zero,
      input logic nan_value,
      input logic positive_inf,
      input logic negative_inf
  );
    if (nan_value) return 8'd1;
    if (positive_inf) return 8'd2;
    if (negative_inf) return 8'd3;
    if (zero_value) return negative_zero ? 8'd5 : 8'd4;
    return 8'd0;
  endfunction

  function automatic logic [7:0] combined_tag(
      input logic [7:0] left_tag,
      input logic [7:0] right_tag,
      input logic nonzero_sum
  );
    if (left_tag == 8'd1 || right_tag == 8'd1
        || ((left_tag == 8'd2 || right_tag == 8'd2)
            && (left_tag == 8'd3 || right_tag == 8'd3))) return 8'd1;
    if (left_tag == 8'd2 || right_tag == 8'd2) return 8'd2;
    if (left_tag == 8'd3 || right_tag == 8'd3) return 8'd3;
    if (nonzero_sum) return 8'd0;
    return (left_tag == 8'd5 && right_tag == 8'd5) ? 8'd5 : 8'd4;
  endfunction

  initial begin
    if (LANES != 16 || RANGES < 2 || (RANGES & (RANGES - 1)) != 0
        || SLOT_W != $clog2(RANGES) || STRIPE_BITS > 3
        || STRIPE_INDEX >= (1 << STRIPE_BITS) || KULISCH_W < 278
        || KULISCH_W > 320 || (KULISCH_W & 1) != 0
        || MAX_ORIGINAL_TERMS < 1 || MAX_ORIGINAL_TERMS > 65535
        || KULISCH_W < 278 + $clog2(MAX_ORIGINAL_TERMS))
      $fatal(1, "Exact tile pipeline parameters exceed local RAM or term bounds");
  end

  assign advance = !stage3_valid || m_ready;
  // A tile reads its slot one cycle after it is accepted, and a slot is
  // written when its tile leaves the sum stage. A slot still in stage 0, C,
  // 1 or 2 would therefore be read before its update lands.
  assign hazard = (stage0_valid && s_slot == stage0_slot)
      || (stagec_valid && s_slot == stagec_slot)
      || (stage1_valid && s_slot == stage1_slot)
      || (stage2_valid && s_slot == stage2_slot);
  assign format_valid = s_format inside {
      PRISM_FORMAT_INT8, PRISM_FORMAT_FP16,
      PRISM_FORMAT_BF16, PRISM_FORMAT_FP32};
  // The release is not part of either ready: it clears the bank only when
  // no tile and no read is on offer, and a tile or read offered beside a
  // release that does not clear would be taken in the next cycle anyway.
  assign s_ready = advance && accepting
      && !hazard && format_valid
      && (|s_element_keep) && s_first_element[3:0] == 0
      && s_first_element == ((32'(s_slot) << (4 + STRIPE_BITS))
          | (32'(STRIPE_INDEX) << 4));
  assign accept = s_valid && s_ready;
  assign quiet = !stage0_valid && !stagec_valid && !stage1_valid
      && !stage2_valid && !sum_valid && !stage3_valid;
  assign s_result_read_ready = reading && quiet && !clear_present;
  assign read_request = s_result_read_valid && s_result_read_ready;
  // The accumulation read uses the registered slot of stage 0, so neither
  // input handshake reaches the memory address. During a stall the slot of
  // stage C is read again, which keeps the memory output aligned with it.
  // While results are read the address is the slot of the request, whether
  // or not one is granted.
  assign read_slot = reading ? s_result_slot
      : advance ? stage0_slot : stagec_slot;
  assign s_release_ready = quiet && !s_valid && !fetched_valid && !m_result_valid
      && !s_result_read_valid && !s_result_read_arm;
  assign m_first_element = stage3_first;
  assign m_element_keep = stage3_keep;
  assign m_kulisch_tags = stage3_tags;
  assign m_kulisch_integers = stage3_integers;
  assign m_errors = stage3_errors;
  assign m_valid = stage3_valid;

  for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
    logic [31:0] int8_fp32, fp16_fp32, bf16_fp32, fp32_bits;
    logic [31:0] native_bits;
    logic [KULISCH_W-1:0] deposit_magnitude;
    logic deposit_negate;
    logic finite, zero_value, zero_sign, nan_value;
    logic positive_inf, negative_inf, overflow, format_error;
    logic [HALF_W:0] low_sum, high_sum;
    logic [KULISCH_W-1:0] summed_integer;
    logic [7:0] merged_tag;
    // Stored tags live in a lane-local memory. Presence stays in registers
    // because a release clears every slot at once.
    logic [7:0] tags [0:RANGES-1];

    prism_int8_to_fp32 u_int8 (
        .input_bits(stage0_bits[lane*8 +: 8]), .output_bits(int8_fp32));
    prism_fp16_to_fp32 u_fp16 (
        .input_bits(stage0_bits[lane*16 +: 16]), .output_bits(fp16_fp32));
    prism_bf16_to_fp32 u_bf16 (
        .input_bits(stage0_bits[lane*16 +: 16]), .output_bits(bf16_fp32));
    prism_fp32_canonicalize u_fp32 (
        .input_bits(stage0_bits[lane*32 +: 32]), .output_bits(fp32_bits));
    always_comb begin
      case (stage0_format)
        PRISM_FORMAT_INT8: native_bits = int8_fp32;
        PRISM_FORMAT_FP16: native_bits = fp16_fp32;
        PRISM_FORMAT_BF16: native_bits = bf16_fp32;
        PRISM_FORMAT_FP32: native_bits = fp32_bits;
        default: native_bits = '0;
      endcase
    end
    prism_float_to_kulisch #(.ACC_W(KULISCH_W)) u_convert (
        .input_bits(stagec_native[lane]), .input_format(PRISM_FORMAT_FP32),
        .deposit(), .magnitude_bits(deposit_magnitude), .negate(deposit_negate),
        .finite(finite), .zero(zero_value),
        .zero_sign(zero_sign), .nan(nan_value),
        .positive_infinity(positive_inf),
        .negative_infinity(negative_inf), .overflow(overflow),
        .format_error(format_error)
    );
    wire unused_finite = finite;

    // A negative deposit arrives as its magnitude: the adder subtracts it
    // (inverted operand, carry in), so the conversion needs no negation of
    // its own in front of the operand register.
    assign low_sum = {1'b0, stage1_left[lane][HALF_W-1:0]}
        + {1'b0, stage1_right[lane][HALF_W-1:0] ^ {HALF_W{stage1_negate[lane]}}}
        + {{HALF_W{1'b0}}, stage1_negate[lane]};
    assign high_sum = {stage2_left_high[lane][HALF_W-1],
        stage2_left_high[lane]}
        + {stage2_right_high[lane][HALF_W-1],
            stage2_right_high[lane]}
        + {{HALF_W{1'b0}}, stage2_carry[lane]};
    assign summed_integer = sum_integer[lane];
    assign merged_tag = sum_present[lane]
        ? combined_tag(sum_left_tag[lane], sum_right_tag[lane],
            !(sum_low_zero[lane] && sum_high_zero[lane]))
        : sum_right_tag[lane];
    assign result_tag[lane] = merged_tag;
    assign result_integer[lane] = merged_tag == 0 ? summed_integer : '0;
    assign result_error[lane] = sum_error[lane] != 0
        ? sum_error[lane]
        : sum_overflow[lane] ? 2'd2 : 2'd0;
    assign result_write[lane] = advance && sum_valid && sum_keep[lane]
        && result_error[lane] == 0;

    prism_sync_ram_1w1r #(
        .WIDTH(KULISCH_W), .DEPTH(RANGES), .ADDR_W(SLOT_W), .BLOCK_RAM(1'b1)
    ) u_ram (
        .clk(clk),
        .write_enable(result_write[lane]),
        .write_address(sum_slot), .write_data(result_integer[lane]),
        .read_address(read_slot), .read_data(ram_value[lane])
    );

    always_ff @(posedge clk) begin
      if (!rst_n) present[lane] <= '0;
      else begin
        if (clear_present) present[lane] <= '0;
        if (result_write[lane]) present[lane][sum_slot] <= 1'b1;
      end
    end

    // The stage registers carry data only; the valid flags qualify them.
    always_ff @(posedge clk) begin
      if (result_write[lane]) tags[sum_slot] <= result_tag[lane];
      // The valid flags say which of these belong to a request.
      fetched_present[lane] <= present[lane][s_result_slot];
      fetched_tags[lane*8 +: 8] <= tags[s_result_slot];
      m_result_present[lane] <= fetched_present[lane];
      m_result_tags[lane*8 +: 8] <= fetched_tags[lane*8 +: 8];
      m_result_integers[lane*KULISCH_W +: KULISCH_W] <= ram_value[lane];
      if (advance) begin
        stagec_native[lane] <= native_bits;
        stagec_present[lane] <= present[lane][stage0_slot];
        stagec_tag[lane] <= tags[stage0_slot];
        stage1_present[lane] <= stagec_present[lane];
        stage1_left_tag[lane] <= stagec_tag[lane];
        stage1_right_tag[lane] <= native_tag(zero_value, zero_sign,
            nan_value, positive_inf, negative_inf);
        stage1_left[lane] <= stagec_present[lane] ? ram_value[lane] : '0;
        stage1_right[lane] <= deposit_magnitude;
        stage1_negate[lane] <= deposit_negate;
        stage1_error[lane] <= overflow || format_error ? 2'd2 : 2'd0;
        stage2_low[lane] <= low_sum[HALF_W-1:0];
        stage2_carry[lane] <= low_sum[HALF_W];
        stage2_left_high[lane] <= stage1_left[lane][KULISCH_W-1:HALF_W];
        stage2_right_high[lane] <= stage1_right[lane][KULISCH_W-1:HALF_W]
            ^ {(KULISCH_W-HALF_W){stage1_negate[lane]}};
        stage2_present[lane] <= stage1_present[lane];
        stage2_left_tag[lane] <= stage1_left_tag[lane];
        stage2_right_tag[lane] <= stage1_right_tag[lane];
        stage2_error[lane] <= stage1_error[lane];
        sum_integer[lane] <= {high_sum[HALF_W-1:0], stage2_low[lane]};
        sum_overflow[lane] <= high_sum[HALF_W] != high_sum[HALF_W-1];
        sum_low_zero[lane] <= stage2_low[lane] == '0;
        sum_high_zero[lane] <= (stage2_left_high[lane] ^ stage2_right_high[lane])
            == {stage2_left_high[lane][HALF_W-2:0] | stage2_right_high[lane][HALF_W-2:0],
                stage2_carry[lane]};
        sum_left_tag[lane] <= stage2_left_tag[lane];
        sum_right_tag[lane] <= stage2_right_tag[lane];
        sum_present[lane] <= stage2_present[lane];
        sum_error[lane] <= stage2_error[lane];
        stage3_integers[lane*KULISCH_W +: KULISCH_W]
            <= result_integer[lane];
        stage3_tags[lane*8 +: 8] <= result_tag[lane];
        stage3_errors[lane*2 +: 2] <= result_error[lane];
      end
    end
  end

  always_ff @(posedge clk) begin
    if (advance) begin
      if (accept) begin
        stage0_slot <= s_slot;
        stage0_first <= s_first_element;
        stage0_format <= s_format;
        stage0_bits <= s_element_bits;
        stage0_keep <= s_element_keep;
      end
      stagec_slot <= stage0_slot;
      stage1_slot <= stagec_slot;
      stage2_slot <= stage1_slot;
      sum_slot <= stage2_slot;
      stagec_first <= stage0_first;
      stage1_first <= stagec_first;
      stage2_first <= stage1_first;
      sum_first <= stage2_first;
      stage3_first <= sum_first;
      stagec_keep <= stage0_keep;
      stage1_keep <= stagec_keep;
      stage2_keep <= stage1_keep;
      sum_keep <= stage2_keep;
      stage3_keep <= sum_keep;
    end
    fetched_slot <= s_result_slot;
    m_result_slot <= fetched_slot;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      stage0_valid <= 1'b0;
      stagec_valid <= 1'b0;
      stage1_valid <= 1'b0;
      stage2_valid <= 1'b0;
      sum_valid <= 1'b0;
      stage3_valid <= 1'b0;
      reading <= 1'b0;
      clear_present <= 1'b0;
      accepting <= 1'b1;
      fetched_valid <= 1'b0;
      m_result_valid <= 1'b0;
    end else begin
      fetched_valid <= read_request;
      m_result_valid <= fetched_valid;
      if (s_release && s_release_ready) reading <= 1'b0;
      else if (s_result_read_arm) reading <= 1'b1;
      // Presence is cleared one cycle after the release, from a local flag.
      clear_present <= s_release && s_release_ready;
      // After a release the bank clears for one cycle and reads no more;
      // otherwise it stops taking tiles when the readout is armed.
      accepting <= !(s_release && s_release_ready) && !s_result_read_arm && !reading;
      if (advance) begin
        stage0_valid <= accept;
        stagec_valid <= stage0_valid;
        stage1_valid <= stagec_valid;
        stage2_valid <= stage1_valid;
        sum_valid <= stage2_valid;
        stage3_valid <= sum_valid;
      end
    end
  end

endmodule
