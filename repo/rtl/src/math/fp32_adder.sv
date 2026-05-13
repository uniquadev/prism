`timescale 1ns / 1ps

// -----------------------------------------------------------------------------
// fp32_adder
//
// IEEE-754 FP32 adder, combinational RTL implementation.
//
// Handles:
//   - positive and negative finite values
//   - addition/subtraction through sign handling
//   - zero
//   - infinities
//   - NaN propagation to qNaN
//   - exponent alignment
//   - mantissa add/sub
//   - normalization
//   - guard/round/sticky
//   - round-to-nearest-even
//   - overflow to infinity
//   - basic subnormal/underflow handling
//
// Note:
//   This is a real FP32 adder module interface/architecture, but it still
//   deserves dedicated unit tests before being considered production-verified.
// -----------------------------------------------------------------------------

module fp32_adder (
    input  logic [31:0] a,
    input  logic [31:0] b,
    output logic [31:0] y
);

  localparam logic [31:0] FP32_QNAN = 32'h7fc0_0000;
  localparam logic [31:0] FP32_PINF = 32'h7f80_0000;
  localparam logic [31:0] FP32_NINF = 32'hff80_0000;

  logic sign_a;
  logic sign_b;

  logic [7:0] exp_a_raw;
  logic [7:0] exp_b_raw;

  logic [22:0] frac_a;
  logic [22:0] frac_b;

  logic is_nan_a;
  logic is_nan_b;
  logic is_inf_a;
  logic is_inf_b;
  logic is_zero_a;
  logic is_zero_b;

  logic [7:0] exp_a_eff;
  logic [7:0] exp_b_eff;

  logic [23:0] mant_a_24;
  logic [23:0] mant_b_24;

  logic [26:0] mant_a_ext;
  logic [26:0] mant_b_ext;

  logic [26:0] mant_big;
  logic [26:0] mant_small;
  logic [26:0] mant_small_shifted;

  logic        sign_big;
  logic        sign_small;
  logic [7:0]  exp_big;

  logic [27:0] add_sum;
  logic [27:0] sub_diff;

  logic [26:0] mant_work;
  logic        sign_work;
  integer      exp_work;

  logic [23:0] mant_pre_round;
  logic        guard_bit;
  logic        round_bit;
  logic        sticky_bit;
  logic        round_increment;

  logic [24:0] mant_rounded;
  logic [7:0]  exp_result;

  integer diff;
  integer norm_i;

  function automatic logic [26:0] shift_right_jam_27;
    input logic [26:0] value;
    input integer      shamt;

    logic sticky;
    integer k;
    begin
      if (shamt <= 0) begin
        shift_right_jam_27 = value;
      end else if (shamt >= 27) begin
        sticky = |value;
        shift_right_jam_27 = {26'd0, sticky};
      end else begin
        sticky = 1'b0;

        for (k = 0; k < shamt; k = k + 1) begin
          sticky = sticky | value[k];
        end

        shift_right_jam_27 = value >> shamt;
        shift_right_jam_27[0] = shift_right_jam_27[0] | sticky;
      end
    end
  endfunction

  function automatic logic a_magnitude_ge_b;
    input logic [7:0]  exp_a_i;
    input logic [7:0]  exp_b_i;
    input logic [23:0] mant_a_i;
    input logic [23:0] mant_b_i;
    begin
      if (exp_a_i > exp_b_i) begin
        a_magnitude_ge_b = 1'b1;
      end else if (exp_a_i < exp_b_i) begin
        a_magnitude_ge_b = 1'b0;
      end else begin
        a_magnitude_ge_b = mant_a_i >= mant_b_i;
      end
    end
  endfunction

  always_comb begin
    sign_a    = a[31];
    sign_b    = b[31];

    exp_a_raw = a[30:23];
    exp_b_raw = b[30:23];

    frac_a    = a[22:0];
    frac_b    = b[22:0];

    is_nan_a  = (exp_a_raw == 8'hff) && (frac_a != 23'd0);
    is_nan_b  = (exp_b_raw == 8'hff) && (frac_b != 23'd0);

    is_inf_a  = (exp_a_raw == 8'hff) && (frac_a == 23'd0);
    is_inf_b  = (exp_b_raw == 8'hff) && (frac_b == 23'd0);

    is_zero_a = (exp_a_raw == 8'd0) && (frac_a == 23'd0);
    is_zero_b = (exp_b_raw == 8'd0) && (frac_b == 23'd0);

    exp_a_eff = 8'd0;
    exp_b_eff = 8'd0;

    mant_a_24 = 24'd0;
    mant_b_24 = 24'd0;

    mant_a_ext = 27'd0;
    mant_b_ext = 27'd0;

    mant_big           = 27'd0;
    mant_small         = 27'd0;
    mant_small_shifted = 27'd0;

    sign_big   = 1'b0;
    sign_small = 1'b0;
    exp_big    = 8'd0;

    add_sum  = 28'd0;
    sub_diff = 28'd0;

    mant_work = 27'd0;
    sign_work = 1'b0;
    exp_work  = 0;

    mant_pre_round  = 24'd0;
    guard_bit       = 1'b0;
    round_bit       = 1'b0;
    sticky_bit      = 1'b0;
    round_increment = 1'b0;

    mant_rounded = 25'd0;
    exp_result   = 8'd0;

    diff   = 0;
    norm_i = 0;

    y = 32'd0;

    // NaN
    if (is_nan_a || is_nan_b) begin
      y = FP32_QNAN;
    end

    // Infinity
    else if (is_inf_a && is_inf_b) begin
      if (sign_a != sign_b) begin
        y = FP32_QNAN;
      end else begin
        y = sign_a ? FP32_NINF : FP32_PINF;
      end
    end else if (is_inf_a) begin
      y = sign_a ? FP32_NINF : FP32_PINF;
    end else if (is_inf_b) begin
      y = sign_b ? FP32_NINF : FP32_PINF;
    end

    // Zero
    else if (is_zero_a && is_zero_b) begin
      y = 32'd0;
    end else if (is_zero_a) begin
      y = b;
    end else if (is_zero_b) begin
      y = a;
    end

    // Finite add/sub
    else begin
      exp_a_eff = (exp_a_raw == 8'd0) ? 8'd1 : exp_a_raw;
      exp_b_eff = (exp_b_raw == 8'd0) ? 8'd1 : exp_b_raw;

      mant_a_24 = (exp_a_raw == 8'd0) ? {1'b0, frac_a} : {1'b1, frac_a};
      mant_b_24 = (exp_b_raw == 8'd0) ? {1'b0, frac_b} : {1'b1, frac_b};

      mant_a_ext = {mant_a_24, 3'b000};
      mant_b_ext = {mant_b_24, 3'b000};

      if (a_magnitude_ge_b(exp_a_eff, exp_b_eff, mant_a_24, mant_b_24)) begin
        exp_big    = exp_a_eff;
        sign_big   = sign_a;
        sign_small = sign_b;
        mant_big   = mant_a_ext;
        mant_small = mant_b_ext;
        diff       = exp_a_eff - exp_b_eff;
      end else begin
        exp_big    = exp_b_eff;
        sign_big   = sign_b;
        sign_small = sign_a;
        mant_big   = mant_b_ext;
        mant_small = mant_a_ext;
        diff       = exp_b_eff - exp_a_eff;
      end

      mant_small_shifted = shift_right_jam_27(mant_small, diff);

      exp_work  = exp_big;
      sign_work = sign_big;

      if (sign_big == sign_small) begin
        add_sum = {1'b0, mant_big} + {1'b0, mant_small_shifted};

        if (add_sum[27]) begin
          mant_work = add_sum[27:1];
          mant_work[0] = mant_work[0] | add_sum[0];
          exp_work = exp_work + 1;
        end else begin
          mant_work = add_sum[26:0];
        end
      end else begin
        sub_diff = {1'b0, mant_big} - {1'b0, mant_small_shifted};
        mant_work = sub_diff[26:0];

        if (mant_work == 27'd0) begin
          sign_work = 1'b0;
          exp_work  = 0;
        end else begin
          for (norm_i = 0; norm_i < 27; norm_i = norm_i + 1) begin
            if ((mant_work[26] == 1'b0) && (exp_work > 1)) begin
              mant_work = mant_work << 1;
              exp_work  = exp_work - 1;
            end
          end
        end
      end

      if (mant_work == 27'd0) begin
        y = 32'd0;
      end else if (exp_work >= 255) begin
        y = sign_work ? FP32_NINF : FP32_PINF;
      end else if (exp_work <= 0) begin
        mant_work = shift_right_jam_27(mant_work, 1 - exp_work);

        mant_pre_round = mant_work[26:3];
        guard_bit      = mant_work[2];
        round_bit      = mant_work[1];
        sticky_bit     = mant_work[0];

        round_increment = guard_bit && (round_bit || sticky_bit || mant_pre_round[0]);
        mant_rounded = {1'b0, mant_pre_round} + {24'd0, round_increment};

        y = {sign_work, 8'd0, mant_rounded[22:0]};
      end else begin
        mant_pre_round = mant_work[26:3];
        guard_bit      = mant_work[2];
        round_bit      = mant_work[1];
        sticky_bit     = mant_work[0];

        round_increment = guard_bit && (round_bit || sticky_bit || mant_pre_round[0]);
        mant_rounded = {1'b0, mant_pre_round} + {24'd0, round_increment};

        if (mant_rounded[24]) begin
          exp_work = exp_work + 1;

          if (exp_work >= 255) begin
            y = sign_work ? FP32_NINF : FP32_PINF;
          end else begin
            exp_result = exp_work[7:0];
            y = {sign_work, exp_result, mant_rounded[23:1]};
          end
        end else begin
          exp_result = exp_work[7:0];
          y = {sign_work, exp_result, mant_rounded[22:0]};
        end
      end
    end
  end

endmodule
