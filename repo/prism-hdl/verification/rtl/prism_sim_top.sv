//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_sim_top.sv
// Module: prism_sim_top
// Description: Exposes the complete PRISM core to Cocotb simulation.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_sim_top #(
    parameter int unsigned NUM_PORTS = 2,
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_KULISCH_BITS = 4096,
    parameter int unsigned MAX_ORIGINAL_TERMS = 16,
    parameter int unsigned MAX_CHILDREN = 8,
    parameter int unsigned EXACT_BANKS = 8,
    parameter bit ENABLE_FP32_ACCUMULATION = 1'b1
) (
    // Clock, reset, and runtime configuration
    input logic clk,
    input logic rst_n,
    input logic millisecond_tick,
    input logic laboratory_extension_enabled,
    input logic [47:0] local_mac_0,
    input logic [47:0] local_mac_1,

    // Ingress port 0
    input logic [511:0] s0_tdata,
    input logic [63:0] s0_tkeep,
    input logic s0_tlast,
    input logic s0_tuser,
    input logic s0_tvalid,
    output logic s0_tready,

    // Ingress port 1
    input logic [511:0] s1_tdata,
    input logic [63:0] s1_tkeep,
    input logic s1_tlast,
    input logic s1_tuser,
    input logic s1_tvalid,
    output logic s1_tready,

    // Egress port 0
    output logic [511:0] m0_tdata,
    output logic [63:0] m0_tkeep,
    output logic m0_tlast,
    output logic m0_tuser,
    output logic m0_tvalid,
    output logic [15:0] m0_frame_bytes,
    input logic m0_tready,

    // Egress port 1
    output logic [511:0] m1_tdata,
    output logic [63:0] m1_tkeep,
    output logic m1_tlast,
    output logic m1_tuser,
    output logic m1_tvalid,
    output logic [15:0] m1_frame_bytes,
    input logic m1_tready,

    // Verification-only ingress stage probes; no production RTL ports.
    output logic [1:0] debug_data_valid,
    output logic [1:0] debug_data_ready,
    output logic [1:0] debug_reader_valid,
    output logic [1:0] debug_reader_ready,
    output logic [1:0] debug_reader_element_last,
    output logic [1:0] debug_tile_valid,
    output logic [1:0] debug_tile_ready,
    output logic [7:0] debug_tile_count [0:1],
    output logic debug_fast_mode,
    output logic debug_fast_exact,
    output logic [1:0] debug_bank_input_valid,
    output logic [1:0] debug_bank_input_ready,
    output logic [1:0] debug_bank_stage1_valid,
    output logic [1:0] debug_bank_stage2_valid,
    output logic [1:0] debug_bank_stage3_valid,
    output logic [1:0] debug_bank_hazard,
    output logic [1:0] debug_bank_advance
);

  // ---------------------------------------------------------------------------
  // Cocotb scalar ports <-> reusable core arrays
  // ---------------------------------------------------------------------------

  logic [NUM_PORTS*48-1:0] local_macs;
  logic [511:0] s_data [0:NUM_PORTS-1];
  logic [63:0] s_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] s_last, s_valid, s_ready;
  logic [0:0] s_user [0:NUM_PORTS-1];
  logic [511:0] m_data [0:NUM_PORTS-1];
  logic [63:0] m_keep [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] m_last, m_valid, m_ready;
  logic [0:0] m_user [0:NUM_PORTS-1];
  logic [15:0] frame_bytes [0:NUM_PORTS-1];

  initial begin
    if (NUM_PORTS < 1 || NUM_PORTS > 2)
      $fatal(1, "Cocotb scalar wrapper exposes one or two physical ports");
  end

  assign local_macs[47:0] = local_mac_0;
  assign s_data[0] = s0_tdata;
  assign s_keep[0] = s0_tkeep;
  assign s_last[0] = s0_tlast;
  assign s_user[0] = s0_tuser;
  assign s_valid[0] = s0_tvalid;
  assign s0_tready = s_ready[0];
  assign m0_tdata = m_data[0];
  assign m0_tkeep = m_keep[0];
  assign m0_tlast = m_last[0];
  assign m0_tuser = m_user[0];
  assign m0_tvalid = m_valid[0];
  assign m0_frame_bytes = frame_bytes[0];
  assign m_ready[0] = m0_tready;

  if (NUM_PORTS == 2) begin : gen_second_port
    assign local_macs[95:48] = local_mac_1;
    assign s_data[1] = s1_tdata;
    assign s_keep[1] = s1_tkeep;
    assign s_last[1] = s1_tlast;
    assign s_user[1] = s1_tuser;
    assign s_valid[1] = s1_tvalid;
    assign s1_tready = s_ready[1];
    assign m1_tdata = m_data[1];
    assign m1_tkeep = m_keep[1];
    assign m1_tlast = m_last[1];
    assign m1_tuser = m_user[1];
    assign m1_tvalid = m_valid[1];
    assign m1_frame_bytes = frame_bytes[1];
    assign m_ready[1] = m1_tready;
  end else begin : gen_no_second_port
    assign s1_tready = 1'b0;
    assign m1_tdata = '0;
    assign m1_tkeep = '0;
    assign m1_tlast = 1'b0;
    assign m1_tuser = 1'b0;
    assign m1_tvalid = 1'b0;
    assign m1_frame_bytes = '0;
  end

  // ---------------------------------------------------------------------------
  // Device under test
  // ---------------------------------------------------------------------------

  prism_collective_core #(
      .NUM_PORTS(NUM_PORTS),
      .KULISCH_W(KULISCH_W), .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS), .MAX_CHILDREN(MAX_CHILDREN),
      .EXACT_BANKS(EXACT_BANKS),
      .ENABLE_FP32_ACCUMULATION(ENABLE_FP32_ACCUMULATION)
  ) u_core (
      // Clock, reset, and runtime configuration
      .clk(clk),
      .rst_n(rst_n),
      .millisecond_tick(millisecond_tick),
      .local_macs(local_macs),
      .laboratory_extension_enabled(laboratory_extension_enabled),

      // Ingress streams
      .s_axis_tdata(s_data),
      .s_axis_tkeep(s_keep),
      .s_axis_tlast(s_last),
      .s_axis_tuser(s_user),
      .s_axis_tvalid(s_valid),
      .s_axis_tready(s_ready),

      // Egress streams
      .m_axis_tdata(m_data),
      .m_axis_tkeep(m_keep),
      .m_axis_tlast(m_last),
      .m_axis_tuser(m_user),
      .m_axis_tvalid(m_valid),
      .m_axis_frame_bytes(frame_bytes),
      .m_axis_tready(m_ready)
  );

  assign debug_data_valid = 2'(u_core.data_in_valid);
  assign debug_data_ready = 2'(u_core.data_in_ready);
  for (genvar port = 0; port < NUM_PORTS; port++) begin : gen_ingress_probe
    assign debug_reader_valid[port] =
        u_core.u_single.u_ingress.gen_port[port].u_receiver.value_valid;
    assign debug_reader_ready[port] =
        u_core.u_single.u_ingress.gen_port[port].u_receiver.value_ready;
    assign debug_reader_element_last[port] =
        u_core.u_single.u_ingress.gen_port[port].u_receiver.element_last_byte;
    assign debug_tile_valid[port] =
        u_core.u_single.u_ingress.receiver_tile_valid[port];
    assign debug_tile_ready[port] =
        u_core.u_single.u_ingress.receiver_tile_ready[port];
    assign debug_tile_count[port] =
        u_core.u_single.u_ingress.receiver_tile_count[port];
  end
  if (NUM_PORTS == 1) begin : gen_no_second_ingress_probe
    assign debug_reader_valid[1] = 1'b0;
    assign debug_reader_ready[1] = 1'b0;
    assign debug_reader_element_last[1] = 1'b0;
    assign debug_tile_valid[1] = 1'b0;
    assign debug_tile_ready[1] = 1'b0;
    assign debug_tile_count[1] = '0;
  end
  assign debug_fast_mode = u_core.u_single.u_ingress.fast_mode;
  assign debug_fast_exact = u_core.u_single.u_ingress.fast_exact;
  if (NUM_PORTS == 2) begin : gen_bank_probes
    for (genvar port = 0; port < 2; port++) begin : gen_bank_probe
      logic [EXACT_BANKS-1:0] stage1_valid, stage2_valid, stage3_valid;
      logic [EXACT_BANKS-1:0] hazard, advance;
      for (genvar bank = 0; bank < EXACT_BANKS; bank++) begin : gen_stripe_probe
        assign stage1_valid[bank] = u_core.u_single.u_ingress
            .gen_striped_exact.gen_bank[port].u_bank.gen_bank[bank].u_pipeline.stage1_valid;
        assign stage2_valid[bank] = u_core.u_single.u_ingress
            .gen_striped_exact.gen_bank[port].u_bank.gen_bank[bank].u_pipeline.stage2_valid;
        assign stage3_valid[bank] = u_core.u_single.u_ingress
            .gen_striped_exact.gen_bank[port].u_bank.gen_bank[bank].u_pipeline.stage3_valid;
        // A hazard counts when it holds up the tile the bank has in front of it.
        assign hazard[bank] = u_core.u_single.u_ingress
            .gen_striped_exact.gen_bank[port].u_bank.gen_bank[bank].u_pipeline.hazard
            && u_core.u_single.u_ingress
            .gen_striped_exact.gen_bank[port].u_bank.gen_bank[bank].u_pipeline.s_valid;
        assign advance[bank] = u_core.u_single.u_ingress
            .gen_striped_exact.gen_bank[port].u_bank.gen_bank[bank].u_pipeline.advance;
      end
      assign debug_bank_input_valid[port] =
          u_core.u_single.u_ingress.gen_striped_exact.gen_bank[port].u_bank.s_valid;
      assign debug_bank_input_ready[port] =
          u_core.u_single.u_ingress.gen_striped_exact.gen_bank[port].u_bank.s_ready;
      assign debug_bank_stage1_valid[port] = |stage1_valid;
      assign debug_bank_stage2_valid[port] = |stage2_valid;
      assign debug_bank_stage3_valid[port] = |stage3_valid;
      assign debug_bank_hazard[port] = |hazard;
      assign debug_bank_advance[port] = &advance;
    end
  end else begin : gen_no_bank_probes
    assign debug_bank_input_valid = '0;
    assign debug_bank_input_ready = '0;
    assign debug_bank_stage1_valid = '0;
    assign debug_bank_stage2_valid = '0;
    assign debug_bank_stage3_valid = '0;
    assign debug_bank_hazard = '0;
    assign debug_bank_advance = '0;
  end

  // Verification-only elaboration guard: FPGA capacity must reach each receiver.
  for (genvar p = 0; p < NUM_PORTS; p++) begin : check_child_capacity
    initial begin
      if (u_core.u_single.u_ingress.gen_port[p].u_receiver.MAX_CHILDREN
          != ((MAX_CHILDREN < 2) ? 2 : MAX_CHILDREN))
        $fatal(1, "Receiver child capacity does not follow top parameter");
      if (u_core.u_single.u_ingress.gen_port[p].u_receiver.u_window.CONTRIBUTORS
          != ((MAX_CHILDREN < 2) ? 2 : MAX_CHILDREN))
        $fatal(1, "Interval window child capacity does not follow top parameter");
    end
  end

endmodule