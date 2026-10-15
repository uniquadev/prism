//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_frame_class_router.sv
// Module: prism_frame_class_router
// Description: Keep a whole AXI frame on its CONTROL or DATA path.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_frame_class_router #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1
) (
    input  logic                     clk,
    input  logic                     rst_n,
    input  logic [DATA_W-1:0]        s_axis_tdata,
    input  logic [DATA_W/8-1:0]      s_axis_tkeep,
    input  logic                     s_axis_tlast,
    input  logic [USER_W-1:0]        s_axis_tuser,
    input  logic                     s_axis_tvalid,
    output logic                     s_axis_tready,
    output logic [DATA_W-1:0]        m_control_tdata,
    output logic [DATA_W/8-1:0]      m_control_tkeep,
    output logic                     m_control_tlast,
    output logic [USER_W-1:0]        m_control_tuser,
    output logic                     m_control_tvalid,
    input  logic                     m_control_tready,
    output logic [DATA_W-1:0]        m_data_tdata,
    output logic [DATA_W/8-1:0]      m_data_tkeep,
    output logic                     m_data_tlast,
    output logic [USER_W-1:0]        m_data_tuser,
    output logic                     m_data_tvalid,
    input  logic                     m_data_tready,
    output logic                     m_drop_valid
);

  typedef enum logic [2:0] {
    ROUTE_FIRST, ROUTE_CONTROL, ROUTE_DATA, ROUTE_DROP
  } route_t;
  route_t state, selected_route;

  initial begin
    if (DATA_W < 128 || DATA_W % 8 != 0 || USER_W < 1)
      $fatal(1, "PRISM class router requires a byte-aligned first beat");
  end

  always_comb begin
    selected_route = state;
    if (state == ROUTE_FIRST) begin
      selected_route = ROUTE_DROP;
      if (&s_axis_tkeep[15:0]) begin
        case (s_axis_tdata[15*8 +: 8])
          8'h01: selected_route = ROUTE_CONTROL;
          8'h02, 8'h03: selected_route = ROUTE_DATA;
          default: selected_route = ROUTE_DROP;
        endcase
      end
    end
  end

  always_comb begin
    case (selected_route)
      ROUTE_CONTROL: s_axis_tready = m_control_tready;
      ROUTE_DATA: s_axis_tready = m_data_tready;
      default: s_axis_tready = 1'b1;
    endcase
  end

  assign m_control_tdata = s_axis_tdata;
  assign m_control_tkeep = s_axis_tkeep;
  assign m_control_tlast = s_axis_tlast;
  assign m_control_tuser = s_axis_tuser;
  assign m_control_tvalid = s_axis_tvalid && selected_route == ROUTE_CONTROL;
  assign m_data_tdata = s_axis_tdata;
  assign m_data_tkeep = s_axis_tkeep;
  assign m_data_tlast = s_axis_tlast;
  assign m_data_tuser = s_axis_tuser;
  assign m_data_tvalid = s_axis_tvalid && selected_route == ROUTE_DATA;
  assign m_drop_valid = s_axis_tvalid && s_axis_tready && s_axis_tlast
      && selected_route == ROUTE_DROP;

  always_ff @(posedge clk) begin
    if (!rst_n) state <= ROUTE_FIRST;
    else if (s_axis_tvalid && s_axis_tready) begin
      if (s_axis_tlast) state <= ROUTE_FIRST;
      else state <= selected_route;
    end
  end

endmodule
