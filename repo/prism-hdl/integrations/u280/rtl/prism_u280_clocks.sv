//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_u280_clocks.sv
// Module: prism_u280_clocks
// Description: Clocks and power-on reset of the U280 design from a board oscillator.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// The 250 MHz clock of the datapath and the 125 MHz clock of the register
// interfaces come from one MMCM on a free-running 100 MHz board clock, so
// the two are phase aligned: the packet adapter of the OpenNIC shell moves
// signals between them without synchronisers.
//
// The reset is released in the 125 MHz domain some cycles after the MMCM
// has locked.
module prism_u280_clocks (
    input  logic sysclk_p,
    input  logic sysclk_n,
    output logic axis_aclk,
    output logic axil_aclk,
    output logic powerup_rstn
);

  logic sysclk, feedback, clock_250, clock_125, locked;
  (* ASYNC_REG = "TRUE" *) logic [1:0] locked_sync;
  logic [7:0] settled;

  IBUFDS #(.DQS_BIAS("TRUE")) u_sysclk (.I(sysclk_p), .IB(sysclk_n), .O(sysclk));

  // 100 MHz x 10 = 1000 MHz; / 4 = 250 MHz, / 8 = 125 MHz.
  MMCME4_BASE #(
      .CLKIN1_PERIOD(10.000),
      .DIVCLK_DIVIDE(1),
      .CLKFBOUT_MULT_F(10.000),
      .CLKOUT0_DIVIDE_F(4.000),
      .CLKOUT1_DIVIDE(8)
  ) u_mmcm (
      .CLKIN1(sysclk),
      .CLKFBIN(feedback),
      .CLKFBOUT(feedback),
      .CLKFBOUTB(),
      .CLKOUT0(clock_250),
      .CLKOUT0B(),
      .CLKOUT1(clock_125),
      .CLKOUT1B(),
      .CLKOUT2(),
      .CLKOUT2B(),
      .CLKOUT3(),
      .CLKOUT3B(),
      .CLKOUT4(),
      .CLKOUT5(),
      .CLKOUT6(),
      .LOCKED(locked),
      .PWRDWN(1'b0),
      .RST(1'b0)
  );

  BUFG u_axis_clock (.I(clock_250), .O(axis_aclk));
  BUFG u_axil_clock (.I(clock_125), .O(axil_aclk));

  always_ff @(posedge axil_aclk or negedge locked) begin
    if (!locked) locked_sync <= '0;
    else locked_sync <= {locked_sync[0], 1'b1};
  end
  always_ff @(posedge axil_aclk) begin
    if (!locked_sync[1]) begin
      settled <= '0;
      powerup_rstn <= 1'b0;
    end else begin
      if (!(&settled)) settled <= settled + 1'b1;
      powerup_rstn <= &settled;
    end
  end

endmodule
