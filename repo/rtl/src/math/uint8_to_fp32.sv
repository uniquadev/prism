
`timescale 1ns / 1ps

module uint8_to_fp32 (
    input  logic [7:0]  in_u8,
    output logic [31:0] out_fp32
);

  integer i;
  integer msb;
  logic [7:0] exponent;
  logic [23:0] normalized;
  logic [22:0] mantissa;

  always_comb begin
    out_fp32   = 32'd0;
    msb        = -1;
    exponent   = 8'd0;
    normalized = 24'd0;
    mantissa   = 23'd0;

    if (in_u8 == 8'd0) begin
      out_fp32 = 32'd0;
    end else begin
      for (i = 0; i < 8; i++) begin
        if (in_u8[i]) begin
          msb = i;
        end
      end

      exponent = 8'(127 + msb);

      // Place the integer so that its MSB lands at bit 23.
      normalized = {16'd0, in_u8} << (23 - msb);

      // Drop implicit leading 1.
      mantissa = normalized[22:0];

      out_fp32 = {1'b0, exponent, mantissa};
    end
  end

endmodule
