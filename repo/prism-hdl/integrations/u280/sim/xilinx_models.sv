//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: xilinx_models.sv
// Module: IBUFDS, BUFG, OBUF, MMCME4_BASE, xpm_cdc_single, xpm_cdc_async_rst,
//         xpm_fifo_sync, xpm_fifo_async, xpm_fifo_axis, xpm_memory_sdpram
// Description: Behavioural models of the AMD primitives the board top uses, for Verilator.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ps / 1ps

// The board simulation runs the U280 top and the parts of the OpenNIC shell
// it reuses under Verilator, which cannot compile the vendor's simulation
// libraries. These models have the ports and parameters those designs use
// and the behaviour they rely on:
//
// - The FIFOs are first-word-fall-through and cross clocks with no latency:
//   a word written in one domain is visible in the other at once. The real
//   synchronisers add a few cycles, which only delays frames.
// - The MMCM makes its clocks from its parameters, phase aligned at time
//   zero, and locks after some cycles of its input clock.
// - Error correction, sleep, the counts and the threshold flags are not
//   modelled; the shell leaves them unconnected.
//
// Only the board simulation reads this file; the build uses the primitives.

module IBUFDS #(
    parameter DQS_BIAS = "FALSE",
    parameter DIFF_TERM = "FALSE",
    parameter IOSTANDARD = "DEFAULT"
) (
    input  logic I,
    input  logic IB,
    output logic O
);
  logic unused;
  assign unused = IB;
  assign O = I;
endmodule

module BUFG (
    input  logic I,
    output logic O
);
  assign O = I;
endmodule

module OBUF (
    input  logic I,
    output logic O
);
  assign O = I;
endmodule

module MMCME4_BASE #(
    parameter string BANDWIDTH = "OPTIMIZED",
    parameter real CLKFBOUT_MULT_F = 5.0,
    parameter real CLKFBOUT_PHASE = 0.0,
    parameter real CLKIN1_PERIOD = 0.0,
    parameter real CLKOUT0_DIVIDE_F = 1.0,
    parameter real CLKOUT0_DUTY_CYCLE = 0.5,
    parameter real CLKOUT0_PHASE = 0.0,
    parameter int CLKOUT1_DIVIDE = 1,
    parameter int CLKOUT2_DIVIDE = 1,
    parameter int CLKOUT3_DIVIDE = 1,
    parameter int CLKOUT4_DIVIDE = 1,
    parameter int CLKOUT5_DIVIDE = 1,
    parameter int CLKOUT6_DIVIDE = 1,
    parameter int DIVCLK_DIVIDE = 1,
    parameter real REF_JITTER1 = 0.0,
    parameter string STARTUP_WAIT = "FALSE"
) (
    input  logic CLKIN1,
    input  logic CLKFBIN,
    input  logic PWRDWN,
    input  logic RST,
    output logic CLKFBOUT,
    output logic CLKFBOUTB,
    output logic CLKOUT0,
    output logic CLKOUT0B,
    output logic CLKOUT1,
    output logic CLKOUT1B,
    output logic CLKOUT2,
    output logic CLKOUT2B,
    output logic CLKOUT3,
    output logic CLKOUT3B,
    output logic CLKOUT4,
    output logic CLKOUT5,
    output logic CLKOUT6,
    output logic LOCKED
);
  // Half periods in ps; the input period is in ns.
  localparam real VCO_PS = CLKIN1_PERIOD * 1000.0 * DIVCLK_DIVIDE / CLKFBOUT_MULT_F;
  localparam longint HALF0 = longint'(VCO_PS * CLKOUT0_DIVIDE_F / 2.0);
  localparam longint HALF1 = longint'(VCO_PS * CLKOUT1_DIVIDE / 2.0);
  localparam int LOCK_CYCLES = 16;

  int unsigned input_cycles = 0;
  logic unused;

  initial begin
    if (CLKIN1_PERIOD <= 0.0) $fatal(1, "The MMCM model needs CLKIN1_PERIOD");
  end

  initial begin
    CLKOUT0 = 1'b0;
    forever #(HALF0) CLKOUT0 = ~CLKOUT0;
  end

  initial begin
    CLKOUT1 = 1'b0;
    forever #(HALF1) CLKOUT1 = ~CLKOUT1;
  end

  always @(posedge CLKIN1 or posedge RST) begin
    if (RST) input_cycles <= 0;
    else if (input_cycles < LOCK_CYCLES) input_cycles <= input_cycles + 1;
  end

  assign LOCKED = input_cycles == LOCK_CYCLES && !PWRDWN;
  assign unused = CLKFBIN;
  assign CLKFBOUT = 1'b0;
  assign CLKFBOUTB = 1'b1;
  assign CLKOUT0B = ~CLKOUT0;
  assign CLKOUT1B = ~CLKOUT1;
  assign {CLKOUT2, CLKOUT2B, CLKOUT3, CLKOUT3B, CLKOUT4, CLKOUT5, CLKOUT6} = 7'b0101000;
