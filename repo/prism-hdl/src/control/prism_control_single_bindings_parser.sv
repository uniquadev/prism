//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_single_bindings_parser.sv
// Module: prism_control_single_bindings_parser
// Description: Sequential SINGLE child/result lists and rank-binding precheck.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_single_bindings_parser #(
    parameter int unsigned MAX_CHILDREN = 8
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic [7:0]                      s_child_count,
    input  logic [7:0]                      s_result_count,
    input  logic [7:0]                      s_rank_mask,
    input  logic [7:0]                      s_accepted_mask,
    input  logic [47:0]                     s_manager_mac,
    input  logic [47:0]                     s_local_mac,
    input  logic [15:0]                     s_supported_ports,
    input  logic                            s_shared_port_demux,
    input  logic                            s_valid,
    output logic                            s_ready,
    output logic [15:0]                     m_read_address,
    input  logic [7:0]                      m_read_data,
    output logic [MAX_CHILDREN*16-1:0]      m_local_endpoints,
    output logic [MAX_CHILDREN*16-1:0]      m_peer_endpoints,
    output logic [MAX_CHILDREN*16-1:0]      m_local_ports,
    output logic [MAX_CHILDREN*16-1:0]      m_rank_ids,
    output logic [MAX_CHILDREN*48-1:0]      m_peer_macs,
    output logic [MAX_CHILDREN*8-1:0]       m_native_masks,
    output logic [MAX_CHILDREN-1:0]         m_result_enabled,
    output logic                            m_accept,
    output logic [2:0]                      m_error_code,
    output logic                            m_valid,
    input  logic                            m_ready
);

  typedef enum logic [2:0] {
    IDLE, READ_CHILD, READ_RESULT, READ_BINDING, CHECK_BINDING, STORE_BINDING, REPORT
  } state_t;
  localparam int unsigned INDEX_W = (MAX_CHILDREN < 2) ? 1 : $clog2(MAX_CHILDREN);
  state_t state;
  logic [15:0] cursor;
  logic [7:0] child_count_reg, result_count_reg;
  logic [7:0] rank_mask_reg, accepted_mask_reg;
  logic [47:0] manager_mac_reg, local_mac_reg;
  logic [15:0] supported_ports_reg;
  logic shared_port_demux_reg;
  logic [7:0] child_index, result_index, binding_index, bound_results;
  logic word_low;
  logic [7:0] word_high;
  logic [4:0] binding_byte_index;
  logic [191:0] binding_bytes;
  logic [15:0] child_endpoints [0:MAX_CHILDREN-1];
  logic [15:0] result_endpoints [0:MAX_CHILDREN-1];
  logic [15:0] binding_local, binding_peer, binding_port, binding_rank;
  logic [31:0] binding_terms;
  logic [47:0] binding_mac;
  logic [7:0] binding_kind, binding_flags, binding_mask;
  logic [23:0] binding_reserved;
  logic expected_result, duplicate_rank, duplicate_endpoint, duplicate_port;
  // The verdict on a binding, one cycle before the binding is stored.
  logic binding_rejected;

  function automatic logic [7:0] bbyte(input int unsigned index);
    return binding_bytes[index*8 +: 8];
  endfunction

  function automatic logic [15:0] bbe16(input int unsigned index);
    return {bbyte(index), bbyte(index + 1)};
  endfunction

  function automatic logic [31:0] bbe32(input int unsigned index);
    return {bbyte(index), bbyte(index + 1), bbyte(index + 2), bbyte(index + 3)};
  endfunction

  initial begin
    if (MAX_CHILDREN < 1 || MAX_CHILDREN > 16)
      $fatal(1, "SINGLE binding parser requires bounded children");
  end

  assign s_ready = state == IDLE;
  assign m_read_address = cursor;
  assign m_valid = state == REPORT;
  assign binding_local = bbe16(0);
  assign binding_peer = bbe16(2);
  assign binding_port = bbe16(4);
  assign binding_kind = bbyte(6);
  assign binding_flags = bbyte(7);
  assign binding_mac = {bbyte(8), bbyte(9), bbyte(10),
      bbyte(11), bbyte(12), bbyte(13)};
  assign binding_rank = bbe16(14);
  assign binding_terms = bbe32(16);
  assign binding_mask = bbyte(20);
  assign binding_reserved = {bbyte(21), bbyte(22), bbyte(23)};

  always_comb begin
    expected_result = 1'b0;
    if (bound_results < result_count_reg)
      expected_result = result_endpoints[INDEX_W'(bound_results)] == binding_local;
    duplicate_rank = 1'b0;
    duplicate_endpoint = 1'b0;
    duplicate_port = 1'b0;
    for (integer index = 0; index < MAX_CHILDREN; index++) begin
      if (index < int'(binding_index)) begin
        if (m_rank_ids[index*16 +: 16] == binding_rank) duplicate_rank = 1'b1;
        if (child_endpoints[index] == binding_local) duplicate_endpoint = 1'b1;
        if (m_local_ports[index*16 +: 16] == binding_port) duplicate_port = 1'b1;
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE;
      cursor <= '0;
      child_count_reg <= '0;
      result_count_reg <= '0;
      rank_mask_reg <= '0;
      accepted_mask_reg <= '0;
      manager_mac_reg <= '0;
      local_mac_reg <= '0;
      supported_ports_reg <= '0;
      shared_port_demux_reg <= 1'b0;
      child_index <= '0;
      result_index <= '0;
      binding_index <= '0;
      bound_results <= '0;
      word_low <= 1'b0;
      word_high <= '0;
      binding_byte_index <= '0;
      binding_bytes <= '0;
      binding_rejected <= 1'b0;
      m_local_endpoints <= '0;
      m_peer_endpoints <= '0;
      m_local_ports <= '0;
      m_rank_ids <= '0;
      m_peer_macs <= '0;
      m_native_masks <= '0;
      m_result_enabled <= '0;
      m_accept <= 1'b0;
      m_error_code <= '0;
      for (integer index = 0; index < MAX_CHILDREN; index++) begin
        child_endpoints[index] <= '0;
        result_endpoints[index] <= '0;
      end
    end else begin
      case (state)
        IDLE: begin
          if (s_valid) begin
            child_count_reg <= s_child_count;
            result_count_reg <= s_result_count;
            rank_mask_reg <= s_rank_mask;
            accepted_mask_reg <= s_accepted_mask;
            manager_mac_reg <= s_manager_mac;
            local_mac_reg <= s_local_mac;
            supported_ports_reg <= s_supported_ports;
            shared_port_demux_reg <= s_shared_port_demux;
            cursor <= 16'd96;
            child_index <= '0;
            result_index <= '0;
            binding_index <= '0;
            bound_results <= '0;
            word_low <= 1'b0;
            binding_byte_index <= '0;
            m_local_endpoints <= '0;
            m_peer_endpoints <= '0;
            m_local_ports <= '0;
            m_rank_ids <= '0;
            m_peer_macs <= '0;
            m_native_masks <= '0;
            m_result_enabled <= '0;
            m_accept <= 1'b0;
            m_error_code <= '0;
            if (s_child_count == 0 || int'(s_child_count) > MAX_CHILDREN
                || s_result_count > s_child_count) begin
              m_error_code <= 3'd1;
              state <= REPORT;
            end else state <= READ_CHILD;
          end
        end
        READ_CHILD: begin
          cursor <= cursor + 16'd1;
          if (!word_low) begin
            word_high <= m_read_data;
            word_low <= 1'b1;
          end else begin
            child_endpoints[INDEX_W'(child_index)] <= {word_high, m_read_data};
            word_low <= 1'b0;
            if (child_index + 8'd1 == child_count_reg) begin
              result_index <= '0;
              if (result_count_reg == 0) state <= READ_BINDING;
              else state <= READ_RESULT;
            end else child_index <= child_index + 8'd1;
          end
        end
        READ_RESULT: begin
          cursor <= cursor + 16'd1;
          if (!word_low) begin
            word_high <= m_read_data;
            word_low <= 1'b1;
          end else begin
            result_endpoints[INDEX_W'(result_index)] <= {word_high, m_read_data};
            word_low <= 1'b0;
            if (result_index + 8'd1 == result_count_reg) begin
              binding_byte_index <= '0;
              state <= READ_BINDING;
            end else result_index <= result_index + 8'd1;
          end
        end
        READ_BINDING: begin
          binding_bytes[binding_byte_index*8 +: 8] <= m_read_data;
          cursor <= cursor + 16'd1;
          if (binding_byte_index == 5'd23) state <= CHECK_BINDING;
          else binding_byte_index <= binding_byte_index + 5'd1;
        end
        // A binding is checked in one cycle and stored in the next: the
        // tables and counters the check reads do not change in between.
        CHECK_BINDING: begin
          binding_rejected <= binding_local == 16'hFFFF || binding_peer == 16'hFFFF
              || binding_local != child_endpoints[INDEX_W'(binding_index)]
              || duplicate_endpoint || duplicate_rank
              || (duplicate_port && !shared_port_demux_reg)
              || binding_kind != 8'd1 || (binding_flags & 8'hfe) != 0
              || binding_flags[0] != expected_result
              || binding_mac == local_mac_reg || binding_mac == manager_mac_reg
              || binding_rank == 16'hFFFF || binding_terms != 32'd1
              || binding_mask == 0 || (binding_mask & 8'hf0) != 0
              || (binding_mask & (binding_mask - 8'd1)) != 0
              || (binding_mask & ~rank_mask_reg) != 0
              || (binding_mask & ~accepted_mask_reg) != 0
              || binding_reserved != 0
              || int'(binding_port) >= 16
              || !supported_ports_reg[binding_port[3:0]];
          state <= STORE_BINDING;
        end
        STORE_BINDING: begin
          if (binding_rejected) begin
            m_accept <= 1'b0;
            m_error_code <= 3'd4;
            state <= REPORT;
          end else begin
            m_local_endpoints[binding_index*16 +: 16] <= binding_local;
            m_peer_endpoints[binding_index*16 +: 16] <= binding_peer;
            m_local_ports[binding_index*16 +: 16] <= binding_port;
            m_rank_ids[binding_index*16 +: 16] <= binding_rank;
            m_peer_macs[binding_index*48 +: 48] <= binding_mac;
            m_native_masks[binding_index*8 +: 8] <= binding_mask;
            m_result_enabled[INDEX_W'(binding_index)] <= binding_flags[0];
            if (binding_flags[0]) bound_results <= bound_results + 8'd1;
            if (binding_index + 8'd1 == child_count_reg) begin
              if (bound_results + {7'b0, binding_flags[0]} != result_count_reg) begin
                m_accept <= 1'b0;
                m_error_code <= 3'd4;
              end else begin
                m_accept <= 1'b1;
                m_error_code <= 3'd0;
              end
              state <= REPORT;
            end else begin
              binding_index <= binding_index + 8'd1;
              binding_byte_index <= '0;
              state <= READ_BINDING;
            end
          end
        end
        REPORT: begin
          if (m_ready) begin
            m_accept <= 1'b0;
            m_error_code <= '0;
            state <= IDLE;
          end
        end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
