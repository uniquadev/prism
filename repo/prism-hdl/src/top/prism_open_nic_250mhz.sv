//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_open_nic_250mhz.sv
// Module: prism_open_nic_250mhz
// Description: Adapts the PRISM core to the OpenNIC 250 MHz plugin interface.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// OpenNIC 250 MHz plugin that replaces the stock p2p block without changing the shell.
// Network ports feed PRISM; QDMA interfaces are terminated explicitly.
module prism_open_nic_250mhz #(
  parameter int NUM_QDMA = 1,
  parameter int NUM_INTF = 2,
  parameter logic [47:0] LOCAL_MAC_BASE = 48'h02_50_52_49_53_00,
  parameter bit LABORATORY_EXTENSION_ENABLED = 1'b1
) (
  // AXI-Lite management windows
  input        [NUM_INTF*2-1:0] s_axil_awvalid,
  input     [32*NUM_INTF*2-1:0] s_axil_awaddr,
  output       [NUM_INTF*2-1:0] s_axil_awready,
  input        [NUM_INTF*2-1:0] s_axil_wvalid,
  input     [32*NUM_INTF*2-1:0] s_axil_wdata,
  output       [NUM_INTF*2-1:0] s_axil_wready,
  output       [NUM_INTF*2-1:0] s_axil_bvalid,
  output     [2*NUM_INTF*2-1:0] s_axil_bresp,
  input        [NUM_INTF*2-1:0] s_axil_bready,
  input        [NUM_INTF*2-1:0] s_axil_arvalid,
  input     [32*NUM_INTF*2-1:0] s_axil_araddr,
  output       [NUM_INTF*2-1:0] s_axil_arready,
  output       [NUM_INTF*2-1:0] s_axil_rvalid,
  output    [32*NUM_INTF*2-1:0] s_axil_rdata,
  output     [2*NUM_INTF*2-1:0] s_axil_rresp,
  input        [NUM_INTF*2-1:0] s_axil_rready,

  // QDMA host-to-card and card-to-host streams
  input      [NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tvalid,
  input  [512*NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tdata,
  input   [64*NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tkeep,
  input      [NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tlast,
  input   [16*NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tuser_size,
  input   [16*NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tuser_src,
  input   [16*NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tuser_dst,
  output     [NUM_INTF*NUM_QDMA-1:0] s_axis_qdma_h2c_tready,

  output     [NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tvalid,
  output [512*NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tdata,
  output  [64*NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tkeep,
  output     [NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tlast,
  output  [16*NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tuser_size,
  output  [16*NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tuser_src,
  output  [16*NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tuser_dst,
  input      [NUM_INTF*NUM_QDMA-1:0] m_axis_qdma_c2h_tready,

  // Network adapter transmit streams
  output     [NUM_INTF-1:0] m_axis_adap_tx_250mhz_tvalid,
  output [512*NUM_INTF-1:0] m_axis_adap_tx_250mhz_tdata,
  output  [64*NUM_INTF-1:0] m_axis_adap_tx_250mhz_tkeep,
  output     [NUM_INTF-1:0] m_axis_adap_tx_250mhz_tlast,
  output  [16*NUM_INTF-1:0] m_axis_adap_tx_250mhz_tuser_size,
  output  [16*NUM_INTF-1:0] m_axis_adap_tx_250mhz_tuser_src,
  output  [16*NUM_INTF-1:0] m_axis_adap_tx_250mhz_tuser_dst,
  input      [NUM_INTF-1:0] m_axis_adap_tx_250mhz_tready,

  // Network adapter receive streams
  input      [NUM_INTF-1:0] s_axis_adap_rx_250mhz_tvalid,
  input  [512*NUM_INTF-1:0] s_axis_adap_rx_250mhz_tdata,
  input   [64*NUM_INTF-1:0] s_axis_adap_rx_250mhz_tkeep,
  input      [NUM_INTF-1:0] s_axis_adap_rx_250mhz_tlast,
  input   [16*NUM_INTF-1:0] s_axis_adap_rx_250mhz_tuser_size,
  input   [16*NUM_INTF-1:0] s_axis_adap_rx_250mhz_tuser_src,
  input   [16*NUM_INTF-1:0] s_axis_adap_rx_250mhz_tuser_dst,
  output     [NUM_INTF-1:0] s_axis_adap_rx_250mhz_tready,

  // Shell clocks and reset handshake
  input                     mod_rstn,
  output                    mod_rst_done,
  input                     axil_aclk,
`ifdef __au55n__
  input                     ref_clk_100mhz,
`elsif __au55c__
  input                     ref_clk_100mhz,
`elsif __au50__
  input                     ref_clk_100mhz,
`elsif __au280__
  input                     ref_clk_100mhz,
`endif
  input                     axis_aclk
);

  // ---------------------------------------------------------------------------
  // Clock-domain reset state and one-millisecond timebase
  // ---------------------------------------------------------------------------

  logic [1:0] axis_reset_sync;
  logic [1:0] axil_reset_sync;
  logic axis_rst_n;
  logic axil_rst_n;
  logic [17:0] millisecond_counter;
  logic millisecond_tick;
  logic [NUM_INTF*48-1:0] local_macs;
  logic [511:0] core_rx_data [0:NUM_INTF-1];
  logic [63:0] core_rx_keep [0:NUM_INTF-1];
  logic [NUM_INTF-1:0] core_rx_last;
  logic [0:0] core_rx_user [0:NUM_INTF-1];
  logic [NUM_INTF-1:0] core_rx_valid;
  logic [NUM_INTF-1:0] core_rx_ready;
  logic [511:0] core_tx_data [0:NUM_INTF-1];
  logic [63:0] core_tx_keep [0:NUM_INTF-1];
  logic [NUM_INTF-1:0] core_tx_last;
  logic [0:0] core_tx_user [0:NUM_INTF-1];
  logic [NUM_INTF-1:0] core_tx_user_flat;
  logic [NUM_INTF-1:0] core_tx_valid;
  logic [NUM_INTF-1:0] core_tx_ready;
  logic [15:0] core_tx_frame_bytes [0:NUM_INTF-1];

  // ---------------------------------------------------------------------------
  // Elaboration checks
  // ---------------------------------------------------------------------------

  initial begin
    if ((NUM_INTF < 1) || (NUM_INTF > 2) || (NUM_QDMA < 1)) begin
      $fatal(1, "PRISM OpenNIC wrapper supports one or two CMAC interfaces");
    end
  end

  // ---------------------------------------------------------------------------
  // Reset synchronization and datapath timebase
  // ---------------------------------------------------------------------------

  always_ff @(posedge axis_aclk or negedge mod_rstn) begin
    if (!mod_rstn) axis_reset_sync <= '0;
    else axis_reset_sync <= {axis_reset_sync[0], 1'b1};
  end
  always_ff @(posedge axil_aclk or negedge mod_rstn) begin
    if (!mod_rstn) axil_reset_sync <= '0;
    else axil_reset_sync <= {axil_reset_sync[0], 1'b1};
  end
  assign axis_rst_n = axis_reset_sync[1];
  assign axil_rst_n = axil_reset_sync[1];
  assign mod_rst_done = axis_rst_n && axil_rst_n;

  always_ff @(posedge axis_aclk) begin
    if (!axis_rst_n) begin
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

  // ---------------------------------------------------------------------------
  // Management adapter
  // ---------------------------------------------------------------------------

  prism_axi_lite_null_slave #(
      .INTERFACES(NUM_INTF*2)
  ) u_axil (
      // Clock and reset
      .clk(axil_aclk),
      .rst_n(axil_rst_n),

      // AXI-Lite write address/data/response channels
      .s_awvalid(s_axil_awvalid),
      .s_awaddr(s_axil_awaddr),
      .s_awready(s_axil_awready),
      .s_wvalid(s_axil_wvalid),
      .s_wdata(s_axil_wdata),
      .s_wready(s_axil_wready),
      .s_bvalid(s_axil_bvalid),
      .s_bresp(s_axil_bresp),
      .s_bready(s_axil_bready),

      // AXI-Lite read address/data channels
      .s_arvalid(s_axil_arvalid),
      .s_araddr(s_axil_araddr),
      .s_arready(s_axil_arready),
      .s_rvalid(s_axil_rvalid),
      .s_rdata(s_axil_rdata),
      .s_rresp(s_axil_rresp),
      .s_rready(s_axil_rready)
  );

  // ---------------------------------------------------------------------------
  // Explicitly terminated QDMA channels
  // ---------------------------------------------------------------------------

  assign s_axis_qdma_h2c_tready = '1;
  assign m_axis_qdma_c2h_tvalid = '0;
  assign m_axis_qdma_c2h_tdata = '0;
  assign m_axis_qdma_c2h_tkeep = '0;
  assign m_axis_qdma_c2h_tlast = '0;
  assign m_axis_qdma_c2h_tuser_size = '0;
  assign m_axis_qdma_c2h_tuser_src = '0;
  assign m_axis_qdma_c2h_tuser_dst = '0;

  // ---------------------------------------------------------------------------
  // OpenNIC flattened streams <-> reusable core arrays
  // ---------------------------------------------------------------------------

  for (genvar port = 0; port < NUM_INTF; port++) begin : gen_ports
    assign local_macs[port*48 +: 48] = LOCAL_MAC_BASE + port;
    assign core_rx_data[port] = s_axis_adap_rx_250mhz_tdata[port*512 +: 512];
    assign core_rx_keep[port] = s_axis_adap_rx_250mhz_tkeep[port*64 +: 64];
    assign core_rx_last[port] = s_axis_adap_rx_250mhz_tlast[port];
    assign core_rx_user[port] = 1'b0;
    assign core_rx_valid[port] = s_axis_adap_rx_250mhz_tvalid[port];
    assign s_axis_adap_rx_250mhz_tready[port] = core_rx_ready[port];

    assign m_axis_adap_tx_250mhz_tdata[port*512 +: 512] = core_tx_data[port];
    assign m_axis_adap_tx_250mhz_tkeep[port*64 +: 64] = core_tx_keep[port];
    assign m_axis_adap_tx_250mhz_tlast[port] = core_tx_last[port];
    assign core_tx_user_flat[port] = core_tx_user[port];
    assign m_axis_adap_tx_250mhz_tuser_size[port*16 +: 16] = core_tx_frame_bytes[port];
    assign m_axis_adap_tx_250mhz_tuser_src[port*16 +: 16] = '0;
    assign m_axis_adap_tx_250mhz_tuser_dst[port*16 +: 16] = 16'(1 << (6 + port));
    assign m_axis_adap_tx_250mhz_tvalid[port] = core_tx_valid[port];
    assign core_tx_ready[port] = m_axis_adap_tx_250mhz_tready[port];
  end

  // ---------------------------------------------------------------------------
  // Reusable PRISM collective core
  // ---------------------------------------------------------------------------

  prism_collective_core #(
      .NUM_PORTS(NUM_INTF)
  ) u_core (
      // Clock, reset, and runtime configuration
      .clk(axis_aclk),
      .rst_n(axis_rst_n),
      .millisecond_tick(millisecond_tick),
      .local_macs(local_macs),
      .laboratory_extension_enabled(LABORATORY_EXTENSION_ENABLED),

      // Network ingress streams
      .s_axis_tdata(core_rx_data),
      .s_axis_tkeep(core_rx_keep),
      .s_axis_tlast(core_rx_last),
      .s_axis_tuser(core_rx_user),
      .s_axis_tvalid(core_rx_valid),
      .s_axis_tready(core_rx_ready),

      // Network egress streams
      .m_axis_tdata(core_tx_data),
      .m_axis_tkeep(core_tx_keep),
      .m_axis_tlast(core_tx_last),
      .m_axis_tuser(core_tx_user),
      .m_axis_tvalid(core_tx_valid),
      .m_axis_frame_bytes(core_tx_frame_bytes),
      .m_axis_tready(core_tx_ready)
  );

  // Shell sidebands that are intentionally outside PRISM's in-band protocol.
  logic unused_shell_sidebands;
  assign unused_shell_sidebands = ^{s_axis_qdma_h2c_tvalid, s_axis_qdma_h2c_tdata,
      s_axis_qdma_h2c_tkeep, s_axis_qdma_h2c_tlast, s_axis_qdma_h2c_tuser_size,
      s_axis_qdma_h2c_tuser_src, s_axis_qdma_h2c_tuser_dst, m_axis_qdma_c2h_tready,
      s_axis_adap_rx_250mhz_tuser_size, s_axis_adap_rx_250mhz_tuser_src,
      s_axis_adap_rx_250mhz_tuser_dst, core_tx_user_flat};

endmodule
