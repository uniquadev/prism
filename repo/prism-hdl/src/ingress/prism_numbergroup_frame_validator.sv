//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_frame_validator.sv
// Module: prism_numbergroup_frame_validator
// Description: Validates a complete DATA/RESULT frame before exposing its bytes.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_numbergroup_frame_validator #(
    parameter int unsigned DATA_W = 512,
    parameter int unsigned MAX_MTU = 1500,
    parameter int unsigned PORT_INDEX = 0
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  logic [DATA_W-1:0]                     s_axis_tdata,
    input  logic [DATA_W/8-1:0]                   s_axis_tkeep,
    input  logic                                  s_axis_tlast,
    input  logic                                  s_axis_tuser,
    input  logic                                  s_axis_tvalid,
    output logic                                  s_axis_tready,
    input  logic [15:0]                           s_mtu,
    input  logic [15:0]                           s_kulisch_bits,
    output prism_pkg::prism_numbergroup_header_t  m_header,
    output logic [15:0]                           m_frame_bytes,
    output logic [4:0]                            m_format_mask,
    output logic                                  m_accept,
    output logic [2:0]                            m_error_code,
    output logic                                  m_valid,
    input  logic                                  m_ready,
    input  logic [15:0]                           m_read_address,
    output logic [7:0]                            m_read_data,
    input  logic [15:0]                           m_read_word_address,
    output logic [DATA_W-1:0]                     m_read_word_data,
    output logic [DATA_W-1:0]                     m_read_next_word_data,
    input  logic [15:0]                           m_copy_word_address,
    output logic [DATA_W-1:0]                     m_copy_word_data
);

  import prism_pkg::*;

  localparam int unsigned KEEP_W = DATA_W / 8;
  localparam int unsigned MAX_FRAME_BYTES = PRISM_ETH_HEADER_BYTES + MAX_MTU;
  localparam int unsigned FRAME_BEATS = (MAX_FRAME_BYTES + KEEP_W - 1) / KEEP_W;
  localparam int unsigned BEAT_INDEX_W = prism_clog2_safe(FRAME_BEATS);
  localparam int unsigned HEADER_BYTES = PRISM_ETH_HEADER_BYTES
      + PRISM_CONTROL_WORD_BYTES + PRISM_DATA_HEADER_BYTES;

  typedef enum logic [2:0] {
    RX, CHECK_HEADER, GROUP_DESCRIPTOR, KULISCH_VALUE,
    GROUP_PADDING, ETHERNET_PADDING, REPORT
  } state_t;

  state_t state;
  logic [DATA_W-1:0] frame_words [0:FRAME_BEATS-1];
  logic [15:0] beat_index;
  logic [15:0] frame_bytes;
  logic receive_error;
  logic [15:0] mtu_reg;
  logic [15:0] kulisch_bits_reg;
  prism_numbergroup_header_t first_header;
  prism_numbergroup_header_t header_reg;
  logic accepted;
  logic [4:0] formats_seen;
  logic [2:0] error_code;
  logic [15:0] body_end;
  logic [15:0] cursor;
  logic [8:0] groups_seen;
  logic [16:0] elements_seen;
  logic [15:0] group_count;
  logic [15:0] group_width;
  logic [15:0] group_value_start;
  logic [15:0] group_padding_start;
  logic [15:0] group_next_cursor;
  logic [1:0] group_padding_bytes;
  logic [2:0] padding_index;
  logic [15:0] element_index;
  logic [15:0] value_byte_index;
  logic [7:0] value_tag;
  logic integer_nonzero;
  logic [15:0] ethernet_padding_index;
  logic unused_parser_ready;
  logic unused_parser_valid;

  function automatic logic [7:0] frame_byte(input logic [15:0] address);
    if (int'(address) >= MAX_FRAME_BYTES) begin
      return 8'h00;
    end
    return frame_words[int'(address) / KEEP_W][(int'(address) % KEEP_W)*8 +: 8];
  endfunction

  prism_numbergroup_header_parser #(
      .DATA_W(DATA_W),
      .PORT_INDEX(PORT_INDEX)
  ) u_header_parser (
      .s_tdata(s_axis_tdata),
      .s_tkeep(s_axis_tkeep),
      .s_valid(s_axis_tvalid),
      .s_ready(unused_parser_ready),
      .m_header(first_header),
      .m_valid(unused_parser_valid),
      .m_ready(1'b1)
  );

  initial begin
    if (DATA_W != 512 || MAX_MTU < 576 || MAX_MTU > 9216) begin
      $fatal(1, "NumberGroup validator requires 512-bit AXI and a supported MTU");
    end
  end

  assign s_axis_tready = (state == RX);
  assign m_valid = (state == REPORT);
  assign m_header = header_reg;
  assign m_frame_bytes = frame_bytes;
  assign m_format_mask = formats_seen;
  assign m_accept = accepted;
  assign m_error_code = error_code;
  assign m_read_data = (m_valid && m_accept && m_read_address < frame_bytes)
      ? frame_byte(m_read_address) : 8'h00;
  assign m_read_word_data = (m_valid && m_accept
      && int'(m_read_word_address) < FRAME_BEATS)
      ? frame_words[m_read_word_address[BEAT_INDEX_W-1:0]] : '0;
  assign m_read_next_word_data = (m_valid && m_accept
      && int'(m_read_word_address) + 1 < FRAME_BEATS)
      ? frame_words[BEAT_INDEX_W'(m_read_word_address + 16'd1)] : '0;
  assign m_copy_word_data = (m_valid && m_accept
      && int'(m_copy_word_address) < FRAME_BEATS)
      ? frame_words[m_copy_word_address[BEAT_INDEX_W-1:0]] : '0;

  always_ff @(posedge clk) begin : p_validator
    int unsigned received_bytes;
    int unsigned width_bytes;
    int unsigned value_bytes;
    int unsigned pad_bytes;
    int unsigned next_position;
    logic [15:0] descriptor_count;
    logic [7:0] format_id;
    logic [4:0] format_bit;
    logic [7:0] value_octet;
    logic [7:0] unused_mask;

    if (!rst_n) begin
      state <= RX;
      beat_index <= '0;
      frame_bytes <= '0;
      receive_error <= 1'b0;
      mtu_reg <= '0;
      kulisch_bits_reg <= '0;
      header_reg <= '0;
      accepted <= 1'b0;
      formats_seen <= '0;
      error_code <= '0;
      body_end <= '0;
      cursor <= '0;
      groups_seen <= '0;
      elements_seen <= '0;
      group_count <= '0;
      group_width <= '0;
      group_value_start <= '0;
      group_padding_start <= '0;
      group_next_cursor <= '0;
      group_padding_bytes <= '0;
      padding_index <= '0;
      element_index <= '0;
      value_byte_index <= '0;
      value_tag <= '0;
      integer_nonzero <= 1'b0;
      ethernet_padding_index <= '0;
    end else begin
      case (state)
        RX: begin
          if (s_axis_tvalid) begin
            received_bytes = $countones(s_axis_tkeep);
            if (beat_index == 0) begin
              header_reg <= first_header;
              mtu_reg <= s_mtu;
              kulisch_bits_reg <= s_kulisch_bits;
              formats_seen <= '0;
            end
            if (int'(beat_index) < FRAME_BEATS) begin
              for (integer lane = 0; lane < KEEP_W; lane++)
                frame_words[beat_index[BEAT_INDEX_W-1:0]][lane*8 +: 8]
                    <= s_axis_tkeep[lane] ? s_axis_tdata[lane*8 +: 8] : 8'd0;
            end
            // The length of the frame is checked once the frame is complete,
            // from the registered byte count, not beat by beat behind the adder.
            if (received_bytes == 0
                || !prism_keep_is_contiguous(s_axis_tkeep, KEEP_W)
                || (!s_axis_tlast && s_axis_tkeep != {KEEP_W{1'b1}})
                || s_axis_tuser || int'(beat_index) >= FRAME_BEATS) begin
              receive_error <= 1'b1;
            end
            frame_bytes <= 16'(int'(frame_bytes) + received_bytes);
            if (s_axis_tlast) begin
              state <= CHECK_HEADER;
            end else if (beat_index != 16'hFFFF) begin
              beat_index <= beat_index + 16'd1;
            end
          end
        end

        CHECK_HEADER: begin
          if (receive_error || frame_bytes < 60 || int'(frame_bytes) > MAX_FRAME_BYTES
              || !header_reg.fixed_header_valid) begin
            error_code <= 3'd1;
            accepted <= 1'b0;
            state <= REPORT;
          end else if (header_reg.ethertype != PRISM_ETHERTYPE
              || header_reg.version != 8'h20
              || (header_reg.packet_class != PRISM_OP_COL_DATA
                  && header_reg.packet_class != PRISM_OP_COL_RES)
              || ((header_reg.flags & ~(PRISM_DATA_FLAG_LAST
                  | PRISM_DATA_FLAG_ACCUMULATION_INEXACT)) != 0)
              || header_reg.reserved != 0
              || ((header_reg.flags & PRISM_DATA_FLAG_ACCUMULATION_INEXACT) != 0
                  ? (header_reg.flags != (PRISM_DATA_FLAG_LAST
                      | PRISM_DATA_FLAG_ACCUMULATION_INEXACT)
                      || header_reg.element_count != 0
                      || header_reg.group_count != 0
                      || header_reg.body_bytes != 0)
                  : (header_reg.element_count == 0 || header_reg.group_count == 0))
              || ({1'b0, header_reg.first_element} + 33'(header_reg.element_count))
                  > 33'h1_0000_0000) begin
            error_code <= 3'd2;
            accepted <= 1'b0;
            state <= REPORT;
          end else if (mtu_reg < 576 || int'(mtu_reg) > MAX_MTU
              || kulisch_bits_reg < 8 || kulisch_bits_reg > 4096
              || int'(header_reg.body_bytes) < 4 * int'(header_reg.group_count)
              || int'(header_reg.body_bytes) + PRISM_CONTROL_WORD_BYTES
                  + PRISM_DATA_HEADER_BYTES > int'(mtu_reg)
              || frame_bytes != ((HEADER_BYTES + int'(header_reg.body_bytes) < 60)
                  ? 16'd60 : 16'(HEADER_BYTES + int'(header_reg.body_bytes)))) begin
            error_code <= 3'd3;
            accepted <= 1'b0;
            state <= REPORT;
          end else begin
            body_end <= 16'(HEADER_BYTES + int'(header_reg.body_bytes));
            cursor <= 16'(HEADER_BYTES);
            groups_seen <= '0;
            elements_seen <= '0;
            if ((header_reg.flags & PRISM_DATA_FLAG_ACCUMULATION_INEXACT) != 0) begin
              ethernet_padding_index <= 16'(HEADER_BYTES);
              state <= ETHERNET_PADDING;
            end else begin
              state <= GROUP_DESCRIPTOR;
            end
          end
        end

        GROUP_DESCRIPTOR: begin
          if (groups_seen == {1'b0, header_reg.group_count}) begin
            if (cursor != body_end || elements_seen != {1'b0, header_reg.element_count}) begin
              error_code <= 3'd4;
              accepted <= 1'b0;
              state <= REPORT;
            end else begin
              ethernet_padding_index <= body_end;
              state <= ETHERNET_PADDING;
            end
          end else if (int'(cursor) + PRISM_NUMBERGROUP_DESCRIPTOR_BYTES > int'(body_end)) begin
            error_code <= 3'd4;
            accepted <= 1'b0;
            state <= REPORT;
          end else begin
            format_id = frame_byte(cursor);
            descriptor_count = {frame_byte(cursor + 16'd2), frame_byte(cursor + 16'd3)};
            case (format_id)
              PRISM_FORMAT_INT8: begin width_bytes = 1; format_bit = 5'b00001; end
              PRISM_FORMAT_FP16: begin width_bytes = 2; format_bit = 5'b00010; end
              PRISM_FORMAT_BF16: begin width_bytes = 2; format_bit = 5'b00100; end
              PRISM_FORMAT_FP32: begin width_bytes = 4; format_bit = 5'b01000; end
              PRISM_FORMAT_KULISCH: begin
                width_bytes = 1 + (int'(kulisch_bits_reg) + 7) / 8;
                format_bit = 5'b10000;
              end
              default: begin width_bytes = 0; format_bit = '0; end
            endcase
            value_bytes = int'(descriptor_count) * width_bytes;
            pad_bytes = (4 - (value_bytes % 4)) % 4;
            next_position = int'(cursor) + PRISM_NUMBERGROUP_DESCRIPTOR_BYTES
                + value_bytes + pad_bytes;
            if (frame_byte(cursor + 16'd1) != 0 || descriptor_count == 0
                || width_bytes == 0 || next_position > int'(body_end)
                || int'(elements_seen) + int'(descriptor_count)
                    > int'(header_reg.element_count)) begin
              error_code <= 3'd4;
              accepted <= 1'b0;
              state <= REPORT;
            end else begin
              formats_seen <= formats_seen | format_bit;
              groups_seen <= groups_seen + 9'd1;
              elements_seen <= elements_seen + {1'b0, descriptor_count};
              group_count <= descriptor_count;
              group_width <= 16'(width_bytes);
              group_value_start <= cursor + 16'd4;
              group_padding_start <= 16'(int'(cursor) + 4 + value_bytes);
              group_next_cursor <= 16'(next_position);
              group_padding_bytes <= 2'(pad_bytes);
              padding_index <= '0;
              element_index <= '0;
              value_byte_index <= '0;
              integer_nonzero <= 1'b0;
              if (format_id == PRISM_FORMAT_KULISCH) begin
                state <= KULISCH_VALUE;
              end else begin
                state <= GROUP_PADDING;
              end
            end
          end
        end

        KULISCH_VALUE: begin
          value_octet = frame_byte(16'(int'(group_value_start)
              + int'(element_index) * int'(group_width) + int'(value_byte_index)));
          if (value_byte_index == 0) begin
            value_tag <= value_octet;
            integer_nonzero <= 1'b0;
            if (value_octet > 8'd5) begin
              error_code <= 3'd5;
              accepted <= 1'b0;
              state <= REPORT;
            end else begin
              value_byte_index <= 16'd1;
            end
          end else if (value_byte_index + 16'd1 == group_width) begin
            unused_mask = 8'hFF << (kulisch_bits_reg % 8);
            if ((value_tag == 0 && !(integer_nonzero || value_octet != 0))
                || (value_tag != 0 && (integer_nonzero || value_octet != 0))
                || (value_tag == 0 && (kulisch_bits_reg % 8) != 0
                    && ((value_octet & unused_mask)
                        != (value_octet[(kulisch_bits_reg-1) % 8]
                            ? unused_mask : 8'h00)))) begin
              error_code <= 3'd5;
              accepted <= 1'b0;
              state <= REPORT;
            end else if (element_index + 16'd1 == group_count) begin
              state <= GROUP_PADDING;
            end else begin
              element_index <= element_index + 16'd1;
              value_byte_index <= '0;
              integer_nonzero <= 1'b0;
            end
          end else begin
            integer_nonzero <= integer_nonzero || value_octet != 0;
            value_byte_index <= value_byte_index + 16'd1;
          end
        end

        GROUP_PADDING: begin
          if (padding_index == {1'b0, group_padding_bytes}) begin
            cursor <= group_next_cursor;
            state <= GROUP_DESCRIPTOR;
          end else if (frame_byte(group_padding_start + 16'(padding_index)) != 0) begin
            error_code <= 3'd4;
            accepted <= 1'b0;
            state <= REPORT;
          end else begin
            padding_index <= padding_index + 3'd1;
          end
        end

        ETHERNET_PADDING: begin
          if (ethernet_padding_index == frame_bytes) begin
            accepted <= 1'b1;
            error_code <= '0;
            state <= REPORT;
          end else if (frame_byte(ethernet_padding_index) != 0) begin
            accepted <= 1'b0;
            error_code <= 3'd3;
            state <= REPORT;
          end else begin
            ethernet_padding_index <= ethernet_padding_index + 16'd1;
          end
        end

        REPORT: begin
          if (m_ready) begin
            state <= RX;
            beat_index <= '0;
            frame_bytes <= '0;
            receive_error <= 1'b0;
            accepted <= 1'b0;
            error_code <= '0;
          end
        end
        default: state <= RX;
      endcase
    end
  end

endmodule