endmodule

module xpm_cdc_single #(
    parameter int DEST_SYNC_FF = 4,
    parameter int INIT_SYNC_FF = 0,
    parameter int SIM_ASSERT_CHK = 0,
    parameter int SRC_INPUT_REG = 1
) (
    input  logic src_clk,
    input  logic src_in,
    input  logic dest_clk,
    output logic dest_out
);
  logic source = 1'b0;
  logic [DEST_SYNC_FF-1:0] stages = '0;

  always @(posedge src_clk) source <= src_in;
  always @(posedge dest_clk) begin
    stages <= {stages[DEST_SYNC_FF-2:0], SRC_INPUT_REG != 0 ? source : src_in};
  end
  assign dest_out = stages[DEST_SYNC_FF-1];
endmodule

module xpm_cdc_async_rst #(
    parameter int DEST_SYNC_FF = 4,
    parameter int INIT_SYNC_FF = 0,
    parameter int RST_ACTIVE_HIGH = 0
) (
    input  logic src_arst,
    input  logic dest_clk,
    output logic dest_arst
);
  // Asserted at once, released after DEST_SYNC_FF cycles of dest_clk.
  logic active;
  logic [DEST_SYNC_FF-1:0] stages = '1;

  assign active = RST_ACTIVE_HIGH != 0 ? src_arst : !src_arst;
  always @(posedge dest_clk or posedge active) begin
    if (active) stages <= '1;
    else stages <= {stages[DEST_SYNC_FF-2:0], 1'b0};
  end
  assign dest_arst = RST_ACTIVE_HIGH != 0 ? stages[DEST_SYNC_FF-1] : !stages[DEST_SYNC_FF-1];
endmodule

// The storage of the FIFO models: first word fall through, one write and
// one read clock, cleared by a reset high, a power of two deep.
module prism_sim_fifo #(
    parameter int WIDTH = 1,
    parameter int DEPTH = 16
) (
    input  logic             wr_clk,
    input  logic             rd_clk,
    input  logic             rst,
    input  logic             wr_en,
    input  logic [WIDTH-1:0] din,
    output logic             full,
    input  logic             rd_en,
    output logic [WIDTH-1:0] dout,
    output logic             empty
);
  localparam int ADDR_W = $clog2(DEPTH);

  logic [WIDTH-1:0] words [DEPTH];
  logic [ADDR_W:0] written = '0, taken = '0;
  logic [ADDR_W:0] count;

  assign count = written - taken;
  assign full = count == (ADDR_W + 1)'(DEPTH);
  assign empty = count == '0;
  initial begin
    if (DEPTH < 2 || (DEPTH & (DEPTH - 1)) != 0) $fatal(1, "The FIFO model needs a power of two");
  end

  assign dout = words[taken[ADDR_W-1:0]];

  always @(posedge wr_clk or posedge rst) begin
    if (rst) begin
      written <= '0;
    end else if (wr_en && !full) begin
      words[written[ADDR_W-1:0]] <= din;
      written <= written + 1'b1;
    end
  end

  always @(posedge rd_clk or posedge rst) begin
    if (rst) taken <= '0;
    else if (rd_en && !empty) taken <= taken + 1'b1;
  end
endmodule

