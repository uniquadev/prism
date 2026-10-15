//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_lifecycle.sv
// Module: prism_single_lifecycle
// Description: One installed SINGLE context with transactional lifecycle pulses.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_lifecycle #(
    parameter int unsigned CONTEXT_W = 1280
) (
    input  logic                            clk,
    input  logic                            rst_n,
    input  prism_pkg::prism_operation_key_t s_operation,
    input  logic [31:0]                     s_transaction_id,
    input  logic [7:0]                      s_command,
    input  logic [7:0]                      s_precheck_status,
    input  logic [CONTEXT_W-1:0]            s_context,
    input  logic                            s_valid,
    output logic                            s_ready,
    input  prism_pkg::prism_operation_key_t s_complete_operation,
    input  logic                            s_complete_valid,
    output logic                            m_context_installed,
    output logic                            m_context_active,
    output logic                            m_context_complete,
    output prism_pkg::prism_operation_key_t m_context_operation,
    output logic [CONTEXT_W-1:0]            m_context,
    output logic                            m_stage_pulse,
    output logic                            m_commit_pulse,
    output logic                            m_release_pulse,
    output prism_pkg::prism_operation_key_t m_ack_operation,
    output logic [31:0]                     m_ack_transaction_id,
    output logic [7:0]                      m_ack_status,
    output logic                            m_ack_valid,
    input  logic                            m_ack_ready
);

  import prism_pkg::*;

  typedef enum logic [1:0] {EMPTY, STAGED, ACTIVE, COMPLETE} lifecycle_t;
  lifecycle_t lifecycle;
  prism_operation_key_t installed_key, generation_key;
  logic [CONTEXT_W-1:0] installed_context;
  logic generation_known;
  logic same_installed, same_family, stale_generation;
  // A command stays on offer until it is taken. It is compared with the
  // stored keys in its first cycle and taken in a later one with the
  // registered results; the keys change only when a command is taken.
  logic compared, same_installed_reg, same_installed_family_reg, stale_generation_reg;

  function automatic logic same_operation_family(
      input prism_operation_key_t left,
      input prism_operation_key_t right
  );
    return left.job_id == right.job_id && left.group_id == right.group_id
        && left.operation_id == right.operation_id;
  endfunction

  initial begin
    if (CONTEXT_W < 1) $fatal(1, "SINGLE lifecycle requires a context record");
  end

  assign same_installed = s_operation == installed_key;
  assign same_family = generation_known
      && same_operation_family(s_operation, generation_key);
  assign stale_generation = same_family
      && (s_operation.group_generation < generation_key.group_generation
          || (s_operation.group_generation == generation_key.group_generation
              && s_operation.operation_generation
                  <= generation_key.operation_generation));
  assign s_ready = !m_ack_valid && compared;
  always_ff @(posedge clk) begin
    if (!rst_n) compared <= 1'b0;
    else compared <= s_valid && !s_ready;
    same_installed_reg <= same_installed;
    same_installed_family_reg <= same_operation_family(s_operation, installed_key);
    stale_generation_reg <= stale_generation;
  end
  assign m_context_installed = lifecycle != EMPTY;
  assign m_context_active = lifecycle == ACTIVE;
  assign m_context_complete = lifecycle == COMPLETE;
  assign m_context_operation = installed_key;
  assign m_context = installed_context;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      lifecycle <= EMPTY;
      installed_key <= '0;
      installed_context <= '0;
      generation_key <= '0;
      generation_known <= 1'b0;
      m_stage_pulse <= 1'b0;
      m_commit_pulse <= 1'b0;
      m_release_pulse <= 1'b0;
      m_ack_operation <= '0;
      m_ack_transaction_id <= '0;
      m_ack_status <= '0;
      m_ack_valid <= 1'b0;
    end else begin
      m_stage_pulse <= 1'b0;
      m_commit_pulse <= 1'b0;
      m_release_pulse <= 1'b0;
      if (s_complete_valid && lifecycle == ACTIVE
          && s_complete_operation == installed_key) lifecycle <= COMPLETE;
      if (m_ack_valid && m_ack_ready) m_ack_valid <= 1'b0;
      if (s_valid && s_ready) begin
        m_ack_operation <= s_operation;
        m_ack_transaction_id <= s_transaction_id;
        m_ack_valid <= 1'b1;
        case (s_command)
          8'd1: begin
            if (s_precheck_status != 0) m_ack_status <= s_precheck_status;
            else if (lifecycle != EMPTY)
              m_ack_status <= same_installed_family_reg ? 8'd4 : 8'd3;
            else if (stale_generation_reg) m_ack_status <= 8'd5;
            else begin
              installed_key <= s_operation;
              installed_context <= s_context;
              generation_key <= s_operation;
              generation_known <= 1'b1;
              lifecycle <= STAGED;
              m_stage_pulse <= 1'b1;
              m_ack_status <= 8'd0;
            end
          end
          8'd2: begin
            if (lifecycle == STAGED && same_installed_reg) begin
              lifecycle <= ACTIVE;
              m_commit_pulse <= 1'b1;
              m_ack_status <= 8'd0;
            end else m_ack_status <= 8'd4;
          end
          8'd4: begin
            if (lifecycle == COMPLETE && same_installed_reg) begin
              lifecycle <= EMPTY;
              m_release_pulse <= 1'b1;
              m_ack_status <= 8'd0;
            end else m_ack_status <= 8'd4;
          end
          8'd6: begin
            if (lifecycle != EMPTY && same_installed_reg) begin
              lifecycle <= EMPTY;
              m_release_pulse <= 1'b1;
            end
            m_ack_status <= 8'd0;
          end
          default: m_ack_status <= 8'd1;
        endcase
      end
    end
  end

endmodule
