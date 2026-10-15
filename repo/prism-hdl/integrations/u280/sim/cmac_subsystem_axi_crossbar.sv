//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: cmac_subsystem_axi_crossbar.sv
// Module: cmac_subsystem_axi_crossbar
// Description: Simulation model of the AXI-Lite crossbar IP inside the shell's CMAC subsystem.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// The CMAC subsystem of the OpenNIC shell routes its register accesses
// through an AXI crossbar IP: addresses below 0x2000 to the MAC, the others to
// a QSFP placeholder. The board simulation uses this model instead of the IP,
// with the same ports and the same decode, one transaction at a time like the
// IP's shared-address mode. Only simulation reads this file; the build uses
// the IP.
module cmac_subsystem_axi_crossbar (
    input  logic [31:0] s_axi_awaddr,
    input  logic [2:0]  s_axi_awprot,
    input  logic        s_axi_awvalid,
    output logic        s_axi_awready,
    input  logic [31:0] s_axi_wdata,
    input  logic [3:0]  s_axi_wstrb,
    input  logic        s_axi_wvalid,
    output logic        s_axi_wready,
    output logic [1:0]  s_axi_bresp,
    output logic        s_axi_bvalid,
    input  logic        s_axi_bready,
    input  logic [31:0] s_axi_araddr,
    input  logic [2:0]  s_axi_arprot,
    input  logic        s_axi_arvalid,
    output logic        s_axi_arready,
    output logic [31:0] s_axi_rdata,
    output logic [1:0]  s_axi_rresp,
    output logic        s_axi_rvalid,
    input  logic        s_axi_rready,
    output logic [63:0] m_axi_awaddr,
    output logic [5:0]  m_axi_awprot,
    output logic [1:0]  m_axi_awvalid,
    input  logic [1:0]  m_axi_awready,
    output logic [63:0] m_axi_wdata,
    output logic [7:0]  m_axi_wstrb,
    output logic [1:0]  m_axi_wvalid,
    input  logic [1:0]  m_axi_wready,
    input  logic [3:0]  m_axi_bresp,
    input  logic [1:0]  m_axi_bvalid,
    output logic [1:0]  m_axi_bready,
    output logic [63:0] m_axi_araddr,
    output logic [5:0]  m_axi_arprot,
    output logic [1:0]  m_axi_arvalid,
    input  logic [1:0]  m_axi_arready,
    input  logic [63:0] m_axi_rdata,
    input  logic [3:0]  m_axi_rresp,
    input  logic [1:0]  m_axi_rvalid,
    output logic [1:0]  m_axi_rready,
    input  logic        aclk,
    input  logic        aresetn
);

  typedef enum logic [2:0] {IDLE, WRITE, WRITE_RESPONSE, READ, READ_RESPONSE} state_t;
  state_t state;
  logic target;
  logic [31:0] address, data;
  logic aw_sent, w_sent;

  assign m_axi_awaddr = {address, address};
  assign m_axi_araddr = {address, address};
  assign m_axi_wdata = {data, data};
  assign m_axi_awprot = '0;
  assign m_axi_arprot = '0;
  assign m_axi_wstrb = '1;
  assign m_axi_awvalid = state == WRITE && !aw_sent ? (2'b01 << target) : 2'b00;
  assign m_axi_wvalid = state == WRITE && !w_sent ? (2'b01 << target) : 2'b00;
  assign m_axi_bready = state == WRITE_RESPONSE ? (2'b01 << target) : 2'b00;
  assign m_axi_arvalid = state == READ ? (2'b01 << target) : 2'b00;
  assign m_axi_rready = state == READ_RESPONSE ? (2'b01 << target) : 2'b00;

  assign s_axi_awready = state == IDLE && s_axi_awvalid && s_axi_wvalid;
  assign s_axi_wready = s_axi_awready;
  assign s_axi_arready = state == IDLE && !(s_axi_awvalid && s_axi_wvalid) && s_axi_arvalid;

  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      state <= IDLE;
      s_axi_bvalid <= 1'b0;
      s_axi_rvalid <= 1'b0;
      aw_sent <= 1'b0;
      w_sent <= 1'b0;
    end else begin
      if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
      if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
      case (state)
        IDLE: begin
          if (s_axi_awready) begin
            address <= s_axi_awaddr;
            data <= s_axi_wdata;
            target <= s_axi_awaddr >= 32'h2000;
            aw_sent <= 1'b0;
            w_sent <= 1'b0;
            state <= WRITE;
          end else if (s_axi_arready) begin
            address <= s_axi_araddr;
            target <= s_axi_araddr >= 32'h2000;
            state <= READ;
          end
        end
        WRITE: begin
          if (m_axi_awready[target]) aw_sent <= 1'b1;
          if (m_axi_wready[target]) w_sent <= 1'b1;
          if ((aw_sent || m_axi_awready[target]) && (w_sent || m_axi_wready[target]))
            state <= WRITE_RESPONSE;
        end
        WRITE_RESPONSE: begin
          if (m_axi_bvalid[target]) begin
            s_axi_bresp <= m_axi_bresp[target*2 +: 2];
            s_axi_bvalid <= 1'b1;
            state <= IDLE;
          end
        end
        READ: if (m_axi_arready[target]) state <= READ_RESPONSE;
        READ_RESPONSE: begin
          if (m_axi_rvalid[target]) begin
            s_axi_rdata <= m_axi_rdata[target*32 +: 32];
            s_axi_rresp <= m_axi_rresp[target*2 +: 2];
            s_axi_rvalid <= 1'b1;
            state <= IDLE;
          end
        end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
