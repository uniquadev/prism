//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_ingress_demux.sv
// Module: prism_ingress_demux
// Description: Locks each accepted frame to CONTROL, DATA, or drain/drop.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_ingress_demux #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned USER_W = 1
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_frame_desc_t          s_packet,
    input  prism_pkg::prism_packet_class_e        s_packet_class,
    input  prism_pkg::prism_status_e              s_packet_status,
    input  prism_pkg::prism_ingress_context_t     s_packet_context,
    input  logic                                  s_packet_valid,
    output logic                                  s_packet_ready,
    input  logic [DATA_W-1:0]                     s_axis_tdata,
    input  logic [DATA_W/8-1:0]                   s_axis_tkeep,
    input  logic                                  s_axis_tlast,
    input  logic [USER_W-1:0]                     s_axis_tuser,
    input  logic                                  s_axis_tvalid,
    output logic                                  s_axis_tready,
    output prism_pkg::prism_frame_desc_t          m_control_packet,
    output logic                                  m_control_packet_valid,
    input  logic                                  m_control_packet_ready,
    output logic [DATA_W-1:0]                     m_control_axis_tdata,
    output logic [DATA_W/8-1:0]                   m_control_axis_tkeep,
    output logic                                  m_control_axis_tlast,
    output logic [USER_W-1:0]                     m_control_axis_tuser,
    output logic                                  m_control_axis_tvalid,
    input  logic                                  m_control_axis_tready,
    output prism_pkg::prism_frame_desc_t          m_data_packet,
    output prism_pkg::prism_ingress_context_t     m_data_context,
    output logic                                  m_data_packet_valid,
    input  logic                                  m_data_packet_ready,
    output logic [DATA_W-1:0]                     m_data_axis_tdata,
    output logic [DATA_W/8-1:0]                   m_data_axis_tkeep,
    output logic                                  m_data_axis_tlast,
    output logic [USER_W-1:0]                     m_data_axis_tuser,
    output logic                                  m_data_axis_tvalid,
    input  logic                                  m_data_axis_tready
);

  import prism_pkg::*;

  typedef enum logic [1:0] {TARGET_DROP, TARGET_CONTROL, TARGET_DATA} target_e;
  logic frame_active;
  target_e target;

  assign m_control_packet = s_packet;
  assign m_data_packet = s_packet;
  assign m_data_context = s_packet_context;
  assign m_control_packet_valid = s_packet_valid && !frame_active
      && (s_packet_class == PRISM_PACKET_CONTROL) && (s_packet_status == PRISM_STATUS_OK);
  assign m_data_packet_valid = s_packet_valid && !frame_active
      && (s_packet_class == PRISM_PACKET_DATA) && (s_packet_status == PRISM_STATUS_OK);
  assign s_packet_ready = !frame_active && (
      ((s_packet_class == PRISM_PACKET_CONTROL) && (s_packet_status == PRISM_STATUS_OK)
          && m_control_packet_ready)
      || ((s_packet_class == PRISM_PACKET_DATA) && (s_packet_status == PRISM_STATUS_OK)
          && m_data_packet_ready)
      || !(((s_packet_class == PRISM_PACKET_CONTROL)
              || (s_packet_class == PRISM_PACKET_DATA))
          && (s_packet_status == PRISM_STATUS_OK)));

  assign m_control_axis_tdata = s_axis_tdata;
  assign m_control_axis_tkeep = s_axis_tkeep;
  assign m_control_axis_tlast = s_axis_tlast;
  assign m_control_axis_tuser = s_axis_tuser;
  assign m_control_axis_tvalid = frame_active && (target == TARGET_CONTROL) && s_axis_tvalid;
  assign m_data_axis_tdata = s_axis_tdata;
  assign m_data_axis_tkeep = s_axis_tkeep;
  assign m_data_axis_tlast = s_axis_tlast;
  assign m_data_axis_tuser = s_axis_tuser;
  assign m_data_axis_tvalid = frame_active && (target == TARGET_DATA) && s_axis_tvalid;

  always_comb begin
    case (target)
      TARGET_CONTROL: s_axis_tready = m_control_axis_tready;
      TARGET_DATA: s_axis_tready = m_data_axis_tready;
      default: s_axis_tready = frame_active;
    endcase
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      frame_active <= 1'b0;
      target <= TARGET_DROP;
    end else begin
      if (s_packet_valid && s_packet_ready) begin
        frame_active <= 1'b1;
        if ((s_packet_class == PRISM_PACKET_CONTROL) && (s_packet_status == PRISM_STATUS_OK)) begin
          target <= TARGET_CONTROL;
        end else if ((s_packet_class == PRISM_PACKET_DATA) && (s_packet_status == PRISM_STATUS_OK)) begin
          target <= TARGET_DATA;
        end else begin
          target <= TARGET_DROP;
        end
      end
      if (s_axis_tvalid && s_axis_tready && s_axis_tlast) begin
        frame_active <= 1'b0;
        target <= TARGET_DROP;
      end
    end
  end

endmodule
