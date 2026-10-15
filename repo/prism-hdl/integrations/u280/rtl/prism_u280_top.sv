//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_u280_top.sv
// Module: prism_u280_top
// Description: PRISM on the Alveo U280 with the 100G ports and no host interface.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// PRISM is configured in band, so the design needs no PCIe. This top joins
// the collective core to one or two 100G ports with the CMAC subsystem and
// the packet adapter of the OpenNIC shell, both used as they are, and
// supplies what the shell otherwise takes from its host interface: the
// clocks, the power-on reset and the register writes that enable the MAC.
//
// Per port:
//
//   QSFP <-> cmac_subsystem <-> packet_adapter <-> prism_collective_core
//            (cmac_clk)         (clock crossing)   (axis_aclk, 250 MHz)
//
// The top is compiled with the shell's defines __synthesis__ and __au280__.
// Without __synthesis__ the shell's CMAC subsystem has no transceivers and no
// MAC: its frames enter and leave through plain stream ports in the clock of
// the MAC, and this top exposes those ports in place of the QSFP pins, so a
// testbench can drive the whole board design with frames.
module prism_u280_top #(
    parameter int unsigned NUM_PORTS = 1,
    parameter logic [47:0] LOCAL_MAC_BASE = 48'h02_50_52_49_53_00,
    parameter logic [47:0] MANAGER_MAC = 48'h02_50_52_49_53_ff,
    parameter logic [15:0] LINK_MTU = 16'd1500,
    parameter bit LABORATORY_EXTENSION_ENABLED = 1'b1,
    parameter int unsigned KULISCH_W = 280,
    parameter int unsigned MAX_KULISCH_BITS = 280,
    parameter int unsigned MAX_ORIGINAL_TERMS = 2,
    parameter int unsigned MAX_CHILDREN = 2,
    parameter int unsigned EXACT_BANKS = 4,
    parameter bit ENABLE_FP32_ACCUMULATION = 1'b0,
    // 125 MHz cycles between two looks at the receiver status: 1 ms.
    parameter int unsigned LINK_POLL_CYCLES = 125000,
    // RS-FEC on the 100G links; the far end of each link must use the same.
    parameter bit RS_FEC = 1'b1
) (
    // Free-running 100 MHz board clock.
    input  logic                   sysclk_p,
    input  logic                   sysclk_n,
`ifdef __synthesis__
    input  logic [NUM_PORTS-1:0]   qsfp_refclk_p,
    input  logic [NUM_PORTS-1:0]   qsfp_refclk_n,
    input  logic [4*NUM_PORTS-1:0] qsfp_rxp,
    input  logic [4*NUM_PORTS-1:0] qsfp_rxn,
    output logic [4*NUM_PORTS-1:0] qsfp_txp,
    output logic [4*NUM_PORTS-1:0] qsfp_txn,
`else
    // Frames as the MAC would receive and send them, in its clock.
    output logic [NUM_PORTS-1:0]     sim_cmac_clk,
    input  logic [NUM_PORTS-1:0]     sim_rx_tvalid,
    input  logic [512*NUM_PORTS-1:0] sim_rx_tdata,
    input  logic [64*NUM_PORTS-1:0]  sim_rx_tkeep,
    input  logic [NUM_PORTS-1:0]     sim_rx_tlast,
    input  logic [NUM_PORTS-1:0]     sim_rx_tuser_err,
    output logic [NUM_PORTS-1:0]     sim_tx_tvalid,
    output logic [512*NUM_PORTS-1:0] sim_tx_tdata,
    output logic [64*NUM_PORTS-1:0]  sim_tx_tkeep,
    output logic [NUM_PORTS-1:0]     sim_tx_tlast,
    output logic [NUM_PORTS-1:0]     sim_tx_tuser_err,
    input  logic [NUM_PORTS-1:0]     sim_tx_tready,
    // The bring-up of each MAC has enabled its transmitter.
    output logic [NUM_PORTS-1:0]     sim_link_up,
`endif
    // Must be driven low: a floating pin can shut the board down for good.
    output logic                   hbm_cattrip
);

  localparam int unsigned MIN_PKT_LEN = 64;
  localparam int unsigned MAX_PKT_LEN = 1518;

  logic axis_aclk, axil_aclk, powerup_rstn;
  logic [NUM_PORTS-1:0] cmac_clk;
  logic [NUM_PORTS-1:0] cmac_rstn, cmac_rst_done, adapter_rst_done, link_up;
  logic [2:0] started;
  logic adapter_rstn;
  logic [1:0] core_reset_sync;
  logic core_rst_n;
  logic [17:0] millisecond_counter;
  logic millisecond_tick;

  logic [NUM_PORTS*48-1:0] local_macs;
  logic [511:0] core_rx_data [0:NUM_PORTS-1];
  logic [63:0] core_rx_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] core_rx_last, core_rx_valid, core_rx_ready;
  logic [0:0] core_rx_user [0:NUM_PORTS-1];
  logic [511:0] core_tx_data [0:NUM_PORTS-1];
  logic [63:0] core_tx_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] core_tx_last, core_tx_valid, core_tx_ready;
  logic [0:0] core_tx_user [0:NUM_PORTS-1];
  logic [15:0] core_tx_frame_bytes [0:NUM_PORTS-1];

  initial begin
    if (NUM_PORTS < 1 || NUM_PORTS > 2) $fatal(1, "The U280 has one or two 100G ports");
  end

  OBUF u_hbm_cattrip (.I(1'b0), .O(hbm_cattrip));

  prism_u280_clocks u_clocks (
      .sysclk_p(sysclk_p), .sysclk_n(sysclk_n),
      .axis_aclk(axis_aclk), .axil_aclk(axil_aclk), .powerup_rstn(powerup_rstn)
  );

  // The reset blocks of the shell start idle and act on a request: a low
  // pulse of one cycle. The adapters get theirs once after power-on; each
  // CMAC gets its own from its bring-up sequencer.
  always_ff @(posedge axil_aclk) begin
    if (!powerup_rstn) started <= '0;
    else started <= {started[1:0], 1'b1};
  end
  assign adapter_rstn = !(started[1] && !started[2]);

  // The core leaves its reset when the adapters have finished theirs. The
  // 125 MHz and 250 MHz clocks are phase aligned, so the flag is taken as it
  // is; the two registers only keep the reset a registered signal.
  always_ff @(posedge axis_aclk) begin
    core_reset_sync <= {core_reset_sync[0], powerup_rstn && (&adapter_rst_done)};
  end
  assign core_rst_n = core_reset_sync[1];

  always_ff @(posedge axis_aclk) begin
    if (!core_rst_n) begin
      millisecond_counter <= '0;
      millisecond_tick <= 1'b0;
    end else if (millisecond_counter == 18'd249999) begin
      millisecond_counter <= '0;
      millisecond_tick <= 1'b1;
    end else begin
      millisecond_counter <= millisecond_counter + 1'b1;
      millisecond_tick <= 1'b0;
    end
  end

  for (genvar port = 0; port < NUM_PORTS; port++) begin : cmac_port
    logic        cmac_awvalid, cmac_awready, cmac_wvalid, cmac_wready;
    logic        cmac_bvalid, cmac_bready, cmac_arvalid, cmac_arready;
    logic        cmac_rvalid, cmac_rready;
    logic [31:0] cmac_awaddr, cmac_wdata, cmac_araddr, cmac_rdata;
    logic [1:0]  cmac_bresp, cmac_rresp;

    logic         cmac_tx_valid, cmac_tx_last, cmac_tx_error, cmac_tx_ready;
    logic [511:0] cmac_tx_data;
    logic [63:0]  cmac_tx_keep;
    logic         cmac_rx_valid, cmac_rx_last, cmac_rx_error;
    logic [511:0] cmac_rx_data;
    logic [63:0]  cmac_rx_keep;

    logic [15:0] rx_size, rx_source, rx_destination;
    logic        unused_adapter;
    logic [31:0] unused_adapter_data;
    logic [1:0]  unused_adapter_bresp, unused_adapter_rresp;
    logic        unused_adapter_awready, unused_adapter_wready, unused_adapter_bvalid;
    logic        unused_adapter_arready, unused_adapter_rvalid;
    assign unused_adapter = ^{rx_size, rx_source, rx_destination, unused_adapter_data,
        unused_adapter_bresp, unused_adapter_rresp, unused_adapter_awready,
        unused_adapter_wready, unused_adapter_bvalid, unused_adapter_arready,
        unused_adapter_rvalid, core_tx_user[port]};

    assign local_macs[port*48 +: 48] = LOCAL_MAC_BASE;
    assign core_rx_user[port] = 1'b0;

    prism_cmac_bringup #(.POLL_CYCLES(LINK_POLL_CYCLES), .RS_FEC(RS_FEC)) u_bringup (
        .clk(axil_aclk), .rst_n(powerup_rstn),
        .m_reset_n(cmac_rstn[port]), .s_reset_done(cmac_rst_done[port]),
        .m_awvalid(cmac_awvalid), .m_awaddr(cmac_awaddr), .m_awready(cmac_awready),
        .m_wvalid(cmac_wvalid), .m_wdata(cmac_wdata), .m_wready(cmac_wready),
        .m_bvalid(cmac_bvalid), .m_bresp(cmac_bresp), .m_bready(cmac_bready),
        .m_arvalid(cmac_arvalid), .m_araddr(cmac_araddr), .m_arready(cmac_arready),
        .m_rvalid(cmac_rvalid), .m_rdata(cmac_rdata), .m_rresp(cmac_rresp),
        .m_rready(cmac_rready),
        .m_link_up(link_up[port])
    );

    cmac_subsystem #(
        .CMAC_ID(port), .MIN_PKT_LEN(MIN_PKT_LEN), .MAX_PKT_LEN(MAX_PKT_LEN)
    ) cmac_subsystem_inst (
        .s_axil_awvalid(cmac_awvalid), .s_axil_awaddr(cmac_awaddr),
        .s_axil_awready(cmac_awready),
        .s_axil_wvalid(cmac_wvalid), .s_axil_wdata(cmac_wdata), .s_axil_wready(cmac_wready),
        .s_axil_bvalid(cmac_bvalid), .s_axil_bresp(cmac_bresp), .s_axil_bready(cmac_bready),
        .s_axil_arvalid(cmac_arvalid), .s_axil_araddr(cmac_araddr),
        .s_axil_arready(cmac_arready),
        .s_axil_rvalid(cmac_rvalid), .s_axil_rdata(cmac_rdata), .s_axil_rresp(cmac_rresp),
        .s_axil_rready(cmac_rready),

        .s_axis_cmac_tx_tvalid(cmac_tx_valid), .s_axis_cmac_tx_tdata(cmac_tx_data),
        .s_axis_cmac_tx_tkeep(cmac_tx_keep), .s_axis_cmac_tx_tlast(cmac_tx_last),
        .s_axis_cmac_tx_tuser_err(cmac_tx_error), .s_axis_cmac_tx_tready(cmac_tx_ready),

        .m_axis_cmac_rx_tvalid(cmac_rx_valid), .m_axis_cmac_rx_tdata(cmac_rx_data),
        .m_axis_cmac_rx_tkeep(cmac_rx_keep), .m_axis_cmac_rx_tlast(cmac_rx_last),
        .m_axis_cmac_rx_tuser_err(cmac_rx_error),

`ifdef __synthesis__
        .gt_rxp(qsfp_rxp[port*4 +: 4]), .gt_rxn(qsfp_rxn[port*4 +: 4]),
        .gt_txp(qsfp_txp[port*4 +: 4]), .gt_txn(qsfp_txn[port*4 +: 4]),
        .gt_refclk_p(qsfp_refclk_p[port]), .gt_refclk_n(qsfp_refclk_n[port]),
`else
        .m_axis_cmac_tx_sim_tvalid(sim_tx_tvalid[port]),
        .m_axis_cmac_tx_sim_tdata(sim_tx_tdata[port*512 +: 512]),
        .m_axis_cmac_tx_sim_tkeep(sim_tx_tkeep[port*64 +: 64]),
        .m_axis_cmac_tx_sim_tlast(sim_tx_tlast[port]),
        .m_axis_cmac_tx_sim_tuser_err(sim_tx_tuser_err[port]),
        .m_axis_cmac_tx_sim_tready(sim_tx_tready[port]),
        .s_axis_cmac_rx_sim_tvalid(sim_rx_tvalid[port]),
        .s_axis_cmac_rx_sim_tdata(sim_rx_tdata[port*512 +: 512]),
        .s_axis_cmac_rx_sim_tkeep(sim_rx_tkeep[port*64 +: 64]),
        .s_axis_cmac_rx_sim_tlast(sim_rx_tlast[port]),
        .s_axis_cmac_rx_sim_tuser_err(sim_rx_tuser_err[port]),
`endif

        .cmac_clk(cmac_clk[port]),
        .mod_rstn(cmac_rstn[port]), .mod_rst_done(cmac_rst_done[port]),
        .axil_aclk(axil_aclk)
    );

    // The adapter drops a frame whose destination does not name its port,
    // and takes the length of a frame from the size beside it. Its
    // registers are counters only and stay unread.
    packet_adapter #(
        .CMAC_ID(port), .MIN_PKT_LEN(MIN_PKT_LEN), .MAX_PKT_LEN(MAX_PKT_LEN)
    ) packet_adapter_inst (
        .s_axil_awvalid(1'b0), .s_axil_awaddr(32'd0), .s_axil_awready(unused_adapter_awready),
        .s_axil_wvalid(1'b0), .s_axil_wdata(32'd0), .s_axil_wready(unused_adapter_wready),
        .s_axil_bvalid(unused_adapter_bvalid), .s_axil_bresp(unused_adapter_bresp),
        .s_axil_bready(1'b1),
        .s_axil_arvalid(1'b0), .s_axil_araddr(32'd0), .s_axil_arready(unused_adapter_arready),
        .s_axil_rvalid(unused_adapter_rvalid), .s_axil_rdata(unused_adapter_data),
        .s_axil_rresp(unused_adapter_rresp), .s_axil_rready(1'b1),

        .s_axis_tx_tvalid(core_tx_valid[port]), .s_axis_tx_tdata(core_tx_data[port]),
        .s_axis_tx_tkeep(core_tx_keep[port]), .s_axis_tx_tlast(core_tx_last[port]),
        .s_axis_tx_tuser_size(core_tx_frame_bytes[port]), .s_axis_tx_tuser_src(16'd0),
        .s_axis_tx_tuser_dst(16'(1 << (6 + port))), .s_axis_tx_tready(core_tx_ready[port]),

        .m_axis_tx_tvalid(cmac_tx_valid), .m_axis_tx_tdata(cmac_tx_data),
        .m_axis_tx_tkeep(cmac_tx_keep), .m_axis_tx_tlast(cmac_tx_last),
        .m_axis_tx_tuser_err(cmac_tx_error), .m_axis_tx_tready(cmac_tx_ready),

        .s_axis_rx_tvalid(cmac_rx_valid), .s_axis_rx_tdata(cmac_rx_data),
        .s_axis_rx_tkeep(cmac_rx_keep), .s_axis_rx_tlast(cmac_rx_last),
        .s_axis_rx_tuser_err(cmac_rx_error),

        .m_axis_rx_tvalid(core_rx_valid[port]), .m_axis_rx_tdata(core_rx_data[port]),
        .m_axis_rx_tkeep(core_rx_keep[port]), .m_axis_rx_tlast(core_rx_last[port]),
        .m_axis_rx_tuser_size(rx_size), .m_axis_rx_tuser_src(rx_source),
        .m_axis_rx_tuser_dst(rx_destination), .m_axis_rx_tready(core_rx_ready[port]),

        .mod_rstn(adapter_rstn), .mod_rst_done(adapter_rst_done[port]),
        .axil_aclk(axil_aclk), .axis_aclk(axis_aclk), .cmac_clk(cmac_clk[port])
    );
  end

  prism_collective_core #(
      .NUM_PORTS(NUM_PORTS), .MANAGER_MAC(MANAGER_MAC), .LINK_MTU(LINK_MTU),
      .KULISCH_W(KULISCH_W), .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS), .MAX_CHILDREN(MAX_CHILDREN),
      .EXACT_BANKS(EXACT_BANKS),
      .ENABLE_FP32_ACCUMULATION(ENABLE_FP32_ACCUMULATION)
  ) u_core (
      .clk(axis_aclk),
      .rst_n(core_rst_n),
      .millisecond_tick(millisecond_tick),
      .local_macs(local_macs),
      .laboratory_extension_enabled(LABORATORY_EXTENSION_ENABLED),
      .s_axis_tdata(core_rx_data),
      .s_axis_tkeep(core_rx_keep),
      .s_axis_tlast(core_rx_last),
      .s_axis_tuser(core_rx_user),
      .s_axis_tvalid(core_rx_valid),
      .s_axis_tready(core_rx_ready),
      .m_axis_tdata(core_tx_data),
      .m_axis_tkeep(core_tx_keep),
      .m_axis_tlast(core_tx_last),
      .m_axis_tuser(core_tx_user),
      .m_axis_tvalid(core_tx_valid),
      .m_axis_frame_bytes(core_tx_frame_bytes),
      .m_axis_tready(core_tx_ready)
  );

  // The state of the links is kept for a debug probe; nothing in the design
  // waits for it, since a frame sent before the link is up is simply lost.
  (* keep = "true" *) logic [NUM_PORTS-1:0] link_up_reg;
  always_ff @(posedge axil_aclk) link_up_reg <= link_up;
`ifndef __synthesis__
  assign sim_cmac_clk = cmac_clk;
  assign sim_link_up = link_up_reg;
`endif

endmodule