module xpm_fifo_sync #(
    parameter int CASCADE_HEIGHT = 0,
    parameter string DOUT_RESET_VALUE = "0",
    parameter string ECC_MODE = "no_ecc",
    parameter string FIFO_MEMORY_TYPE = "auto",
    parameter int FIFO_READ_LATENCY = 1,
    parameter int FIFO_WRITE_DEPTH = 2048,
    parameter int FULL_RESET_VALUE = 0,
    parameter int PROG_EMPTY_THRESH = 10,
    parameter int PROG_FULL_THRESH = 10,
    parameter int RD_DATA_COUNT_WIDTH = 1,
    parameter int READ_DATA_WIDTH = 32,
    parameter string READ_MODE = "std",
    parameter int SIM_ASSERT_CHK = 0,
    parameter string USE_ADV_FEATURES = "0707",
    parameter int WAKEUP_TIME = 0,
    parameter int WRITE_DATA_WIDTH = 32,
    parameter int WR_DATA_COUNT_WIDTH = 1
) (
    input  logic                           sleep,
    input  logic                           rst,
    input  logic                           wr_clk,
    input  logic                           wr_en,
    input  logic [WRITE_DATA_WIDTH-1:0]    din,
    output logic                           full,
    output logic                           prog_full,
    output logic [WR_DATA_COUNT_WIDTH-1:0] wr_data_count,
    output logic                           overflow,
    output logic                           wr_rst_busy,
    output logic                           almost_full,
    output logic                           wr_ack,
    input  logic                           rd_en,
    output logic [READ_DATA_WIDTH-1:0]     dout,
    output logic                           empty,
    output logic                           prog_empty,
    output logic [RD_DATA_COUNT_WIDTH-1:0] rd_data_count,
    output logic                           underflow,
    output logic                           rd_rst_busy,
    output logic                           almost_empty,
    output logic                           data_valid,
    input  logic                           injectsbiterr,
    input  logic                           injectdbiterr,
    output logic                           sbiterr,
    output logic                           dbiterr
);
  initial begin
    if (READ_MODE != "fwft" || READ_DATA_WIDTH != WRITE_DATA_WIDTH)
      $fatal(1, "The FIFO model covers first-word-fall-through FIFOs of one width");
  end

  prism_sim_fifo #(.WIDTH(WRITE_DATA_WIDTH), .DEPTH(FIFO_WRITE_DEPTH)) u_fifo (
      .wr_clk(wr_clk), .rd_clk(wr_clk), .rst(rst),
      .wr_en(wr_en), .din(din), .full(full),
      .rd_en(rd_en), .dout(dout), .empty(empty)
  );

  assign data_valid = !empty;
  assign {prog_full, overflow, wr_rst_busy, almost_full, wr_ack} = '0;
  assign {prog_empty, underflow, rd_rst_busy, almost_empty, sbiterr, dbiterr} = '0;
  assign wr_data_count = '0;
  assign rd_data_count = '0;
endmodule

module xpm_fifo_async #(
    parameter int CASCADE_HEIGHT = 0,
    parameter int CDC_SYNC_STAGES = 2,
    parameter string DOUT_RESET_VALUE = "0",
    parameter string ECC_MODE = "no_ecc",
    parameter string FIFO_MEMORY_TYPE = "auto",
    parameter int FIFO_READ_LATENCY = 1,
    parameter int FIFO_WRITE_DEPTH = 2048,
    parameter int FULL_RESET_VALUE = 0,
    parameter int PROG_EMPTY_THRESH = 10,
    parameter int PROG_FULL_THRESH = 10,
    parameter int RD_DATA_COUNT_WIDTH = 1,
    parameter int READ_DATA_WIDTH = 32,
    parameter string READ_MODE = "std",
    parameter int RELATED_CLOCKS = 0,
    parameter int SIM_ASSERT_CHK = 0,
    parameter string USE_ADV_FEATURES = "0707",
    parameter int WAKEUP_TIME = 0,
    parameter int WRITE_DATA_WIDTH = 32,
    parameter int WR_DATA_COUNT_WIDTH = 1
) (
    input  logic                           sleep,
    input  logic                           rst,
    input  logic                           wr_clk,
    input  logic                           wr_en,
    input  logic [WRITE_DATA_WIDTH-1:0]    din,
    output logic                           full,
    output logic                           prog_full,
    output logic [WR_DATA_COUNT_WIDTH-1:0] wr_data_count,
    output logic                           overflow,
    output logic                           wr_rst_busy,
    output logic                           almost_full,
    output logic                           wr_ack,
    input  logic                           rd_clk,
    input  logic                           rd_en,
    output logic [READ_DATA_WIDTH-1:0]     dout,
    output logic                           empty,
    output logic                           prog_empty,
    output logic [RD_DATA_COUNT_WIDTH-1:0] rd_data_count,
    output logic                           underflow,
    output logic                           rd_rst_busy,
    output logic                           almost_empty,
    output logic                           data_valid,
    input  logic                           injectsbiterr,
    input  logic                           injectdbiterr,
    output logic                           sbiterr,
    output logic                           dbiterr
);
  initial begin
    if (READ_MODE != "fwft" || READ_DATA_WIDTH != WRITE_DATA_WIDTH)
      $fatal(1, "The FIFO model covers first-word-fall-through FIFOs of one width");
  end

  prism_sim_fifo #(.WIDTH(WRITE_DATA_WIDTH), .DEPTH(FIFO_WRITE_DEPTH)) u_fifo (
      .wr_clk(wr_clk), .rd_clk(rd_clk), .rst(rst),
      .wr_en(wr_en), .din(din), .full(full),
      .rd_en(rd_en), .dout(dout), .empty(empty)
  );

  assign data_valid = !empty;
  assign {prog_full, overflow, wr_rst_busy, almost_full, wr_ack} = '0;
  assign {prog_empty, underflow, rd_rst_busy, almost_empty, sbiterr, dbiterr} = '0;
  assign wr_data_count = '0;
  assign rd_data_count = '0;
