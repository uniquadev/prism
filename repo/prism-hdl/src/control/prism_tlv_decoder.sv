//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_tlv_decoder.sv
// Module: prism_tlv_decoder
// Description: Converts a reassembled CONTROL payload into backpressurable TLV events.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_tlv_decoder (
    input  logic                             clk,
    input  logic                             rst_n,
    input  prism_pkg::prism_control_header_t s_header,
    input  logic [15:0]                      s_payload_length,
    input  logic                             s_header_valid,
    output logic                             s_header_ready,
    input  logic [7:0]                       s_byte,
    input  logic                             s_byte_last,
    input  logic                             s_byte_valid,
    output logic                             s_byte_ready,
    output prism_pkg::prism_tlv_event_t      m_event,
    output logic                             m_event_valid,
    input  logic                             m_event_ready
);

  import prism_pkg::*;

  typedef enum logic [3:0] {
    STATE_IDLE,
    STATE_HEADER,
    STATE_VALUE,
    STATE_PADDING,
    STATE_RECORD_END,
    STATE_DRAIN,
    STATE_MESSAGE_END
  } state_e;

  state_e state;
  prism_control_header_t header_reg;
  logic [15:0] payload_length_reg;
  logic [15:0] bytes_consumed;
  logic [2:0] header_index;
  logic [15:0] type_shift;
  logic [15:0] flags_shift;
  logic [23:0] length_shift;
  logic [15:0] record_type_reg;
  logic [15:0] record_flags_reg;
  logic [31:0] record_length_reg;
  logic [31:0] value_index;
  logic [2:0] padding_remaining;
  prism_status_e message_status;

  logic [31:0] completed_length;
  logic [2:0] completed_padding;
  logic [32:0] completed_extent;

  always_comb begin
    completed_length = {length_shift, s_byte};
    completed_padding = 3'((4'd8 - {1'b0, completed_length[2:0]}) & 4'd7);
    completed_extent = 33'(completed_length) + 33'(completed_padding);
  end

  assign s_header_ready = (state == STATE_IDLE) && !m_event_valid;
  assign s_byte_ready = ((state == STATE_HEADER) || (state == STATE_VALUE)
      || (state == STATE_PADDING) || (state == STATE_DRAIN)) && !m_event_valid;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= STATE_IDLE;
      header_reg <= '0;
      payload_length_reg <= '0;
      bytes_consumed <= '0;
      header_index <= '0;
      type_shift <= '0;
      flags_shift <= '0;
      length_shift <= '0;
      record_type_reg <= '0;
      record_flags_reg <= '0;
      record_length_reg <= '0;
      value_index <= '0;
      padding_remaining <= '0;
      message_status <= PRISM_STATUS_OK;
      m_event <= '0;
      m_event_valid <= 1'b0;
    end else begin
      if (m_event_valid && m_event_ready) begin
        m_event_valid <= 1'b0;
      end

      case (state)
        STATE_IDLE: begin
          if (s_header_valid && s_header_ready) begin
            header_reg <= s_header;
            payload_length_reg <= s_payload_length;
            bytes_consumed <= '0;
            header_index <= '0;
            message_status <= PRISM_STATUS_OK;
            m_event <= '{
              kind: PRISM_TLV_EVENT_MESSAGE_START,
              header: s_header,
              record_type: 16'b0,
              record_flags: 16'b0,
              record_length: 32'b0,
              value_byte: 8'b0,
              value_last: 1'b0,
              status: PRISM_STATUS_OK
            };
            m_event_valid <= 1'b1;
            state <= (s_payload_length == 0) ? STATE_MESSAGE_END : STATE_HEADER;
          end
        end

        STATE_HEADER: begin
          if (s_byte_valid && s_byte_ready) begin
            bytes_consumed <= bytes_consumed + 1'b1;
            if (s_byte_last != (bytes_consumed + 1'b1 == payload_length_reg)) begin
              message_status <= PRISM_STATUS_BAD_PAYLOAD_LENGTH;
            end
            case (header_index)
              3'd0: type_shift[15:8] <= s_byte;
              3'd1: type_shift[7:0] <= s_byte;
              3'd2: flags_shift[15:8] <= s_byte;
              3'd3: flags_shift[7:0] <= s_byte;
              3'd4: length_shift[23:16] <= s_byte;
              3'd5: length_shift[15:8] <= s_byte;
              3'd6: length_shift[7:0] <= s_byte;
              default: begin end
            endcase
            if (header_index == 3'd7) begin
              record_type_reg <= type_shift;
              record_flags_reg <= flags_shift;
              record_length_reg <= completed_length;
              value_index <= '0;
              padding_remaining <= completed_padding;
              header_index <= '0;
              if ((flags_shift & ~PRISM_TLV_FLAG_KNOWN_MASK) != 0) begin
                message_status <= PRISM_STATUS_INVALID_RECORD;
              end
              if ((33'(bytes_consumed + 1'b1) + completed_extent)
                  > 33'(payload_length_reg)) begin
                message_status <= PRISM_STATUS_BAD_PAYLOAD_LENGTH;
                state <= STATE_DRAIN;
              end else begin
                m_event <= '{
                  kind: PRISM_TLV_EVENT_RECORD_START,
                  header: header_reg,
                  record_type: type_shift,
                  record_flags: flags_shift,
                  record_length: completed_length,
                  value_byte: 8'b0,
                  value_last: 1'b0,
                  status: PRISM_STATUS_OK
                };
                m_event_valid <= 1'b1;
                if (completed_length != 0) begin
                  state <= STATE_VALUE;
                end else if (completed_padding != 0) begin
                  state <= STATE_PADDING;
                end else begin
                  state <= STATE_RECORD_END;
                end
              end
            end else if (bytes_consumed + 1'b1 == payload_length_reg) begin
              message_status <= PRISM_STATUS_BAD_PAYLOAD_LENGTH;
              state <= STATE_MESSAGE_END;
            end else begin
              header_index <= header_index + 1'b1;
            end
          end
        end

        STATE_VALUE: begin
          if (s_byte_valid && s_byte_ready) begin
            bytes_consumed <= bytes_consumed + 1'b1;
            value_index <= value_index + 1'b1;
            if (s_byte_last != (bytes_consumed + 1'b1 == payload_length_reg)) begin
              message_status <= PRISM_STATUS_BAD_PAYLOAD_LENGTH;
            end
            m_event <= '{
              kind: PRISM_TLV_EVENT_VALUE_BYTE,
              header: header_reg,
              record_type: record_type_reg,
              record_flags: record_flags_reg,
              record_length: record_length_reg,
              value_byte: s_byte,
              value_last: (value_index + 1'b1 == record_length_reg),
              status: PRISM_STATUS_OK
            };
            m_event_valid <= 1'b1;
            if (value_index + 1'b1 == record_length_reg) begin
              state <= (padding_remaining == 0) ? STATE_RECORD_END : STATE_PADDING;
            end
          end
        end

        STATE_PADDING: begin
          if (s_byte_valid && s_byte_ready) begin
            bytes_consumed <= bytes_consumed + 1'b1;
            padding_remaining <= padding_remaining - 1'b1;
            if (s_byte != 0) begin
              message_status <= PRISM_STATUS_INVALID_RECORD;
            end
            if (s_byte_last != (bytes_consumed + 1'b1 == payload_length_reg)) begin
              message_status <= PRISM_STATUS_BAD_PAYLOAD_LENGTH;
            end
            if (padding_remaining == 1) begin
              state <= STATE_RECORD_END;
            end
          end
        end

        STATE_RECORD_END: begin
          if (!m_event_valid) begin
            m_event <= '{
              kind: PRISM_TLV_EVENT_RECORD_END,
              header: header_reg,
              record_type: record_type_reg,
              record_flags: record_flags_reg,
              record_length: record_length_reg,
              value_byte: 8'b0,
              value_last: 1'b0,
              status: PRISM_STATUS_OK
            };
            m_event_valid <= 1'b1;
            state <= (bytes_consumed == payload_length_reg) ? STATE_MESSAGE_END : STATE_HEADER;
          end
        end

        STATE_DRAIN: begin
          if (s_byte_valid && s_byte_ready) begin
            bytes_consumed <= bytes_consumed + 1'b1;
            if (bytes_consumed + 1'b1 == payload_length_reg) begin
              if (!s_byte_last) begin
                message_status <= PRISM_STATUS_BAD_PAYLOAD_LENGTH;
              end
              state <= STATE_MESSAGE_END;
            end
          end
        end

        STATE_MESSAGE_END: begin
          if (!m_event_valid) begin
            m_event <= '{
              kind: PRISM_TLV_EVENT_MESSAGE_END,
              header: header_reg,
              record_type: 16'b0,
              record_flags: 16'b0,
              record_length: 32'b0,
              value_byte: 8'b0,
              value_last: 1'b0,
              status: message_status
            };
            m_event_valid <= 1'b1;
            state <= STATE_IDLE;
          end
        end

        default: state <= STATE_IDLE;
      endcase
    end
  end

endmodule
