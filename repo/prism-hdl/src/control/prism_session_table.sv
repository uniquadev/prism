//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_session_table.sv
// Module: prism_session_table
// Description: Owns session cookies, leases, job bindings, and lifecycle state.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_session_table #(
    parameter int unsigned SESSIONS = 4,
    parameter logic [63:0] DEVICE_BOOT_ID = 64'h5052_4953_4D00_0001,
    parameter logic [63:0] DEFAULT_LEASE_MS = 64'd30000,
    parameter logic [63:0] LEASE_GRACE_MS = 64'd5000
) (
    input  logic                                clk,
    input  logic                                rst_n,
    input  logic                                millisecond_tick,
    input  prism_pkg::prism_control_request_t   s_request,
    input  logic                                s_request_valid,
    output logic                                s_request_ready,
    input  logic                                request_session_has_groups,
    output prism_pkg::prism_control_result_t    m_result,
    output logic                                m_result_valid,
    input  logic                                m_result_ready,
    input  logic [63:0]                         lookup_cookie,
    output logic                                lookup_valid,
    output logic [63:0]                         lookup_job_id,
    output prism_pkg::prism_session_state_e     lookup_state
);

  import prism_pkg::*;

  localparam int unsigned SLOT_W = prism_clog2_safe(SESSIONS);

  logic valid [0:SESSIONS-1];
  prism_session_state_e state [0:SESSIONS-1];
  logic [63:0] cookie [0:SESSIONS-1];
  logic [63:0] job_id [0:SESSIONS-1];
  logic [63:0] lease_remaining [0:SESSIONS-1];
  logic [63:0] grace_remaining [0:SESSIONS-1];
  logic [63:0] open_transaction [0:SESSIONS-1];

  logic request_match;
  logic request_replay;
  logic request_free;
  logic [SLOT_W-1:0] request_slot;
  logic [63:0] granted_lease;
  logic [63:0] generated_cookie;
  prism_control_result_t result_reg;
  // The shared request envelope contains fields owned by the group and operation tables.
  logic unused_request_fields;
  assign unused_request_fields = ^s_request;

  initial begin
    if ((SESSIONS < 1) || (DEFAULT_LEASE_MS == 0) || (LEASE_GRACE_MS == 0)) begin
      $fatal(1, "prism_session_table parameters are illegal");
    end
  end

  always_comb begin
    lookup_valid = 1'b0;
    lookup_job_id = '0;
    lookup_state = PRISM_SESSION_CLOSED;
    for (int unsigned slot = 0; slot < SESSIONS; slot++) begin
      if (valid[slot] && (cookie[slot] == lookup_cookie) && !lookup_valid) begin
        lookup_valid = 1'b1;
        lookup_job_id = job_id[slot];
        lookup_state = state[slot];
      end
    end
  end

  always_comb begin
    request_match = 1'b0;
    request_replay = 1'b0;
    request_free = 1'b0;
    request_slot = '0;
    for (int unsigned slot = 0; slot < SESSIONS; slot++) begin
      if (valid[slot] && (cookie[slot] == s_request.header.session_cookie)
          && !request_match) begin
        request_match = 1'b1;
        request_slot = SLOT_W'(slot);
      end
    end
    if (s_request.header.command == PRISM_CMD_SESSION_OPEN) begin
      request_match = 1'b0;
      for (int unsigned slot = 0; slot < SESSIONS; slot++) begin
        if (valid[slot] && (open_transaction[slot] == s_request.header.transaction_id)
            && (job_id[slot] == s_request.job_id) && !request_replay) begin
          request_replay = 1'b1;
          request_slot = SLOT_W'(slot);
        end
      end
    end
    if (!request_match && !request_replay) begin
      for (int unsigned slot = 0; slot < SESSIONS; slot++) begin
        if (!valid[slot] && !request_free) begin
          request_free = 1'b1;
          request_slot = SLOT_W'(slot);
        end
      end
    end
    granted_lease = s_request.present[PRISM_PRESENT_LEASE_MS]
        ? s_request.lease_ms : DEFAULT_LEASE_MS;
    generated_cookie = DEVICE_BOOT_ID ^ s_request.header.transaction_id
        ^ s_request.job_id ^ (64'(request_slot) + 1'b1);
    if (generated_cookie == 0) generated_cookie = 64'(request_slot) + 1'b1;
  end

  assign s_request_ready = !m_result_valid || m_result_ready;
  assign m_result = result_reg;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      result_reg <= '0;
      m_result_valid <= 1'b0;
      for (int unsigned slot = 0; slot < SESSIONS; slot++) begin
        valid[slot] <= 1'b0;
        state[slot] <= PRISM_SESSION_CLOSED;
        cookie[slot] <= '0;
        job_id[slot] <= '0;
        lease_remaining[slot] <= '0;
        grace_remaining[slot] <= '0;
        open_transaction[slot] <= '0;
      end
    end else begin
      if (m_result_valid && m_result_ready) begin
        m_result_valid <= 1'b0;
      end

      if (millisecond_tick) begin
        for (int unsigned slot = 0; slot < SESSIONS; slot++) begin
          if (valid[slot] && (state[slot] == PRISM_SESSION_OPEN)) begin
            if (lease_remaining[slot] <= 1) begin
              lease_remaining[slot] <= '0;
              state[slot] <= PRISM_SESSION_EXPIRING;
            end else begin
              lease_remaining[slot] <= lease_remaining[slot] - 1'b1;
            end
          end else if (valid[slot] && (state[slot] == PRISM_SESSION_EXPIRING)) begin
            if (grace_remaining[slot] <= 1) begin
              grace_remaining[slot] <= '0;
              state[slot] <= PRISM_SESSION_ORPHANED;
            end else begin
              grace_remaining[slot] <= grace_remaining[slot] - 1'b1;
            end
          end
        end
      end

      if (s_request_valid && s_request_ready) begin
        result_reg <= '0;
        result_reg.header <= s_request.header;
        result_reg.device_boot_id <= DEVICE_BOOT_ID;
        result_reg.lease_grace_ms <= LEASE_GRACE_MS;
        result_reg.status <= s_request.decode_status;
        m_result_valid <= 1'b1;

        if (s_request.decode_status == PRISM_STATUS_OK) begin
          case (s_request.header.command)
            PRISM_CMD_SESSION_OPEN: begin
              if (s_request.header.session_cookie != 0) begin
                result_reg.status <= PRISM_STATUS_INVALID_REQUEST;
              end else if (s_request.security_profile != 0) begin
                result_reg.status <= PRISM_STATUS_UNSUPPORTED_FEATURE;
              end else if (request_replay) begin
                result_reg.session_cookie <= cookie[request_slot];
                result_reg.lease_ms <= lease_remaining[request_slot];
              end else if (!request_free) begin
                result_reg.status <= PRISM_STATUS_NO_OPERATION_SLOT;
              end else begin
                valid[request_slot] <= 1'b1;
                state[request_slot] <= PRISM_SESSION_OPEN;
                cookie[request_slot] <= generated_cookie;
                job_id[request_slot] <= s_request.job_id;
                lease_remaining[request_slot] <= granted_lease;
                grace_remaining[request_slot] <= LEASE_GRACE_MS;
                open_transaction[request_slot] <= s_request.header.transaction_id;
                result_reg.session_cookie <= generated_cookie;
                result_reg.lease_ms <= granted_lease;
              end
            end

            PRISM_CMD_SESSION_RENEW: begin
              if (!request_match) begin
                result_reg.status <= PRISM_STATUS_STALE_SESSION;
              end else if (state[request_slot] == PRISM_SESSION_ORPHANED) begin
                result_reg.status <= PRISM_STATUS_INVALID_STATE;
              end else begin
                state[request_slot] <= PRISM_SESSION_OPEN;
                lease_remaining[request_slot] <= granted_lease;
                grace_remaining[request_slot] <= LEASE_GRACE_MS;
                result_reg.session_cookie <= cookie[request_slot];
                result_reg.lease_ms <= granted_lease;
              end
            end

            PRISM_CMD_SESSION_CLOSE: begin
              if (!request_match) begin
                result_reg.status <= PRISM_STATUS_STALE_SESSION;
              end else if (request_session_has_groups) begin
                result_reg.status <= PRISM_STATUS_GROUP_BUSY;
              end else begin
                valid[request_slot] <= 1'b0;
                state[request_slot] <= PRISM_SESSION_CLOSED;
                result_reg.session_cookie <= cookie[request_slot];
              end
            end

            default: result_reg.status <= PRISM_STATUS_UNSUPPORTED_COMMAND;
          endcase
        end
      end
    end
  end

endmodule
