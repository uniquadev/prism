//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_collective_core.sv
// Module: prism_collective_core
// Description: Physical-port SINGLE NumberGroup core.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_collective_core #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned NUM_PORTS = 2,
    parameter int unsigned USER_W = 1,
    parameter logic [47:0] MANAGER_MAC = 48'h020000000000,
    parameter logic [15:0] CONTROL_ENDPOINT = 16'hfffe,
    parameter logic [15:0] LINK_MTU = 16'd1500,
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_KULISCH_BITS = 4096,
    parameter int unsigned MAX_ORIGINAL_TERMS = 16,
    parameter int unsigned MAX_CHILDREN = 8,
    parameter int unsigned EXACT_BANKS = 8,
    parameter bit ENABLE_FP32_ACCUMULATION = 1'b1
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         millisecond_tick,
    input  logic [NUM_PORTS*48-1:0]      local_macs,
    input  logic                         laboratory_extension_enabled,
    input  logic [DATA_W-1:0]            s_axis_tdata [0:NUM_PORTS-1],
    input  logic [DATA_W/8-1:0]          s_axis_tkeep [0:NUM_PORTS-1],
    input  logic [NUM_PORTS-1:0]         s_axis_tlast,
    input  logic [USER_W-1:0]            s_axis_tuser [0:NUM_PORTS-1],
    input  logic [NUM_PORTS-1:0]         s_axis_tvalid,
    output logic [NUM_PORTS-1:0]         s_axis_tready,
    output logic [DATA_W-1:0]            m_axis_tdata [0:NUM_PORTS-1],
    output logic [DATA_W/8-1:0]          m_axis_tkeep [0:NUM_PORTS-1],
    output logic [NUM_PORTS-1:0]         m_axis_tlast,
    output logic [USER_W-1:0]            m_axis_tuser [0:NUM_PORTS-1],
    output logic [NUM_PORTS-1:0]         m_axis_tvalid,
    output logic [15:0]                  m_axis_frame_bytes [0:NUM_PORTS-1],
    input  logic [NUM_PORTS-1:0]         m_axis_tready
);

  localparam int unsigned PORT_W = NUM_PORTS > 1 ? $clog2(NUM_PORTS) : 1;

  logic [511:0] control_in_data [0:NUM_PORTS-1];
  logic [63:0] control_in_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] control_in_last, control_in_user;
  logic [NUM_PORTS-1:0] control_in_valid, control_in_ready;
  logic [511:0] data_in_data [0:NUM_PORTS-1];
  logic [63:0] data_in_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] data_in_last, data_in_user;
  logic [NUM_PORTS-1:0] data_in_valid, data_in_ready;
  logic [NUM_PORTS-1:0] dropped;
  // Frames and the station addresses enter through registers at the boundary
  // of the core, so no logic of the core hangs on a port.
  logic [511:0] entry_data [0:NUM_PORTS-1];
  logic [63:0] entry_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] entry_last, entry_user, entry_valid, entry_ready;
  logic [NUM_PORTS*48-1:0] local_macs_reg;
  always_ff @(posedge clk) local_macs_reg <= local_macs;
  // The reset is used two registers after the port: the first takes it from
  // the port, the second can be copied next to each block it resets. While
  // the core is in reset it takes no frame.
  logic reset_entry = 1'b0;
  logic core_rst_n = 1'b0;
  logic [NUM_PORTS-1:0] input_ready;
  always_ff @(posedge clk) begin
    reset_entry <= rst_n;
    core_rst_n <= reset_entry;
  end

  logic [511:0] control_out_data, result_out_data;
  logic [63:0] control_out_keep, result_out_keep;
  logic control_out_last, control_out_user, control_out_valid;
  logic control_out_ready, result_out_last, result_out_valid, result_out_ready;
  logic [15:0] control_out_bytes, result_out_bytes, result_out_port;
  // CONTROL responses as the control plane hands them over, before the
  // buffer in front of the frame arbitration.
  logic [511:0] response_data;
  logic [63:0] response_keep;
  logic response_last, response_user, response_valid, response_ready;
  logic [15:0] response_bytes;
  logic context_installed, context_active, context_complete;
  logic [7:0] result_sent_mask;
  logic result_all_sent, fault;
  logic result_frame_active;
  logic [PORT_W-1:0] result_active_port;
  logic [NUM_PORTS-1:0] select_result, select_control;
  logic unused_signals;
  assign unused_signals = ^{millisecond_tick, laboratory_extension_enabled,
      local_macs_reg, dropped, context_installed,
      context_active, context_complete, result_sent_mask,
      result_all_sent, fault, control_in_last,
      control_in_user, control_in_valid};

  initial begin
    if (DATA_W != 512 || USER_W != 1 || NUM_PORTS < 1 || NUM_PORTS > 8)
      $fatal(1, "SINGLE NumberGroup core requires 1-8 512-bit physical ports");
  end

  for (genvar port = 0; port < NUM_PORTS; port++) begin : gen_ingress
    if (port != 0) begin : gen_unmanaged_port
      assign control_in_ready[port] = 1'b1;
    end
    prism_axis_skid_buffer #(.DATA_W(512), .USER_W(1)) u_input (
        .clk(clk), .rst_n(core_rst_n),
        .s_axis_tdata(s_axis_tdata[port]), .s_axis_tkeep(s_axis_tkeep[port]),
        .s_axis_tlast(s_axis_tlast[port]), .s_axis_tuser(s_axis_tuser[port]),
        .s_axis_tvalid(s_axis_tvalid[port] && core_rst_n),
        .s_axis_tready(input_ready[port]),
        .m_axis_tdata(entry_data[port]), .m_axis_tkeep(entry_keep[port]),
        .m_axis_tlast(entry_last[port]), .m_axis_tuser(entry_user[port]),
        .m_axis_tvalid(entry_valid[port]), .m_axis_tready(entry_ready[port])
    );
    assign s_axis_tready[port] = input_ready[port] && core_rst_n;
    prism_frame_class_router u_router (
        .clk(clk), .rst_n(core_rst_n),
        .s_axis_tdata(entry_data[port]),
        .s_axis_tkeep(entry_keep[port]),
        .s_axis_tlast(entry_last[port]),
        .s_axis_tuser(entry_user[port]),
        .s_axis_tvalid(entry_valid[port]),
        .s_axis_tready(entry_ready[port]),
        .m_control_tdata(control_in_data[port]),
        .m_control_tkeep(control_in_keep[port]),
        .m_control_tlast(control_in_last[port]),
        .m_control_tuser(control_in_user[port]),
        .m_control_tvalid(control_in_valid[port]),
        .m_control_tready(control_in_ready[port]),
        .m_data_tdata(data_in_data[port]),
        .m_data_tkeep(data_in_keep[port]),
        .m_data_tlast(data_in_last[port]),
        .m_data_tuser(data_in_user[port]),
        .m_data_tvalid(data_in_valid[port]),
        .m_data_tready(data_in_ready[port]),
        .m_drop_valid(dropped[port])
    );
  end

  prism_single_native_core #(
      .CONTROL_PORT_INDEX(0), .FIRST_DATA_PORT(0),
      .DATA_PORTS(NUM_PORTS),
      .KULISCH_W(KULISCH_W), .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS), .MAX_CHILDREN(MAX_CHILDREN),
      .EXACT_BANKS(EXACT_BANKS),
      .ENABLE_FP32_ACCUMULATION(ENABLE_FP32_ACCUMULATION)
  ) u_single (
      .clk(clk), .rst_n(core_rst_n),
      .s_control_tdata(control_in_data[0]),
      .s_control_tkeep(control_in_keep[0]),
      .s_control_tlast(control_in_last[0]),
      .s_control_tuser(control_in_user[0]),
      .s_control_tvalid(control_in_valid[0]),
      .s_control_tready(control_in_ready[0]),
      .s_data_tdata(data_in_data), .s_data_tkeep(data_in_keep),
      .s_data_tlast(data_in_last), .s_data_tuser(data_in_user),
      .s_data_tvalid(data_in_valid), .s_data_tready(data_in_ready),
      .s_local_mac(local_macs_reg[47:0]), .s_manager_mac(MANAGER_MAC),
      .s_manager_port(16'd0), .s_control_endpoint(CONTROL_ENDPOINT),
      .s_link_mtu(LINK_MTU),
      .s_usable_port_mask(16'((1 << NUM_PORTS) - 1)),
      .s_shared_port_demux(1'b1),
      .m_control_tdata(response_data),
      .m_control_tkeep(response_keep),
      .m_control_tlast(response_last),
      .m_control_tuser(response_user),
      .m_control_frame_bytes(response_bytes),
      .m_control_tvalid(response_valid),
      .m_control_tready(response_ready),
      .m_result_port(result_out_port),
      .m_result_tdata(result_out_data),
      .m_result_tkeep(result_out_keep),
      .m_result_tlast(result_out_last),
      .m_result_frame_bytes(result_out_bytes),
      .m_result_tvalid(result_out_valid),
      .m_result_tready(result_out_ready),
      .m_context_installed(context_installed),
      .m_context_active(context_active),
      .m_context_complete(context_complete),
      .m_result_sent_mask(result_sent_mask),
      .m_result_all_sent(result_all_sent),
      .m_fault(fault)
  );

  // The responses reach the arbitration through a skid buffer, as the
  // RESULT frames do inside the node: the encoder of the control plane and
  // the output registers of a port sit in different parts of the device.
  prism_axis_skid_buffer #(.DATA_W(512), .USER_W(17)) u_response (
      .clk(clk), .rst_n(core_rst_n),
      .s_axis_tdata(response_data), .s_axis_tkeep(response_keep),
      .s_axis_tlast(response_last), .s_axis_tuser({response_bytes, response_user}),
      .s_axis_tvalid(response_valid), .s_axis_tready(response_ready),
      .m_axis_tdata(control_out_data), .m_axis_tkeep(control_out_keep),
      .m_axis_tlast(control_out_last), .m_axis_tuser({control_out_bytes, control_out_user}),
      .m_axis_tvalid(control_out_valid), .m_axis_tready(control_out_ready)
  );

  always_comb begin
    select_result = '0;
    select_control = '0;
    for (integer port = 0; port < NUM_PORTS; port++) begin
      if (result_frame_active && int'(result_active_port) == port)
        select_result[port] = 1'b1;
      else if (port == 0 && control_out_valid)
        select_control[port] = 1'b1;
      else if (!result_frame_active && result_out_valid
          && int'(result_out_port) == port)
        select_result[port] = 1'b1;
    end
  end

  // Every port leaves through a registered stage, so the frame arbitration
  // above sees a registered ready and the outputs come from registers.
  logic [DATA_W-1:0] port_data [0:NUM_PORTS-1];
  logic [DATA_W/8-1:0] port_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] port_last, port_valid, port_ready;
  logic [USER_W-1:0] port_user [0:NUM_PORTS-1];
  logic [15:0] port_frame_bytes [0:NUM_PORTS-1];

  assign control_out_ready = port_ready[0] && select_control[0];
  always_comb begin
    result_out_ready = 1'b0;
    for (integer port = 0; port < NUM_PORTS; port++) begin
      if (select_result[port]) result_out_ready = port_ready[port];
      port_data[port] = '0;
      port_keep[port] = '0;
      port_last[port] = 1'b0;
      port_user[port] = '0;
      port_frame_bytes[port] = '0;
      port_valid[port] = 1'b0;
      if (select_control[port]) begin
        port_data[port] = control_out_data;
        port_keep[port] = control_out_keep;
        port_last[port] = control_out_last;
        port_user[port] = control_out_user;
        port_frame_bytes[port] = control_out_bytes;
        port_valid[port] = control_out_valid;
      end else if (select_result[port]) begin
        port_data[port] = result_out_data;
        port_keep[port] = result_out_keep;
        port_last[port] = result_out_last;
        port_frame_bytes[port] = result_out_bytes;
        port_valid[port] = result_out_valid;
      end
    end
  end

  for (genvar port = 0; port < NUM_PORTS; port++) begin : gen_egress
    prism_axis_skid_buffer #(.DATA_W(DATA_W), .USER_W(16 + USER_W)) u_output (
        .clk(clk), .rst_n(core_rst_n),
        .s_axis_tdata(port_data[port]), .s_axis_tkeep(port_keep[port]),
        .s_axis_tlast(port_last[port]),
        .s_axis_tuser({port_frame_bytes[port], port_user[port]}),
        .s_axis_tvalid(port_valid[port]), .s_axis_tready(port_ready[port]),
        .m_axis_tdata(m_axis_tdata[port]), .m_axis_tkeep(m_axis_tkeep[port]),
        .m_axis_tlast(m_axis_tlast[port]),
        .m_axis_tuser({m_axis_frame_bytes[port], m_axis_tuser[port]}),
        .m_axis_tvalid(m_axis_tvalid[port]), .m_axis_tready(m_axis_tready[port])
    );
  end
  always_ff @(posedge clk) begin
    if (!core_rst_n) begin
      result_frame_active <= 1'b0;
      result_active_port <= '0;
    end else if (result_out_valid && result_out_ready) begin
      if (result_out_last) result_frame_active <= 1'b0;
      else begin
        result_frame_active <= 1'b1;
        result_active_port <= result_out_port[PORT_W-1:0];
      end
    end
  end

endmodule
