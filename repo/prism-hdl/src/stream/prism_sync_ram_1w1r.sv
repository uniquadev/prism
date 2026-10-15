//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_sync_ram_1w1r.sv
// Module: prism_sync_ram_1w1r
// Description: Inferred synchronous RAM with one write port and one read port.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_sync_ram_1w1r #(
    parameter int unsigned WIDTH = 32,
    parameter int unsigned DEPTH = 16,
    parameter int unsigned ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter bit BLOCK_RAM = 1'b0,
    parameter bit WRITE_FIRST = 1'b0
) (
    input  logic                 clk,
    input  logic                 write_enable,
    input  logic [ADDR_W-1:0]    write_address,
    input  logic [WIDTH-1:0]     write_data,
    input  logic [ADDR_W-1:0]    read_address,
    output logic [WIDTH-1:0]     read_data
);

  initial begin
    if ((WIDTH < 1) || (DEPTH < 2) || (ADDR_W < $clog2(DEPTH))) begin
      $fatal(1, "prism_sync_ram_1w1r parameters are illegal");
    end
  end

  generate
    if (BLOCK_RAM) begin : gen_block_ram
      (* ram_style = "block" *)
      logic [WIDTH-1:0] memory [0:DEPTH-1];
      logic [WIDTH-1:0] memory_read_data;
      logic [WIDTH-1:0] collision_write_data;
      logic collision_write_valid;

      always_ff @(posedge clk) begin
        if (write_enable) memory[write_address] <= write_data;
        memory_read_data <= memory[read_address];
        collision_write_valid <= WRITE_FIRST && write_enable
            && (write_address == read_address);
        collision_write_data <= write_data;
      end

      assign read_data = collision_write_valid
          ? collision_write_data : memory_read_data;
    end else begin : gen_auto_ram
      logic [WIDTH-1:0] memory [0:DEPTH-1];
      always_ff @(posedge clk) begin
        if (write_enable) memory[write_address] <= write_data;
        if (WRITE_FIRST && write_enable
            && (write_address == read_address)) begin
          read_data <= write_data;
        end else begin
          read_data <= memory[read_address];
        end
      end
    end
  endgenerate

endmodule
