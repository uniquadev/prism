//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_axi_lite_null_slave.sv
// Module: prism_axi_lite_null_slave
// Description: Terminates OpenNIC AXI-Lite windows with identity registers.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Minimal compliant AXI4-Lite endpoint for the OpenNIC plugin windows.
// PRISM control is in-band: these windows expose read-only identity registers
// and acknowledge writes without modifying datapath state.
module prism_axi_lite_null_slave #(
    parameter int unsigned INTERFACES = 1
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic [INTERFACES-1:0]        s_awvalid,
    input  logic [32*INTERFACES-1:0]     s_awaddr,
    output logic [INTERFACES-1:0]        s_awready,
    input  logic [INTERFACES-1:0]        s_wvalid,
    input  logic [32*INTERFACES-1:0]     s_wdata,
    output logic [INTERFACES-1:0]        s_wready,
    output logic [INTERFACES-1:0]        s_bvalid,
    output logic [2*INTERFACES-1:0]      s_bresp,
    input  logic [INTERFACES-1:0]        s_bready,
    input  logic [INTERFACES-1:0]        s_arvalid,
    input  logic [32*INTERFACES-1:0]     s_araddr,
    output logic [INTERFACES-1:0]        s_arready,
    output logic [INTERFACES-1:0]        s_rvalid,
    output logic [32*INTERFACES-1:0]     s_rdata,
    output logic [2*INTERFACES-1:0]      s_rresp,
    input  logic [INTERFACES-1:0]        s_rready
);

  logic [INTERFACES-1:0] aw_pending;
  logic [INTERFACES-1:0] w_pending;

  initial begin
    if (INTERFACES < 1) $fatal(1, "INTERFACES must be positive");
  end

  always_comb begin
    s_awready = ~aw_pending & ~s_bvalid;
    s_wready = ~w_pending & ~s_bvalid;
    s_arready = ~s_rvalid;
    s_bresp = '0;
    s_rresp = '0;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      aw_pending <= '0;
      w_pending <= '0;
      s_bvalid <= '0;
      s_rvalid <= '0;
      s_rdata <= '0;
    end else begin
      for (int unsigned interface_index = 0;
          interface_index < INTERFACES; interface_index++) begin
        if (s_bvalid[interface_index] && s_bready[interface_index]) begin
          s_bvalid[interface_index] <= 1'b0;
        end
        if (s_awvalid[interface_index] && s_awready[interface_index]) begin
          aw_pending[interface_index] <= 1'b1;
        end
        if (s_wvalid[interface_index] && s_wready[interface_index]) begin
          w_pending[interface_index] <= 1'b1;
        end
        if (!s_bvalid[interface_index]
            && (aw_pending[interface_index]
                || (s_awvalid[interface_index] && s_awready[interface_index]))
            && (w_pending[interface_index]
                || (s_wvalid[interface_index] && s_wready[interface_index]))) begin
          aw_pending[interface_index] <= 1'b0;
          w_pending[interface_index] <= 1'b0;
          s_bvalid[interface_index] <= 1'b1;
        end

        if (s_rvalid[interface_index] && s_rready[interface_index]) begin
          s_rvalid[interface_index] <= 1'b0;
        end
        if (s_arvalid[interface_index] && s_arready[interface_index]) begin
          s_rvalid[interface_index] <= 1'b1;
          case (s_araddr[interface_index*32 +: 8])
            8'h00: s_rdata[interface_index*32 +: 32] <= 32'h5052_4953;
            8'h04: s_rdata[interface_index*32 +: 32] <= 32'h0001_0000;
            default: s_rdata[interface_index*32 +: 32] <= '0;
          endcase
        end
      end
    end
  end

  // Consume address and data explicitly; writes are intentional no-ops.
  logic unused_write_inputs;
  assign unused_write_inputs = ^{s_awaddr, s_wdata};

endmodule
