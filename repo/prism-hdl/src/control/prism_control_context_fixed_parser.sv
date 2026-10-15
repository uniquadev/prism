//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_control_context_fixed_parser.sv
// Module: prism_control_context_fixed_parser
// Description: Sequential 48-byte SINGLE context admission precheck.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_context_fixed_parser #(
    parameter int unsigned MAX_CHILDREN = 8,
    parameter logic [3:0] SUPPORTED_POLICY_BITS = 4'b1101
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [15:0]  s_body_bytes,
    input  logic [47:0]  s_manager_mac,
    input  logic [15:0]  s_manager_port,
    input  logic [15:0]  s_link_mtu,
    input  logic [31:0]  s_max_elements,
    input  logic [31:0]  s_max_original_terms,
    input  logic [15:0]  s_max_kulisch_bits,
    input  logic [15:0]  s_max_window_intervals,
    input  logic [31:0]  s_max_window_bytes,
    input  logic         s_valid,
    output logic         s_ready,
    output logic [15:0]  m_read_address,
    input  logic [7:0]   m_read_data,
    output logic [7:0]   m_child_count,
    output logic [7:0]   m_result_count,
    output logic [31:0]  m_original_terms,
    output logic [31:0]  m_maximum_original_terms,
    output logic [31:0]  m_element_count,
    output logic [15:0]  m_kulisch_bits,
    output logic [15:0]  m_mtu,
    output logic [15:0]  m_window_intervals,
    output logic [31:0]  m_window_bytes,
    output logic [7:0]   m_accumulator,
    output logic [7:0]   m_partial_wire,
    output logic [7:0]   m_output_format,
    output logic [7:0]   m_accepted_mask,
    output logic [7:0]   m_rank_mask,
    output logic [7:0]   m_collective_kind,
    output logic         m_accept,
    output logic [2:0]   m_error_code,
    output logic         m_valid,
    input  logic         m_ready
);

  typedef enum logic [2:0] {IDLE, LOAD, PREPARE, CHECK, REPORT} state_t;
  state_t state;
  logic [383:0] fixed_bytes;
  logic [5:0] byte_index;
  logic [15:0] body_bytes_reg, manager_port_reg, link_mtu_reg;
  logic [47:0] manager_mac_reg;
  logic [31:0] max_elements_reg, max_terms_reg, max_window_bytes_reg;
  logic [15:0] max_kulisch_reg, max_window_intervals_reg;
  logic [47:0] context_manager_mac;
  logic [15:0] context_manager_port, parent_endpoint;
  logic [7:0] role, flags, reserved8;
  logic [15:0] reserved16;
  logic [23:0] extension_reserved;
  int unsigned required_width, expected_bytes, streams;
  // The derived limits are registered in a step of their own, so the
  // product and the sums are not part of the checks that use them.
  logic [31:0] window_minimum_reg;
  logic [15:0] required_width_reg, expected_bytes_reg;

  function automatic logic [7:0] byte_at(input int unsigned index);
    return fixed_bytes[index*8 +: 8];
  endfunction

  function automatic logic [15:0] be16(input int unsigned index);
    return {byte_at(index), byte_at(index + 1)};
  endfunction

  function automatic logic [31:0] be32(input int unsigned index);
    return {byte_at(index), byte_at(index + 1), byte_at(index + 2),
        byte_at(index + 3)};
  endfunction

  initial begin
    if (MAX_CHILDREN < 1 || MAX_CHILDREN > 16)
      $fatal(1, "SINGLE context parser requires bounded child resources");
  end

  assign s_ready = state == IDLE;
  assign m_read_address = 16'(48 + byte_index);
  assign m_valid = state == REPORT;
  assign role = byte_at(0);
  assign m_child_count = byte_at(1);
  assign m_result_count = byte_at(2);
  assign flags = byte_at(3);
  assign parent_endpoint = be16(4);
  assign m_original_terms = be32(6);
  assign m_window_intervals = be16(10);
  assign m_window_bytes = be32(12);
  assign m_element_count = be32(16);
  assign m_kulisch_bits = be16(20);
  assign m_mtu = be16(22);
  assign m_accumulator = byte_at(24);
  assign m_partial_wire = byte_at(25);
  assign m_output_format = byte_at(26);
  assign m_accepted_mask = byte_at(27);
  assign m_collective_kind = byte_at(28);
  assign reserved8 = byte_at(29);
  assign reserved16 = be16(30);
  assign context_manager_mac = {byte_at(32), byte_at(33), byte_at(34),
      byte_at(35), byte_at(36), byte_at(37)};
  assign context_manager_port = be16(38);
  assign m_maximum_original_terms = be32(40);
  assign m_rank_mask = byte_at(44);
  assign extension_reserved = {byte_at(45), byte_at(46), byte_at(47)};

  always_comb begin
    required_width = 278 + prism_pkg::prism_ceil_log2_terms(m_maximum_original_terms);
    expected_bytes = 48 + 2 * (int'(m_child_count) + int'(m_result_count))
        + 24 * int'(m_child_count);
    streams = int'(m_child_count);
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE;
      fixed_bytes <= '0;
      byte_index <= '0;
      body_bytes_reg <= '0;
      manager_mac_reg <= '0;
      manager_port_reg <= '0;
      link_mtu_reg <= '0;
      max_elements_reg <= '0;
      max_terms_reg <= '0;
      max_kulisch_reg <= '0;
      max_window_intervals_reg <= '0;
      max_window_bytes_reg <= '0;
      m_accept <= 1'b0;
      m_error_code <= '0;
    end else begin
      case (state)
        IDLE: begin
          if (s_valid) begin
            body_bytes_reg <= s_body_bytes;
            manager_mac_reg <= s_manager_mac;
            manager_port_reg <= s_manager_port;
            link_mtu_reg <= s_link_mtu;
            max_elements_reg <= s_max_elements;
            max_terms_reg <= s_max_original_terms;
            max_kulisch_reg <= s_max_kulisch_bits;
            max_window_intervals_reg <= s_max_window_intervals;
            max_window_bytes_reg <= s_max_window_bytes;
            byte_index <= '0;
            state <= LOAD;
          end
        end
        LOAD: begin
          fixed_bytes[byte_index*8 +: 8] <= m_read_data;
          if (byte_index == 6'd47) state <= PREPARE;
          else byte_index <= byte_index + 6'd1;
        end
        PREPARE: begin
          window_minimum_reg <= 32'(streams * (int'(m_mtu) + 14));
          required_width_reg <= 16'(required_width);
          expected_bytes_reg <= 16'(expected_bytes);
          state <= CHECK;
        end
        CHECK: begin
          m_accept <= 1'b0;
          if (role != 8'd1 || m_child_count == 0
              || int'(m_child_count) > MAX_CHILDREN
              || m_result_count > m_child_count || flags != 0
              || parent_endpoint != 16'hFFFF || reserved8 != 0
              || reserved16 != 0 || extension_reserved != 0
              || body_bytes_reg != expected_bytes_reg
              || m_collective_kind < 1 || m_collective_kind > 2
              || (m_collective_kind == 2 && m_result_count != m_child_count)
              || (m_collective_kind == 1 && m_result_count != 1)
              || m_original_terms != 32'(m_child_count)
              || m_maximum_original_terms < m_original_terms
              || m_accepted_mask == 0 || (m_accepted_mask & 8'he0) != 0
              || m_rank_mask == 0 || (m_rank_mask & 8'hf0) != 0
              || (m_rank_mask & ~m_accepted_mask) != 0) begin
            m_error_code <= 3'd1;
          end else if (context_manager_mac != manager_mac_reg
              || context_manager_port != manager_port_reg) begin
            m_error_code <= 3'd4;
          end else if (m_element_count == 0 || m_element_count > max_elements_reg
              || !(m_mtu inside {16'd576, 16'd1500})
              || m_maximum_original_terms > max_terms_reg
              || m_mtu < 576 || m_mtu > link_mtu_reg
              || m_kulisch_bits > max_kulisch_reg
              || m_window_intervals < 16'(streams)
              || m_window_intervals > max_window_intervals_reg
              || m_window_bytes > max_window_bytes_reg
              || m_window_bytes < window_minimum_reg) begin
            m_error_code <= 3'd3;
          end else if ((SUPPORTED_POLICY_BITS[3]
                  && m_accumulator == 8'h80 && m_partial_wire == 8'hff
                  && m_kulisch_bits >= required_width_reg
                  && (m_output_format inside {8'h01, 8'h02, 8'h03, 8'h04}
                      || m_output_format inside {8'h80, 8'hff}))
              || (SUPPORTED_POLICY_BITS[2]
                  && m_accumulator == 8'h80 && m_partial_wire == 8'h80
                  && m_kulisch_bits >= required_width_reg
                  && (m_output_format inside {8'h01, 8'h02, 8'h03, 8'h04}
                      || m_output_format inside {8'h80, 8'hff}))
              || ((m_accumulator == 8'h01 && SUPPORTED_POLICY_BITS[0])
                  && m_partial_wire == 8'h04
                  && m_output_format inside {8'h04, 8'hff}
                  && m_rank_mask == 8'h08)) begin
            m_accept <= 1'b1;
            m_error_code <= 3'd0;
          end else begin
            m_error_code <= 3'd2;
          end
          state <= REPORT;
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
