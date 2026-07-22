//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_range_scheduler.sv
// Module: prism_range_scheduler
// Description: Tracks contributor completion and reduces global element ranges.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_range_scheduler #(
    parameter int unsigned LANES = 16,
    parameter int unsigned RANGES = 64,
    parameter int unsigned CONTRIBUTORS = 2,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_tile_meta_t           s_meta,
    input  logic [LANES*32-1:0]                   s_fp32_bits,
    input  logic signed [LANES*WIDTH_2-1:0]       s_kulisch_deposits,
    input  logic [LANES-1:0]                      s_element_keep,
    input  logic [LANES-1:0]                      s_finite,
    input  logic [LANES-1:0]                      s_zero,
    input  logic [LANES-1:0]                      s_zero_sign,
    input  logic [LANES-1:0]                      s_nan,
    input  logic [LANES-1:0]                      s_positive_infinity,
    input  logic [LANES-1:0]                      s_negative_infinity,
    input  logic [LANES-1:0]                      s_deposit_overflow,
    input  logic [1:0]                            s_width_index,
    input  logic                                  s_format_error,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output prism_pkg::prism_tile_meta_t           m_meta,
    output logic [LANES*32-1:0]                   m_fp32_bits,
    output logic [LANES-1:0]                      m_element_keep,
    output logic                                  m_accumulation_inexact,
    output logic                                  m_valid,
    input  logic                                  m_ready
);

  import prism_pkg::*;

  localparam int unsigned SLOT_W = prism_clog2_safe(RANGES);
  localparam int unsigned CONTRIBUTOR_W = prism_clog2_safe(CONTRIBUTORS);

  logic range_valid [0:RANGES-1];
  logic range_busy [0:RANGES-1];
  logic range_ready [0:RANGES-1];
  logic range_fold_pending [0:RANGES-1];
  logic [15:0] range_operation_slot [0:RANGES-1];
  logic [31:0] range_index [0:RANGES-1];
  prism_tile_meta_t range_meta [0:RANGES-1];
  logic [LANES-1:0] expected_mask [0:RANGES-1];
  logic [LANES-1:0] received_mask [0:RANGES-1][0:CONTRIBUTORS-1];
  logic range_warning [0:RANGES-1];

  logic [31:0] fp_values [0:RANGES-1][0:LANES-1];
  logic [31:0] ordered_values [0:RANGES-1][0:CONTRIBUTORS-1][0:LANES-1];
  logic signed [WIDTH_2-1:0] kulisch_values [0:RANGES-1][0:LANES-1];
  logic [LANES-1:0] saw_nan [0:RANGES-1];
  logic [LANES-1:0] saw_positive_infinity [0:RANGES-1];
  logic [LANES-1:0] saw_negative_infinity [0:RANGES-1];
  logic [LANES-1:0] saw_finite_nonzero [0:RANGES-1];
  logic [LANES-1:0] saw_zero [0:RANGES-1];
  logic [LANES-1:0] all_zero_negative [0:RANGES-1];

  logic input_match;
  logic input_free;
  logic [SLOT_W-1:0] input_slot;
  logic [31:0] input_range_index;
  logic [31:0] input_range_first;
  logic [LANES-1:0] input_expected_mask;
  logic [LANES-1:0] input_prior_mask;
  logic [LANES-1:0] input_effective_keep;
  logic input_complete_after;
  logic input_slot_available;
  logic [LANES-1:0] input_lane_any;

  logic fp_request_valid;
  logic fp_request_ready;
  logic [LANES*32-1:0] fp_left;
  logic [LANES*32-1:0] fp_right;
  logic ordered_pair_fast_path;
  logic [LANES*32-1:0] fp_result;
  logic [LANES-1:0] unused_fp_result_keep;
  logic [LANES*5-1:0] unused_fp_exceptions;
  logic unused_fp_tag;
  logic fp_result_valid;
  logic [SLOT_W-1:0] fp_transaction_slot;
  logic [CONTRIBUTOR_W-1:0] fp_transaction_contributor;
  logic [LANES-1:0] fp_transaction_first_mask;
  logic [LANES-1:0] fp_transaction_keep;
  logic [LANES*32-1:0] fp_transaction_input;
  logic fp_transaction_complete;
  logic fp_transaction_ordered_pair;

  logic fold_found;
  logic [SLOT_W-1:0] fold_found_slot;
  logic fold_active;
  logic fold_waiting;
  logic [SLOT_W-1:0] fold_slot;
  logic [CONTRIBUTOR_W-1:0] fold_contributor;
  logic [LANES*32-1:0] fold_accumulator;
  logic [LANES*32-1:0] fold_right;
  logic [LANES*32-1:0] fold_seed;
  logic fold_request_ready;
  logic fold_result_valid;
  logic [LANES*32-1:0] fold_result;
  logic [LANES-1:0] unused_fold_result_keep;
  logic [LANES*5-1:0] unused_fold_exceptions;
  logic unused_fold_tag;

  logic output_found;
  logic [SLOT_W-1:0] output_slot;
  logic [LANES*32-1:0] kulisch_fp32;
  logic signed [LANES*WIDTH_2-1:0] kulisch_finalize_input;
  logic [LANES-1:0] unused_kulisch_round_overflow;
  logic [LANES-1:0] unused_kulisch_round_underflow;
  logic [LANES-1:0] unused_kulisch_round_inexact;

  logic signed [WIDTH_2-1:0] kulisch_updated [0:LANES-1];
  logic [LANES-1:0] kulisch_saturated;

  function automatic logic [WIDTH_2:0] saturating_add(
      input logic signed [WIDTH_2-1:0] left,
      input logic signed [WIDTH_2-1:0] right,
      input logic [1:0] width_selection
  );
    logic signed [WIDTH_0-1:0] left0, right0, sum0;
    logic signed [WIDTH_1-1:0] left1, right1, sum1;
    logic signed [WIDTH_2-1:0] sum2;
    logic overflow_value;
    logic signed [WIDTH_2-1:0] result_value;
    begin
      overflow_value = 1'b0;
      result_value = '0;
      left0 = left[WIDTH_0-1:0]; right0 = right[WIDTH_0-1:0]; sum0 = left0 + right0;
      left1 = left[WIDTH_1-1:0]; right1 = right[WIDTH_1-1:0]; sum1 = left1 + right1;
      sum2 = left + right;
      case (width_selection)
        2'd0: begin
          overflow_value = (left0[WIDTH_0-1] == right0[WIDTH_0-1])
              && (sum0[WIDTH_0-1] != left0[WIDTH_0-1]);
          if (overflow_value) begin
            result_value = left0[WIDTH_0-1]
                ? {{(WIDTH_2-WIDTH_0){1'b1}}, 1'b1, {(WIDTH_0-1){1'b0}}}
                : {{(WIDTH_2-WIDTH_0){1'b0}}, 1'b0, {(WIDTH_0-1){1'b1}}};
          end else result_value = {{(WIDTH_2-WIDTH_0){sum0[WIDTH_0-1]}}, sum0};
        end
        2'd1: begin
          overflow_value = (left1[WIDTH_1-1] == right1[WIDTH_1-1])
              && (sum1[WIDTH_1-1] != left1[WIDTH_1-1]);
          if (overflow_value) begin
            result_value = left1[WIDTH_1-1]
                ? {{(WIDTH_2-WIDTH_1){1'b1}}, 1'b1, {(WIDTH_1-1){1'b0}}}
                : {{(WIDTH_2-WIDTH_1){1'b0}}, 1'b0, {(WIDTH_1-1){1'b1}}};
          end else result_value = {{(WIDTH_2-WIDTH_1){sum1[WIDTH_1-1]}}, sum1};
        end
        default: begin
          overflow_value = (left[WIDTH_2-1] == right[WIDTH_2-1])
              && (sum2[WIDTH_2-1] != left[WIDTH_2-1]);
          if (overflow_value) begin
            result_value = left[WIDTH_2-1]
                ? {1'b1, {(WIDTH_2-1){1'b0}}} : {1'b0, {(WIDTH_2-1){1'b1}}};
          end else result_value = sum2;
        end
      endcase
      return {overflow_value, result_value};
    end
  endfunction

  // ---------------------------------------------------------------------------
  // Elaboration checks and input range selection
  // ---------------------------------------------------------------------------

  initial begin
    if ((LANES < 1) || (RANGES < 2) || (CONTRIBUTORS < 1)
        || (WIDTH_0 < 8) || (WIDTH_1 < WIDTH_0) || (WIDTH_2 < WIDTH_1)) begin
      $fatal(1, "prism_range_scheduler parameters are illegal");
    end
  end

  always_comb begin
    input_range_index = s_meta.first_element / LANES;
    input_range_first = input_range_index * LANES;
    input_match = 1'b0;
    input_free = 1'b0;
    input_slot = '0;
    for (int unsigned slot = 0; slot < RANGES; slot++) begin
      if (range_valid[slot] && (range_operation_slot[slot] == s_meta.operation_slot)
          && (range_index[slot] == input_range_index) && !input_match) begin
        input_match = 1'b1;
        input_slot = SLOT_W'(slot);
      end
    end
    if (!input_match) begin
      for (int unsigned slot = 0; slot < RANGES; slot++) begin
        if (!range_valid[slot] && !input_free) begin
          input_free = 1'b1;
          input_slot = SLOT_W'(slot);
        end
      end
    end
    input_expected_mask = '0;
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      input_expected_mask[lane] =
          (input_range_first + 32'(lane)) < s_meta.total_element_count;
    end
    input_prior_mask = '0;
    if (input_match && (s_meta.contributor_id < 16'(CONTRIBUTORS))) begin
      input_prior_mask =
          received_mask[input_slot][CONTRIBUTOR_W'(s_meta.contributor_id)];
    end
    input_effective_keep = s_element_keep & ~input_prior_mask;
    input_lane_any = '0;
    if (input_match) begin
      for (int unsigned contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
        input_lane_any |= received_mask[input_slot][contributor];
      end
    end
    input_complete_after = (s_meta.expected_contributors != 0)
        && (s_meta.expected_contributors <= 16'(CONTRIBUTORS));
    for (int unsigned contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
      if (16'(contributor) < s_meta.expected_contributors) begin
        if (16'(contributor) == s_meta.contributor_id) begin
          input_complete_after &= ((input_prior_mask | input_effective_keep)
              == input_expected_mask);
        end else begin
          input_complete_after &= input_match
              && (received_mask[input_slot][contributor] == input_expected_mask);
        end
      end
    end
    input_slot_available = (input_match || input_free)
        && !range_busy[input_slot] && !range_ready[input_slot]
        && !range_fold_pending[input_slot]
        && (s_meta.contributor_id < s_meta.expected_contributors)
        && (s_meta.expected_contributors <= 16'(CONTRIBUTORS)) && !s_format_error;
  end

  always_comb begin
    fp_left = '0;
    fp_right = s_fp32_bits;
    ordered_pair_fast_path = (s_meta.accumulator_profile == PRISM_ACC_FP32_ORDERED)
        && (s_meta.expected_contributors == 2) && input_complete_after
        && (input_effective_keep != 0);
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      fp_left[lane*32 +: 32] = input_match ? fp_values[input_slot][lane] : 32'b0;
      if (ordered_pair_fast_path) begin
        if (s_meta.contributor_id == 0) begin
          fp_left[lane*32 +: 32] = input_effective_keep[lane]
              ? s_fp32_bits[lane*32 +: 32]
              : ordered_values[input_slot][0][lane];
          fp_right[lane*32 +: 32] = ordered_values[input_slot][1][lane];
        end else begin
          fp_left[lane*32 +: 32] = ordered_values[input_slot][0][lane];
          fp_right[lane*32 +: 32] = input_effective_keep[lane]
              ? s_fp32_bits[lane*32 +: 32]
              : ordered_values[input_slot][1][lane];
        end
      end
    end
    fp_request_valid = s_valid && input_slot_available
        && ((s_meta.accumulator_profile == PRISM_ACC_FP32_ARRIVAL) || ordered_pair_fast_path)
        && (input_effective_keep != 0);
    if (!input_slot_available) s_ready = 1'b0;
    else if (((s_meta.accumulator_profile == PRISM_ACC_FP32_ARRIVAL)
        || ordered_pair_fast_path)
        && (input_effective_keep != 0)) s_ready = fp_request_ready;
    else s_ready = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // Arrival-ordered FP32 backend
  // ---------------------------------------------------------------------------

  prism_fp32_backend #(
      .LANES(LANES),
      .TAG_W(1)
  ) u_accepted_backend (
      .clk(clk),
      .rst_n(rst_n),
      .s_left(fp_left),
      .s_right(fp_right),
      .s_lane_keep(input_effective_keep),
      .s_tag(1'b0),
      .s_valid(fp_request_valid),
      .s_ready(fp_request_ready),
      .m_result(fp_result),
      .m_lane_keep(unused_fp_result_keep),
      .m_exceptions(unused_fp_exceptions),
      .m_tag(unused_fp_tag),
      .m_valid(fp_result_valid),
      .m_ready(1'b1)
  );

  always_comb begin
    fold_found = 1'b0;
    fold_found_slot = '0;
    for (int unsigned slot = 0; slot < RANGES; slot++) begin
      if (range_valid[slot] && range_fold_pending[slot] && !fold_found) begin
        fold_found = 1'b1;
        fold_found_slot = SLOT_W'(slot);
      end
    end
    fold_right = '0;
    fold_seed = '0;
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      fold_right[lane*32 +: 32] = ordered_values[fold_slot][fold_contributor][lane];
      fold_seed[lane*32 +: 32] = ordered_values[fold_found_slot][0][lane];
    end
  end

  // ---------------------------------------------------------------------------
  // Contributor-ordered FP32 fold backend
  // ---------------------------------------------------------------------------

  prism_fp32_backend #(
      .LANES(LANES),
      .TAG_W(1)
  ) u_ordered_backend (
      .clk(clk),
      .rst_n(rst_n),
      .s_left(fold_accumulator),
      .s_right(fold_right),
      .s_lane_keep(expected_mask[fold_slot]),
      .s_tag(1'b0),
      .s_valid(fold_active && !fold_waiting),
      .s_ready(fold_request_ready),
      .m_result(fold_result),
      .m_lane_keep(unused_fold_result_keep),
      .m_exceptions(unused_fold_exceptions),
      .m_tag(unused_fold_tag),
      .m_valid(fold_result_valid),
      .m_ready(1'b1)
  );

  always_comb begin
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      logic [WIDTH_2:0] add_result;
      add_result = saturating_add(
          input_match ? kulisch_values[input_slot][lane] : '0,
          s_kulisch_deposits[lane*WIDTH_2 +: WIDTH_2], s_width_index);
      kulisch_updated[lane] = add_result[WIDTH_2-1:0];
      kulisch_saturated[lane] = add_result[WIDTH_2];
    end
  end

  always_comb begin
    output_found = 1'b0;
    output_slot = '0;
    for (int unsigned slot = 0; slot < RANGES; slot++) begin
      if (range_valid[slot] && range_ready[slot] && !output_found) begin
        output_found = 1'b1;
        output_slot = SLOT_W'(slot);
      end
    end
  end

  always_comb begin
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      kulisch_finalize_input[lane*WIDTH_2 +: WIDTH_2] =
          kulisch_values[output_slot][lane];
    end
  end

  // ---------------------------------------------------------------------------
  // Exact-accumulator finalization and output selection
  // ---------------------------------------------------------------------------

  prism_kulisch_finalize_array #(
      .ACC_W(WIDTH_2),
      .LANES(LANES)
  ) u_kulisch_finalize (
      .accumulators(kulisch_finalize_input),
      .input_format(prism_wire_format_e'(range_meta[output_slot].input_format)),
      .saw_nan(saw_nan[output_slot]),
      .saw_positive_infinity(saw_positive_infinity[output_slot]),
      .saw_negative_infinity(saw_negative_infinity[output_slot]),
      .saw_finite_nonzero(saw_finite_nonzero[output_slot]),
      .saw_zero(saw_zero[output_slot]),
      .all_zero_negative(all_zero_negative[output_slot]),
      .fp32_bits(kulisch_fp32),
      .overflow(unused_kulisch_round_overflow),
      .underflow(unused_kulisch_round_underflow),
      .inexact(unused_kulisch_round_inexact)
  );

  always_comb begin
    m_meta = range_meta[output_slot];
    m_element_keep = expected_mask[output_slot];
    m_accumulation_inexact = range_warning[output_slot];
    m_fp32_bits = '0;
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      m_fp32_bits[lane*32 +: 32] =
          (range_meta[output_slot].accumulator_profile == PRISM_ACC_KULISCH_FP32)
          ? kulisch_fp32[lane*32 +: 32] : fp_values[output_slot][lane];
    end
    m_valid = output_found;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      fp_transaction_slot <= '0;
      fp_transaction_contributor <= '0;
      fp_transaction_first_mask <= '0;
      fp_transaction_keep <= '0;
      fp_transaction_input <= '0;
      fp_transaction_complete <= 1'b0;
      fp_transaction_ordered_pair <= 1'b0;
      fold_active <= 1'b0;
      fold_waiting <= 1'b0;
      fold_slot <= '0;
      fold_contributor <= '0;
      fold_accumulator <= '0;
      for (int unsigned slot = 0; slot < RANGES; slot++) begin
        range_valid[slot] <= 1'b0;
        range_busy[slot] <= 1'b0;
        range_ready[slot] <= 1'b0;
        range_fold_pending[slot] <= 1'b0;
        range_operation_slot[slot] <= '0;
        range_index[slot] <= '0;
        range_meta[slot] <= '0;
        expected_mask[slot] <= '0;
        range_warning[slot] <= 1'b0;
        saw_nan[slot] <= '0;
        saw_positive_infinity[slot] <= '0;
        saw_negative_infinity[slot] <= '0;
        saw_finite_nonzero[slot] <= '0;
        saw_zero[slot] <= '0;
        all_zero_negative[slot] <= '0;
        for (int unsigned contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
          received_mask[slot][contributor] <= '0;
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            ordered_values[slot][contributor][lane] <= '0;
          end
        end
        for (int unsigned lane = 0; lane < LANES; lane++) begin
          fp_values[slot][lane] <= '0;
          kulisch_values[slot][lane] <= '0;
        end
      end
    end else begin
      if (m_valid && m_ready) begin
        range_valid[output_slot] <= 1'b0;
        range_ready[output_slot] <= 1'b0;
      end

      if (s_valid && s_ready) begin
        if (!input_match) begin
          range_valid[input_slot] <= 1'b1;
          range_operation_slot[input_slot] <= s_meta.operation_slot;
          range_index[input_slot] <= input_range_index;
          range_meta[input_slot] <= s_meta;
          range_meta[input_slot].first_element <= input_range_first;
          range_meta[input_slot].element_count <= 8'($countones(input_expected_mask));
          expected_mask[input_slot] <= input_expected_mask;
          range_warning[input_slot] <=
              (s_meta.flags & PRISM_DATA_FLAG_ACCUMULATION_INEXACT) != 0;
          for (int unsigned contributor = 0; contributor < CONTRIBUTORS; contributor++) begin
            received_mask[input_slot][contributor] <= '0;
          end
          saw_nan[input_slot] <= '0;
          saw_positive_infinity[input_slot] <= '0;
          saw_negative_infinity[input_slot] <= '0;
          saw_finite_nonzero[input_slot] <= '0;
          saw_zero[input_slot] <= '0;
          all_zero_negative[input_slot] <= {LANES{1'b1}};
        end else if ((s_meta.flags & PRISM_DATA_FLAG_ACCUMULATION_INEXACT) != 0) begin
          range_warning[input_slot] <= 1'b1;
        end

        if (s_meta.accumulator_profile == PRISM_ACC_FP32_ARRIVAL) begin
          if (input_effective_keep != 0) begin
            range_busy[input_slot] <= 1'b1;
            fp_transaction_slot <= input_slot;
            fp_transaction_contributor <= CONTRIBUTOR_W'(s_meta.contributor_id);
            fp_transaction_first_mask <= input_effective_keep & ~input_lane_any;
            fp_transaction_keep <= input_effective_keep;
            fp_transaction_input <= s_fp32_bits;
            fp_transaction_complete <= input_complete_after;
            fp_transaction_ordered_pair <= 1'b0;
          end
        end else if (s_meta.accumulator_profile == PRISM_ACC_FP32_ORDERED) begin
          received_mask[input_slot][CONTRIBUTOR_W'(s_meta.contributor_id)]
              <= input_prior_mask | input_effective_keep;
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            if (input_effective_keep[lane]) begin
              ordered_values[input_slot][CONTRIBUTOR_W'(s_meta.contributor_id)][lane]
                  <= s_fp32_bits[lane*32 +: 32];
            end
          end
          if (input_complete_after) begin
            if (ordered_pair_fast_path) begin
              range_busy[input_slot] <= 1'b1;
              fp_transaction_slot <= input_slot;
              fp_transaction_contributor <= CONTRIBUTOR_W'(s_meta.contributor_id);
              fp_transaction_first_mask <= '0;
              fp_transaction_keep <= input_expected_mask;
              fp_transaction_input <= '0;
              fp_transaction_complete <= 1'b1;
              fp_transaction_ordered_pair <= 1'b1;
            end else begin
              range_fold_pending[input_slot] <= 1'b1;
            end
          end
        end else if (s_meta.accumulator_profile == PRISM_ACC_KULISCH_FP32) begin
          received_mask[input_slot][CONTRIBUTOR_W'(s_meta.contributor_id)]
              <= input_prior_mask | input_effective_keep;
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            if (input_effective_keep[lane]) begin
              kulisch_values[input_slot][lane] <= kulisch_updated[lane];
              saw_nan[input_slot][lane] <= (input_match && saw_nan[input_slot][lane]) || s_nan[lane];
              saw_positive_infinity[input_slot][lane] <=
                  (input_match && saw_positive_infinity[input_slot][lane])
                  || s_positive_infinity[lane];
              saw_negative_infinity[input_slot][lane] <=
                  (input_match && saw_negative_infinity[input_slot][lane])
                  || s_negative_infinity[lane];
              saw_finite_nonzero[input_slot][lane] <=
                  (input_match && saw_finite_nonzero[input_slot][lane])
                  || (s_finite[lane] && !s_zero[lane]);
              saw_zero[input_slot][lane] <= (input_match && saw_zero[input_slot][lane])
                  || s_zero[lane];
              all_zero_negative[input_slot][lane] <=
                  (!input_match || all_zero_negative[input_slot][lane])
                  && (!s_zero[lane] || s_zero_sign[lane]);
              if (kulisch_saturated[lane] || s_deposit_overflow[lane]) begin
                range_warning[input_slot] <= 1'b1;
              end
            end
          end
          if (input_complete_after) range_ready[input_slot] <= 1'b1;
        end
      end

      if (fp_result_valid) begin
        range_busy[fp_transaction_slot] <= 1'b0;
        if (fp_transaction_ordered_pair) begin
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            if (fp_transaction_keep[lane]) begin
              fp_values[fp_transaction_slot][lane] <= fp_result[lane*32 +: 32];
            end
          end
          range_ready[fp_transaction_slot] <= 1'b1;
        end else begin
          received_mask[fp_transaction_slot][fp_transaction_contributor] <=
              received_mask[fp_transaction_slot][fp_transaction_contributor]
              | fp_transaction_keep;
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            if (fp_transaction_keep[lane]) begin
              fp_values[fp_transaction_slot][lane] <= fp_transaction_first_mask[lane]
                  ? fp_transaction_input[lane*32 +: 32] : fp_result[lane*32 +: 32];
            end
          end
          if (fp_transaction_complete) range_ready[fp_transaction_slot] <= 1'b1;
        end
      end

      if (!fold_active && fold_found) begin
        fold_slot <= fold_found_slot;
        fold_accumulator <= fold_seed;
        range_fold_pending[fold_found_slot] <= 1'b0;
        if (range_meta[fold_found_slot].expected_contributors <= 1) begin
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            fp_values[fold_found_slot][lane] <= ordered_values[fold_found_slot][0][lane];
          end
          range_ready[fold_found_slot] <= 1'b1;
        end else begin
          fold_contributor <= CONTRIBUTOR_W'(1);
          fold_active <= 1'b1;
        end
      end
      if (fold_active && !fold_waiting && fold_request_ready) fold_waiting <= 1'b1;
      if (fold_result_valid) begin
        fold_waiting <= 1'b0;
        fold_accumulator <= fold_result;
        if (16'(fold_contributor) + 16'd1
            >= range_meta[fold_slot].expected_contributors) begin
          for (int unsigned lane = 0; lane < LANES; lane++) begin
            fp_values[fold_slot][lane] <= fold_result[lane*32 +: 32];
          end
          range_ready[fold_slot] <= 1'b1;
          fold_active <= 1'b0;
        end else begin
          fold_contributor <= fold_contributor + CONTRIBUTOR_W'(1);
        end
      end
    end
  end

endmodule