endmodule

module xpm_fifo_axis #(
    parameter int CASCADE_HEIGHT = 0,
    parameter int CDC_SYNC_STAGES = 2,
    parameter string CLOCKING_MODE = "common_clock",
    parameter string ECC_MODE = "no_ecc",
    parameter int FIFO_DEPTH = 2048,
    parameter string FIFO_MEMORY_TYPE = "auto",
    parameter string PACKET_FIFO = "false",
    parameter int PROG_EMPTY_THRESH = 10,
    parameter int PROG_FULL_THRESH = 10,
    parameter int RD_DATA_COUNT_WIDTH = 1,
    parameter int RELATED_CLOCKS = 0,
    parameter int SIM_ASSERT_CHK = 0,
    parameter int TDATA_WIDTH = 32,
    parameter int TDEST_WIDTH = 1,
    parameter int TID_WIDTH = 1,
    parameter int TUSER_WIDTH = 1,
    parameter string USE_ADV_FEATURES = "1000",
    parameter int WR_DATA_COUNT_WIDTH = 1
) (
    input  logic                           s_aclk,
    input  logic                           m_aclk,
    input  logic                           s_aresetn,
    input  logic                           s_axis_tvalid,
    output logic                           s_axis_tready,
    input  logic [TDATA_WIDTH-1:0]         s_axis_tdata,
    input  logic [TDATA_WIDTH/8-1:0]       s_axis_tkeep,
    input  logic [TDATA_WIDTH/8-1:0]       s_axis_tstrb,
    input  logic                           s_axis_tlast,
    input  logic [TID_WIDTH-1:0]           s_axis_tid,
    input  logic [TDEST_WIDTH-1:0]         s_axis_tdest,
    input  logic [TUSER_WIDTH-1:0]         s_axis_tuser,
    output logic                           m_axis_tvalid,
    input  logic                           m_axis_tready,
    output logic [TDATA_WIDTH-1:0]         m_axis_tdata,
    output logic [TDATA_WIDTH/8-1:0]       m_axis_tkeep,
    output logic [TDATA_WIDTH/8-1:0]       m_axis_tstrb,
    output logic                           m_axis_tlast,
    output logic [TID_WIDTH-1:0]           m_axis_tid,
    output logic [TDEST_WIDTH-1:0]         m_axis_tdest,
    output logic [TUSER_WIDTH-1:0]         m_axis_tuser,
    output logic                           almost_empty_axis,
    output logic                           prog_empty_axis,
    output logic                           almost_full_axis,
    output logic                           prog_full_axis,
    output logic [WR_DATA_COUNT_WIDTH-1:0] wr_data_count_axis,
    output logic [RD_DATA_COUNT_WIDTH-1:0] rd_data_count_axis,
    input  logic                           injectsbiterr_axis,
    input  logic                           injectdbiterr_axis,
    output logic                           sbiterr_axis,
    output logic                           dbiterr_axis
);
  localparam int WIDTH = TUSER_WIDTH + TDEST_WIDTH + TID_WIDTH + 1 + TDATA_WIDTH / 4
      + TDATA_WIDTH;

  logic full, empty;

  initial begin
    if (PACKET_FIFO != "false") $fatal(1, "The AXI-Stream FIFO model has no packet mode");
  end

  prism_sim_fifo #(.WIDTH(WIDTH), .DEPTH(FIFO_DEPTH)) u_fifo (
      .wr_clk(s_aclk), .rd_clk(CLOCKING_MODE == "independent_clock" ? m_aclk : s_aclk),
      .rst(!s_aresetn),
      .wr_en(s_axis_tvalid),
      .din({s_axis_tuser, s_axis_tdest, s_axis_tid, s_axis_tlast, s_axis_tstrb,
            s_axis_tkeep, s_axis_tdata}),
      .full(full),
      .rd_en(m_axis_tready),
      .dout({m_axis_tuser, m_axis_tdest, m_axis_tid, m_axis_tlast, m_axis_tstrb,
             m_axis_tkeep, m_axis_tdata}),
      .empty(empty)
  );

  assign s_axis_tready = !full && s_aresetn;
  assign m_axis_tvalid = !empty;
  assign {almost_empty_axis, prog_empty_axis, almost_full_axis, prog_full_axis} = '0;
  assign {sbiterr_axis, dbiterr_axis} = '0;
  assign wr_data_count_axis = '0;
  assign rd_data_count_axis = '0;
