//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_control_reassembler.sv
// Module: prism_control_reassembler
// Description: Reassembles bounded out-of-order CONTROL fragments by transaction key.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_control_reassembler #(
    parameter int unsigned CONTEXTS = 2,
    parameter int unsigned CAPACITY_BYTES = 8192,
    parameter int unsigned MAX_FRAGMENT_BYTES = 1474,
    parameter int unsigned TIMEOUT_CYCLES = 250000
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_control_header_t      s_header,
    input  logic [15:0]                           s_payload_length,
    input  logic                                  s_start_valid,
    output logic                                  s_start_ready,
    input  logic [7:0]                            s_byte,
    input  logic                                  s_byte_last,
    input  logic                                  s_byte_valid,
    output logic                                  s_byte_ready,
    output prism_pkg::prism_control_header_t      m_header,
    output logic [15:0]                           m_payload_length,
    output logic                                  m_header_valid,
    input  logic                                  m_header_ready,
    output logic [7:0]                            m_byte,
    output logic                                  m_byte_last,
    output logic                                  m_byte_valid,
    input  logic                                  m_byte_ready,
    output prism_pkg::prism_status_e              error_status,
    output logic                                  error_valid,
    input  logic                                  error_ready
);

  import prism_pkg::*;

  localparam int unsigned MAX_FRAGMENTS =
      (CAPACITY_BYTES + MAX_FRAGMENT_BYTES - 1) / MAX_FRAGMENT_BYTES;
  localparam int unsigned CTX_W = prism_clog2_safe(CONTEXTS);
  localparam int unsigned FRAG_W = prism_clog2_safe(MAX_FRAGMENTS);
  localparam int unsigned BYTE_W = prism_clog2_safe(MAX_FRAGMENT_BYTES + 1);
  localparam int unsigned BYTE_INDEX_W = prism_clog2_safe(MAX_FRAGMENT_BYTES);
  localparam int unsigned TIMER_W = prism_clog2_safe(TIMEOUT_CYCLES + 1);

  logic context_valid [0:CONTEXTS-1];
  logic context_complete [0:CONTEXTS-1];
  prism_control_header_t context_header [0:CONTEXTS-1];
  logic [MAX_FRAGMENTS-1:0] fragment_received [0:CONTEXTS-1];
  logic [15:0] fragment_length [0:CONTEXTS-1][0:MAX_FRAGMENTS-1];
  logic [15:0] total_length [0:CONTEXTS-1];
  logic [TIMER_W-1:0] age [0:CONTEXTS-1];
  logic [7:0] payload_memory [0:CONTEXTS-1][0:MAX_FRAGMENTS-1][0:MAX_FRAGMENT_BYTES-1];

  logic write_active;
  logic write_discard;
  logic write_compare;
  logic write_conflict;
  logic [CTX_W-1:0] write_context;
  logic [FRAG_W-1:0] write_fragment;
  logic [BYTE_W-1:0] write_offset;
  logic [15:0] write_length;

  logic start_match;
  logic start_free;
  logic [CTX_W-1:0] start_context;
  logic start_invariants_valid;
  logic start_capacity_valid;

  logic output_active;
  logic output_header_sent;
  logic [CTX_W-1:0] output_context;
  logic [FRAG_W-1:0] output_fragment;
  logic [BYTE_W-1:0] output_offset;
  logic output_found;
  logic [CTX_W-1:0] output_found_context;
  logic output_first_found;
  logic [FRAG_W-1:0] output_first_fragment;
  logic output_next_found;
  logic [FRAG_W-1:0] output_next_fragment;

  initial begin
    if ((CONTEXTS < 1) || (CAPACITY_BYTES < 1) || (MAX_FRAGMENT_BYTES < 1)
        || (MAX_FRAGMENTS > 16) || (TIMEOUT_CYCLES < 1)) begin
      $fatal(1, "prism_control_reassembler parameters are illegal");
    end
  end

  always_comb begin
    start_match = 1'b0;
    start_free = 1'b0;
    start_context = '0;
    for (int unsigned ctx = 0; ctx < CONTEXTS; ctx++) begin
      if (context_valid[ctx]
          && (context_header[ctx].session_cookie == s_header.session_cookie)
          && (context_header[ctx].transaction_id == s_header.transaction_id)
          && !start_match) begin
        start_match = 1'b1;
        start_context = CTX_W'(ctx);
      end
    end
    if (!start_match) begin
      for (int unsigned ctx = 0; ctx < CONTEXTS; ctx++) begin
        if (!context_valid[ctx] && !start_free) begin
          start_free = 1'b1;
          start_context = CTX_W'(ctx);
        end
      end
    end
    start_invariants_valid = (s_header.fragment_count > 0)
        && (s_header.fragment_count <= 16'(MAX_FRAGMENTS))
        && (s_header.fragment_index < s_header.fragment_count)
        && ((s_header.flags & ~PRISM_CONTROL_FLAG_KNOWN_MASK) == 0)
        && ($countones(s_header.flags & (PRISM_CONTROL_FLAG_REQUEST
            | PRISM_CONTROL_FLAG_RESPONSE | PRISM_CONTROL_FLAG_EVENT)) == 1);
    if (start_match) begin
      start_invariants_valid &= (context_header[start_context].command == s_header.command)
          && (context_header[start_context].flags == s_header.flags)
          && (context_header[start_context].status == s_header.status)
          && (context_header[start_context].fragment_count == s_header.fragment_count)
          && (context_header[start_context].source_mac == s_header.source_mac)
          && (context_header[start_context].destination_mac == s_header.destination_mac)
          && (context_header[start_context].ingress_port == s_header.ingress_port);
      start_capacity_valid = ({1'b0, total_length[start_context]}
          + {1'b0, s_payload_length}) <= 17'(CAPACITY_BYTES);
      if (fragment_received[start_context][FRAG_W'(s_header.fragment_index)]) begin
        start_capacity_valid =
            fragment_length[start_context][FRAG_W'(s_header.fragment_index)]
            == s_payload_length;
      end
    end else begin
      start_capacity_valid = s_payload_length <= 16'(CAPACITY_BYTES);
    end
  end

  assign s_start_ready = !write_active && (start_match || start_free)
      && (!error_valid || error_ready);
  assign s_byte_ready = write_active;

  always_comb begin
    output_found = 1'b0;
    output_found_context = '0;
    for (int unsigned ctx = 0; ctx < CONTEXTS; ctx++) begin
      if (context_valid[ctx] && context_complete[ctx] && !output_found) begin
        output_found = 1'b1;
        output_found_context = CTX_W'(ctx);
      end
    end
  end

  assign m_header = context_header[output_context];
  assign m_payload_length = total_length[output_context];
  assign m_header_valid = output_active && !output_header_sent;
  assign m_byte_valid = output_active && output_header_sent
      && (total_length[output_context] != 0);
  assign m_byte = payload_memory[output_context][output_fragment]
      [output_offset[BYTE_INDEX_W-1:0]];
  assign m_byte_last = m_byte_valid
      && (16'(output_offset)
          == fragment_length[output_context][output_fragment] - 16'd1)
      && !output_next_found;

  always_comb begin
    output_first_found = 1'b0;
    output_first_fragment = '0;
    output_next_found = 1'b0;
    output_next_fragment = '0;
    for (int unsigned fragment = 0; fragment < MAX_FRAGMENTS; fragment++) begin
      if ((16'(fragment) < context_header[output_context].fragment_count)
          && (fragment_length[output_context][fragment] != 0)
          && !output_first_found) begin
        output_first_found = 1'b1;
        output_first_fragment = FRAG_W'(fragment);
      end
      if ((FRAG_W'(fragment) > output_fragment)
          && (16'(fragment) < context_header[output_context].fragment_count)
          && (fragment_length[output_context][fragment] != 0)
          && !output_next_found) begin
        output_next_found = 1'b1;
        output_next_fragment = FRAG_W'(fragment);
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      write_active <= 1'b0;
      write_discard <= 1'b0;
      write_compare <= 1'b0;
      write_conflict <= 1'b0;
      write_context <= '0;
      write_fragment <= '0;
      write_offset <= '0;
      write_length <= '0;
      output_active <= 1'b0;
      output_header_sent <= 1'b0;
      output_context <= '0;
      output_fragment <= '0;
      output_offset <= '0;
      error_status <= PRISM_STATUS_OK;
      error_valid <= 1'b0;
      for (int unsigned ctx = 0; ctx < CONTEXTS; ctx++) begin
        context_valid[ctx] <= 1'b0;
        context_complete[ctx] <= 1'b0;
        context_header[ctx] <= '0;
        fragment_received[ctx] <= '0;
        total_length[ctx] <= '0;
        age[ctx] <= '0;
        for (int unsigned fragment = 0; fragment < MAX_FRAGMENTS; fragment++) begin
          fragment_length[ctx][fragment] <= '0;
        end
      end
    end else begin
      if (error_valid && error_ready) begin
        error_valid <= 1'b0;
      end

      for (int unsigned ctx = 0; ctx < CONTEXTS; ctx++) begin
        if (context_valid[ctx] && !context_complete[ctx]
            && !(write_active && (write_context == CTX_W'(ctx)))) begin
          if (age[ctx] == TIMER_W'(TIMEOUT_CYCLES - 1)) begin
            context_valid[ctx] <= 1'b0;
            context_complete[ctx] <= 1'b0;
            if (!error_valid || error_ready) begin
              error_status <= PRISM_STATUS_INVALID_STATE;
              error_valid <= 1'b1;
            end
          end else begin
            age[ctx] <= age[ctx] + 1'b1;
          end
        end
      end

      if (s_start_valid && s_start_ready) begin
        write_active <= (s_payload_length != 0);
        write_discard <= !start_invariants_valid || !start_capacity_valid
            || (s_payload_length > 16'(MAX_FRAGMENT_BYTES));
        write_compare <= start_match
            && fragment_received[start_context][FRAG_W'(s_header.fragment_index)];
        write_conflict <= 1'b0;
        write_context <= start_context;
        write_fragment <= FRAG_W'(s_header.fragment_index);
        write_offset <= '0;
        write_length <= s_payload_length;

        if (!start_invariants_valid || !start_capacity_valid
            || (s_payload_length > 16'(MAX_FRAGMENT_BYTES))) begin
          if (start_match) begin
            context_valid[start_context] <= 1'b0;
            context_complete[start_context] <= 1'b0;
          end
          error_status <= start_capacity_valid
              ? PRISM_STATUS_INVALID_REQUEST : PRISM_STATUS_NO_OPERATION_SLOT;
          error_valid <= 1'b1;
        end else begin
          if (!start_match) begin
            context_valid[start_context] <= 1'b1;
            context_complete[start_context] <= 1'b0;
            context_header[start_context] <= s_header;
            fragment_received[start_context] <= '0;
            total_length[start_context] <= s_payload_length;
          end
          age[start_context] <= '0;
          if (!start_match
              || !fragment_received[start_context][FRAG_W'(s_header.fragment_index)]) begin
            fragment_length[start_context][FRAG_W'(s_header.fragment_index)]
                <= s_payload_length;
            if (start_match) begin
              total_length[start_context] <= total_length[start_context] + s_payload_length;
            end
          end
          if (s_payload_length == 0) begin
            fragment_received[start_context][FRAG_W'(s_header.fragment_index)] <= 1'b1;
            if ((fragment_received[start_context]
                | ({{(MAX_FRAGMENTS-1){1'b0}}, 1'b1} << s_header.fragment_index))
                == (({{(MAX_FRAGMENTS-1){1'b0}}, 1'b1} << s_header.fragment_count) - 1'b1)) begin
              context_complete[start_context] <= 1'b1;
            end
          end
        end
      end

      if (s_byte_valid && s_byte_ready) begin
        if (!write_discard) begin
          if (write_compare) begin
            if (payload_memory[write_context][write_fragment]
                [write_offset[BYTE_INDEX_W-1:0]] != s_byte) begin
              write_conflict <= 1'b1;
            end
          end else begin
            payload_memory[write_context][write_fragment]
                [write_offset[BYTE_INDEX_W-1:0]] <= s_byte;
          end
        end
        if (s_byte_last || (16'(write_offset) == write_length - 16'd1)) begin
          write_active <= 1'b0;
          if (!write_discard) begin
            if (write_conflict
                || (write_compare
                    && (payload_memory[write_context][write_fragment]
                        [write_offset[BYTE_INDEX_W-1:0]] != s_byte))
                || (s_byte_last
                    != (16'(write_offset) == write_length - 16'd1))) begin
              context_valid[write_context] <= 1'b0;
              context_complete[write_context] <= 1'b0;
              error_status <= PRISM_STATUS_TXN_CONFLICT;
              error_valid <= 1'b1;
            end else begin
              fragment_received[write_context][write_fragment] <= 1'b1;
              if ((fragment_received[write_context]
                  | ({{(MAX_FRAGMENTS-1){1'b0}}, 1'b1} << write_fragment))
                  == (({{(MAX_FRAGMENTS-1){1'b0}}, 1'b1}
                      << context_header[write_context].fragment_count) - 1'b1)) begin
                context_complete[write_context] <= 1'b1;
              end
            end
          end
        end else begin
          write_offset <= write_offset + 1'b1;
        end
      end

      if (!output_active && output_found) begin
        output_active <= 1'b1;
        output_header_sent <= 1'b0;
        output_context <= output_found_context;
        output_fragment <= '0;
        output_offset <= '0;
      end
      if (m_header_valid && m_header_ready) begin
        output_header_sent <= 1'b1;
        output_fragment <= output_first_fragment;
        output_offset <= '0;
        if (total_length[output_context] == 0) begin
          context_valid[output_context] <= 1'b0;
          context_complete[output_context] <= 1'b0;
          output_active <= 1'b0;
        end
      end
      if (m_byte_valid && m_byte_ready) begin
        if (m_byte_last) begin
          context_valid[output_context] <= 1'b0;
          context_complete[output_context] <= 1'b0;
          output_active <= 1'b0;
          output_header_sent <= 1'b0;
        end else if (16'(output_offset)
            == fragment_length[output_context][output_fragment] - 16'd1) begin
          output_fragment <= output_next_fragment;
          output_offset <= '0;
        end else begin
          output_offset <= output_offset + 1'b1;
        end
      end
    end
  end

endmodule
