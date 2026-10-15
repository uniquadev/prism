//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_value_reader.sv
// Module: prism_numbergroup_value_reader
// Description: Emits validated consecutive values as bounded byte transfers.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_value_reader (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_numbergroup_header_t  s_header,
    input  logic [15:0]                           s_kulisch_bits,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output logic [15:0]                           read_address,
    input  logic [7:0]                            read_data,
    output logic [31:0]                           m_global_index,
    output logic [7:0]                            m_format,
    output logic [7:0]                            m_group_index,
    output logic [15:0]                           m_value_bytes,
    output logic [15:0]                           m_byte_index,
    output logic [7:0]                            m_value_byte,
    output logic                                  m_element_last_byte,
    output logic                                  m_group_last_byte,
    output logic                                  m_packet_last_byte,
    output logic                                  m_valid,
    input  logic                                  m_ready,
    output logic                                  m_done_valid,
    input  logic                                  m_done_ready
);

  import prism_pkg::*;

  typedef enum logic [2:0] {
    IDLE, FORMAT, FLAGS, COUNT_HIGH, COUNT_LOW, VALUE, SKIP_PADDING, DONE
  } state_t;

  state_t state;
  prism_numbergroup_header_t header_reg;
  logic [15:0] kulisch_bits_reg;
  logic [15:0] cursor;
  logic [7:0] format_reg;
  logic [15:0] value_width;
  logic [7:0] count_high;
  logic [15:0] values_in_group;
  logic [15:0] value_index;
  logic [15:0] byte_index;
  logic [8:0] group_index;
  logic [31:0] global_index;
  logic [1:0] group_padding;

  assign s_ready = state == IDLE;
  assign read_address = cursor;
  assign m_global_index = global_index;
  assign m_format = format_reg;
  assign m_group_index = group_index[7:0];
  assign m_value_bytes = value_width;
  assign m_byte_index = byte_index;
  assign m_value_byte = read_data;
  assign m_element_last_byte = (byte_index + 16'd1 == value_width);
  assign m_group_last_byte = m_element_last_byte
      && (value_index + 16'd1 == values_in_group);
  assign m_packet_last_byte = m_group_last_byte
      && (group_index + 9'd1 == {1'b0, header_reg.group_count});
  assign m_valid = state == VALUE;
  assign m_done_valid = state == DONE;

  always_ff @(posedge clk) begin
    int unsigned element_bytes;
    int unsigned padding_bytes;
    if (!rst_n) begin
      state <= IDLE;
      header_reg <= '0;
      kulisch_bits_reg <= '0;
      cursor <= '0;
      format_reg <= '0;
      value_width <= '0;
      count_high <= '0;
      values_in_group <= '0;
      value_index <= '0;
      byte_index <= '0;
      group_index <= '0;
      global_index <= '0;
      group_padding <= '0;
    end else begin
      case (state)
        IDLE: begin
          if (s_valid) begin
            header_reg <= s_header;
            kulisch_bits_reg <= s_kulisch_bits;
            cursor <= 16'd56;
            group_index <= '0;
            global_index <= s_header.first_element;
            state <= FORMAT;
          end
        end
        FORMAT: begin
          format_reg <= read_data;
          case (read_data)
            PRISM_FORMAT_INT8: value_width <= 16'd1;
            PRISM_FORMAT_FP16, PRISM_FORMAT_BF16: value_width <= 16'd2;
            PRISM_FORMAT_FP32: value_width <= 16'd4;
            PRISM_FORMAT_KULISCH: value_width <= 16'(1 + (int'(kulisch_bits_reg) + 7) / 8);
            default: value_width <= '0;
          endcase
          cursor <= cursor + 16'd1;
          state <= FLAGS;
        end
        FLAGS: begin
          cursor <= cursor + 16'd1;
          state <= COUNT_HIGH;
        end
        COUNT_HIGH: begin
          count_high <= read_data;
          cursor <= cursor + 16'd1;
          state <= COUNT_LOW;
        end
        COUNT_LOW: begin
          values_in_group <= {count_high, read_data};
          cursor <= cursor + 16'd1;
          value_index <= '0;
          byte_index <= '0;
          state <= VALUE;
        end
        VALUE: begin
          if (m_ready) begin
            cursor <= cursor + 16'd1;
            if (m_element_last_byte) begin
              byte_index <= '0;
              global_index <= global_index + 32'd1;
              if (m_group_last_byte) begin
                element_bytes = int'(values_in_group) * int'(value_width);
                padding_bytes = (4 - (element_bytes % 4)) % 4;
                group_padding <= 2'(padding_bytes);
                group_index <= group_index + 9'd1;
                state <= SKIP_PADDING;
              end else begin
                value_index <= value_index + 16'd1;
              end
            end else begin
              byte_index <= byte_index + 16'd1;
            end
          end
        end
        SKIP_PADDING: begin
          cursor <= cursor + {14'd0, group_padding};
          if (group_index == {1'b0, header_reg.group_count}) begin
            state <= DONE;
          end else begin
            state <= FORMAT;
          end
        end
        DONE: begin
          if (m_done_ready) begin
            state <= IDLE;
          end
        end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