endmodule

module xpm_memory_sdpram #(
    parameter int ADDR_WIDTH_A = 6,
    parameter int ADDR_WIDTH_B = 6,
    parameter int AUTO_SLEEP_TIME = 0,
    parameter int BYTE_WRITE_WIDTH_A = 32,
    parameter int CASCADE_HEIGHT = 0,
    parameter string CLOCKING_MODE = "common_clock",
    parameter string ECC_MODE = "no_ecc",
    parameter string MEMORY_INIT_FILE = "none",
    parameter string MEMORY_INIT_PARAM = "0",
    parameter string MEMORY_OPTIMIZATION = "true",
    parameter string MEMORY_PRIMITIVE = "auto",
    parameter int MEMORY_SIZE = 2048,
    parameter int MESSAGE_CONTROL = 0,
    parameter int READ_DATA_WIDTH_B = 32,
    parameter int READ_LATENCY_B = 2,
    parameter string READ_RESET_VALUE_B = "0",
    parameter string RST_MODE_A = "SYNC",
    parameter string RST_MODE_B = "SYNC",
    parameter int SIM_ASSERT_CHK = 0,
    parameter int USE_EMBEDDED_CONSTRAINT = 0,
    parameter int USE_MEM_INIT = 1,
    parameter string WAKEUP_TIME = "disable_sleep",
    parameter int WRITE_DATA_WIDTH_A = 32,
    parameter string WRITE_MODE_B = "no_change"
) (
    input  logic                                       clka,
    input  logic                                       ena,
    input  logic [WRITE_DATA_WIDTH_A/BYTE_WRITE_WIDTH_A-1:0] wea,
    input  logic [ADDR_WIDTH_A-1:0]                    addra,
    input  logic [WRITE_DATA_WIDTH_A-1:0]              dina,
    input  logic                                       injectsbiterra,
    input  logic                                       injectdbiterra,
    input  logic                                       clkb,
    input  logic                                       rstb,
    input  logic                                       enb,
    input  logic                                       regceb,
    input  logic [ADDR_WIDTH_B-1:0]                    addrb,
    output logic [READ_DATA_WIDTH_B-1:0]               doutb,
    output logic                                       sbiterrb,
    output logic                                       dbiterrb,
    input  logic                                       sleep
);
  localparam int WORDS = MEMORY_SIZE / WRITE_DATA_WIDTH_A;

  logic [WRITE_DATA_WIDTH_A-1:0] words [WORDS];
  logic [READ_DATA_WIDTH_B-1:0] first = '0;

  initial begin
    if (READ_DATA_WIDTH_B != WRITE_DATA_WIDTH_A || BYTE_WRITE_WIDTH_A != WRITE_DATA_WIDTH_A
        || CLOCKING_MODE != "common_clock" || READ_LATENCY_B < 1 || READ_LATENCY_B > 2)
      $fatal(1, "The RAM model covers one clock, whole-word writes and a read latency of 1 or 2");
  end

  always @(posedge clka) begin
    if (ena && wea[0]) words[addra] <= dina;
  end

  if (READ_LATENCY_B == 1) begin : gen_one
    always @(posedge clkb) begin
      if (rstb) doutb <= '0;
      else if (enb) doutb <= words[addrb];
    end
  end else begin : gen_two
    always @(posedge clkb) begin
      if (enb) first <= words[addrb];
      if (rstb) doutb <= '0;
      else if (regceb) doutb <= first;
    end
  end

  assign {sbiterrb, dbiterrb} = '0;
endmodule
