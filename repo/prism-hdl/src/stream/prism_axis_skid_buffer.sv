//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_axis_skid_buffer.sv
// Module: prism_axis_skid_buffer
// Description: Breaks the AXI ready path with one-word spill storage.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_axis_skid_buffer #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic [DATA_W-1:0]     s_axis_tdata,
    input  logic [DATA_W/8-1:0]   s_axis_tkeep,
    input  logic                  s_axis_tlast,
    input  logic [USER_W-1:0]     s_axis_tuser,
    input  logic                  s_axis_tvalid,
    output logic                  s_axis_tready,
    output logic [DATA_W-1:0]     m_axis_tdata,
    output logic [DATA_W/8-1:0]   m_axis_tkeep,
    output logic                  m_axis_tlast,
    output logic [USER_W-1:0]     m_axis_tuser,
    output logic                  m_axis_tvalid,
    input  logic                  m_axis_tready
);

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned WORD_W = DATA_W + KEEP_W + 1 + USER_W;

  logic [WORD_W-1:0] primary_word;
  logic [WORD_W-1:0] skid_word;
  logic primary_valid;
  logic skid_valid;
  logic [WORD_W-1:0] input_word;
  logic output_fire;
  logic input_fire;

  assign input_word = {s_axis_tuser, s_axis_tlast, s_axis_tkeep, s_axis_tdata};
  assign {m_axis_tuser, m_axis_tlast, m_axis_tkeep, m_axis_tdata} = primary_word;
  assign m_axis_tvalid = primary_valid;
  assign s_axis_tready = !skid_valid;
  assign output_fire = m_axis_tvalid && m_axis_tready;
  assign input_fire = s_axis_tvalid && s_axis_tready;

  initial begin
    if ((DATA_W == 0) || ((DATA_W % 8) != 0)) begin
      $fatal(1, "prism_axis_skid_buffer DATA_W must be a positive multiple of eight");
    end
    if (USER_W == 0) begin
      $fatal(1, "prism_axis_skid_buffer USER_W must be positive");
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      primary_word <= '0;
      skid_word <= '0;
      primary_valid <= 1'b0;
      skid_valid <= 1'b0;
    end else begin
      case ({input_fire, output_fire})
        2'b00: begin
          primary_valid <= primary_valid;
          skid_valid <= skid_valid;
        end
        2'b01: begin
          if (skid_valid) begin
            primary_word <= skid_word;
            primary_valid <= 1'b1;
            skid_valid <= 1'b0;
          end else begin
            primary_valid <= 1'b0;
          end
        end
        2'b10: begin
          if (!primary_valid) begin
            primary_word <= input_word;
            primary_valid <= 1'b1;
          end else begin
            skid_word <= input_word;
            skid_valid <= 1'b1;
          end
        end
        2'b11: begin
          if (skid_valid) begin
            primary_word <= skid_word;
            skid_word <= input_word;
            primary_valid <= 1'b1;
            skid_valid <= 1'b1;
          end else begin
            primary_word <= input_word;
            primary_valid <= 1'b1;
          end
        end
        default: begin
          primary_valid <= 1'b0;
          skid_valid <= 1'b0;
        end
      endcase
    end
  end

endmodule
