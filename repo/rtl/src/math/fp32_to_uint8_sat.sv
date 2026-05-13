
`timescale 1ns / 1ps

module fp32_to_uint8_sat (
    input  logic [31:0] in_fp32,
    output logic [7:0]  out_u8
);

  logic        sign;
  logic [7:0]  exponent;
  logic [22:0] fraction;
  logic [23:0] mantissa;
  integer      shift;
  logic [31:0] value;

  always_comb begin
    sign     = in_fp32[31];
    exponent = in_fp32[30:23];
    fraction = in_fp32[22:0];
    mantissa = {1'b1, fraction};
    shift    = 0;
    value    = 32'd0;
    out_u8   = 8'd0;

    if (in_fp32 == 32'd0) begin
      out_u8 = 8'd0;
    end else if (sign) begin
      // Current reduction path is unsigned/saturating.
      out_u8 = 8'd0;
    end else if (exponent < 8'd127) begin
      out_u8 = 8'd0;
    end else if (exponent > 8'd134) begin
      // Anything >= 256 saturates.
      out_u8 = 8'hff;
    end else begin
      shift = exponent - 8'd127;

      if (shift >= 23) begin
        value = {8'd0, mantissa} << (shift - 23);
      end else begin
        value = {8'd0, mantissa} >> (23 - shift);
      end

      if (value > 32'd255) begin
        out_u8 = 8'hff;
      end else begin
        out_u8 = value[7:0];
      end
    end
  end

endmodule
