//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_operation_table.sv
// Module: prism_operation_table
// Description: Owns operation lifecycle, route state, and accumulator-width selection.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_operation_table #(
    parameter int unsigned OPERATIONS = 8,
    parameter int unsigned MAX_RESULT_ROUTES = 2,
    parameter int unsigned WIDTH_COUNT = 3,
    parameter int unsigned WIDTH_0 = 64,
    parameter int unsigned WIDTH_1 = 288,
    parameter int unsigned WIDTH_2 = 320
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_control_request_t         s_request,
    input  prism_pkg::prism_result_route_t            s_result_routes [0:MAX_RESULT_ROUTES-1],
    input  logic                                      s_request_valid,
    output logic                                      s_request_ready,
    input  logic                                      request_session_valid,
    input  logic [63:0]                               request_session_job_id,
    input  logic                                      request_group_valid,
    input  logic [15:0]                               request_group_slot,
    input  prism_pkg::prism_group_state_e             request_group_state,
    input  logic [15:0]                               request_group_expected_contributors,
    output prism_pkg::prism_control_result_t          m_result,
    output logic                                      m_result_valid,
    input  logic                                      m_result_ready,
    input  logic [15:0]                               group_query_slot,
    output logic                                      group_has_operations,
    input  prism_pkg::prism_operation_key_t           lookup_key,
    output logic                                      lookup_valid,
    output logic [15:0]                               lookup_slot,
    output prism_pkg::prism_operation_state_e         lookup_state,
    output prism_pkg::prism_operation_descriptor_t    lookup_descriptor,
    output logic [15:0]                               lookup_group_slot,
    output logic [15:0]                               lookup_expected_contributors,
    output logic [15:0]                               lookup_selected_width,
    output logic [1:0]                                lookup_width_index,
    output logic                                      lookup_accumulation_inexact,
    input  logic [15:0]                               route_lookup_slot,
    input  logic [15:0]                               route_lookup_index,
    output logic                                      route_lookup_valid,
    output prism_pkg::prism_result_route_t            route_lookup_route,
    input  logic                                      complete_operation_valid,
    input  logic [15:0]                               complete_operation_slot
);

  import prism_pkg::*;

  localparam int unsigned SLOT_W = prism_clog2_safe(OPERATIONS);
  localparam int unsigned ROUTE_W = prism_clog2_safe(MAX_RESULT_ROUTES);

  typedef enum logic [1:0] {STATE_IDLE, STATE_WAIT_WIDTH, STATE_RESULT} control_state_e;
  control_state_e control_state;

  logic valid [0:OPERATIONS-1];
  prism_operation_state_e operation_state [0:OPERATIONS-1];
  logic [63:0] session_cookie [0:OPERATIONS-1];
  prism_operation_key_t key [0:OPERATIONS-1];
  logic [15:0] group_slot [0:OPERATIONS-1];
  logic [15:0] expected_contributors [0:OPERATIONS-1];
  prism_operation_descriptor_t descriptor [0:OPERATIONS-1];
  logic [15:0] selected_width [0:OPERATIONS-1];
  logic [1:0] width_index [0:OPERATIONS-1];
  logic accumulation_inexact [0:OPERATIONS-1];
  logic [63:0] prepare_transaction [0:OPERATIONS-1];
  prism_result_route_t routes [0:OPERATIONS-1][0:MAX_RESULT_ROUTES-1];

  logic request_exact;
  logic request_generation_mismatch;
  logic request_free;
  logic request_replay;
  logic [SLOT_W-1:0] request_slot;
  logic route_geometry_valid;
  logic [23:0] output_chunk_count;

  logic [63:0] pending_session_cookie;
  logic [15:0] pending_group_id;
  logic [15:0] pending_group_generation;
  logic [15:0] pending_operation_id;
  logic [31:0] pending_operation_generation;
  prism_operation_descriptor_t pending_descriptor;
  logic [15:0] pending_result_route_count;
  logic [63:0] pending_transaction;
  prism_result_route_t pending_routes [0:MAX_RESULT_ROUTES-1];
  logic [SLOT_W-1:0] pending_slot;
  logic [15:0] pending_group_slot;
  logic [15:0] pending_expected_contributors;
  logic [63:0] pending_session_job_id;
  prism_control_result_t result_reg;
  // The shared request envelope contains fields owned by the session and group tables.
  logic unused_request_fields;
  assign unused_request_fields = ^s_request;

  logic selector_start;
  logic selector_ready;
  logic [15:0] unused_selector_required_width;
  logic [15:0] selector_selected_width;
  logic [1:0] selector_width_index;
  logic unused_selector_sufficient;
  logic selector_inexact;
  logic selector_valid;

  prism_kulisch_width_selector #(
      .WIDTH_COUNT(WIDTH_COUNT),
      .WIDTH_0(WIDTH_0),
      .WIDTH_1(WIDTH_1),
      .WIDTH_2(WIDTH_2)
  ) u_width_selector (
      .clk(clk),
      .rst_n(rst_n),
      .s_input_format(s_request.operation_descriptor.input_format),
      .s_maximum_terms(s_request.operation_descriptor.maximum_reduction_terms),
      .s_valid(selector_start),
      .s_ready(selector_ready),
      .m_required_width(unused_selector_required_width),
      .m_selected_width(selector_selected_width),
      .m_width_index(selector_width_index),
      .m_sufficient(unused_selector_sufficient),
      .m_accumulation_inexact(selector_inexact),
      .m_valid(selector_valid),
      .m_ready(control_state == STATE_WAIT_WIDTH)
  );

  initial begin
    if ((OPERATIONS < 1) || (MAX_RESULT_ROUTES < 1)) begin
      $fatal(1, "prism_operation_table parameters are illegal");
    end
  end

  always_comb begin
    group_has_operations = 1'b0;
    lookup_valid = 1'b0;
    lookup_slot = '0;
    lookup_state = PRISM_OPERATION_FREE;
    lookup_descriptor = '0;
    lookup_group_slot = '0;
    lookup_expected_contributors = '0;
    lookup_selected_width = '0;
    lookup_width_index = '0;
    lookup_accumulation_inexact = 1'b0;
    for (int unsigned slot = 0; slot < OPERATIONS; slot++) begin
      if (valid[slot] && (group_slot[slot] == group_query_slot)) begin
        group_has_operations = 1'b1;
      end
      if (valid[slot] && (key[slot] == lookup_key) && !lookup_valid) begin
        lookup_valid = 1'b1;
        lookup_slot = 16'(slot);
        lookup_state = operation_state[slot];
        lookup_descriptor = descriptor[slot];
        lookup_group_slot = group_slot[slot];
        lookup_expected_contributors = expected_contributors[slot];
        lookup_selected_width = selected_width[slot];
        lookup_width_index = width_index[slot];
        lookup_accumulation_inexact = accumulation_inexact[slot];
      end
    end

    route_lookup_valid = 1'b0;
    route_lookup_route = '0;
    if ((route_lookup_slot < 16'(OPERATIONS))
        && valid[SLOT_W'(route_lookup_slot)]
        && (route_lookup_index
            < descriptor[SLOT_W'(route_lookup_slot)].result_route_count)) begin
      route_lookup_valid = 1'b1;
      route_lookup_route = routes[SLOT_W'(route_lookup_slot)]
          [ROUTE_W'(route_lookup_index)];
    end
  end

  always_comb begin
    request_exact = 1'b0;
    request_generation_mismatch = 1'b0;
    request_free = 1'b0;
    request_replay = 1'b0;
    request_slot = '0;
    for (int unsigned slot = 0; slot < OPERATIONS; slot++) begin
      if (valid[slot] && (session_cookie[slot] == s_request.header.session_cookie)
          && (key[slot].operation_id == s_request.operation_id)) begin
        if ((key[slot].operation_generation == s_request.operation_generation)
            && !request_exact) begin
          request_exact = 1'b1;
          request_slot = SLOT_W'(slot);
          request_replay = prepare_transaction[slot] == s_request.header.transaction_id;
        end else if (key[slot].operation_generation != s_request.operation_generation) begin
          request_generation_mismatch = 1'b1;
        end
      end
    end
    if (!request_exact) begin
      for (int unsigned slot = 0; slot < OPERATIONS; slot++) begin
        if (!valid[slot] && !request_free) begin
          request_free = 1'b1;
          request_slot = SLOT_W'(slot);
        end
      end
    end

    output_chunk_count = 24'(prism_chunk_count(
        s_request.operation_descriptor.element_count,
        s_request.operation_descriptor.output_format));
    route_geometry_valid = output_chunk_count != 0;
    if (s_request.operation_descriptor.result_delivery_role) begin
      route_geometry_valid &= s_request.result_route_count != 0;
      for (int unsigned route = 0; route < MAX_RESULT_ROUTES; route++) begin
        if (route < s_request.result_route_count) begin
          if (route == 0) begin
            route_geometry_valid &= s_result_routes[route].chunk_first == 0;
          end else begin
            route_geometry_valid &= s_result_routes[route].chunk_first
                == s_result_routes[route-1].chunk_last + 1'b1;
          end
          route_geometry_valid &= s_result_routes[route].chunk_last < output_chunk_count;
          if (16'(route + 1) == s_request.result_route_count) begin
            route_geometry_valid &= s_result_routes[route].chunk_last == output_chunk_count - 1'b1;
          end
        end
      end
    end else begin
      route_geometry_valid &= s_request.result_route_count == 0;
    end
  end

  assign s_request_ready = (control_state == STATE_IDLE) && !m_result_valid;
  assign m_result = result_reg;
  assign selector_start = s_request_valid && s_request_ready
      && (s_request.header.command == PRISM_CMD_OP_PREPARE)
      && (s_request.decode_status == PRISM_STATUS_OK)
      && request_session_valid && request_group_valid
      && (request_group_state == PRISM_GROUP_INSTALLED)
      && !request_exact && !request_generation_mismatch && request_free
      && route_geometry_valid && selector_ready;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      control_state <= STATE_IDLE;
      pending_session_cookie <= '0;
      pending_group_id <= '0;
      pending_group_generation <= '0;
      pending_operation_id <= '0;
      pending_operation_generation <= '0;
      pending_descriptor <= '0;
      pending_result_route_count <= '0;
      pending_transaction <= '0;
      pending_slot <= '0;
      pending_group_slot <= '0;
      pending_expected_contributors <= '0;
      pending_session_job_id <= '0;
      result_reg <= '0;
      m_result_valid <= 1'b0;
      for (int unsigned slot = 0; slot < OPERATIONS; slot++) begin
        valid[slot] <= 1'b0;
        operation_state[slot] <= PRISM_OPERATION_FREE;
        session_cookie[slot] <= '0;
        key[slot] <= '0;
        group_slot[slot] <= '0;
        expected_contributors[slot] <= '0;
        descriptor[slot] <= '0;
        selected_width[slot] <= '0;
        width_index[slot] <= '0;
        accumulation_inexact[slot] <= 1'b0;
        prepare_transaction[slot] <= '0;
        for (int unsigned route = 0; route < MAX_RESULT_ROUTES; route++) begin
          routes[slot][route] <= '0;
        end
      end
    end else begin
      if (complete_operation_valid
          && (complete_operation_slot < 16'(OPERATIONS))
          && valid[SLOT_W'(complete_operation_slot)]
          && (operation_state[SLOT_W'(complete_operation_slot)]
              == PRISM_OPERATION_ACTIVE)) begin
        operation_state[SLOT_W'(complete_operation_slot)] <= PRISM_OPERATION_COMPLETE;
      end

      if (m_result_valid && m_result_ready) begin
        m_result_valid <= 1'b0;
        control_state <= STATE_IDLE;
      end

      if (s_request_valid && s_request_ready) begin
        result_reg <= '0;
        result_reg.header <= s_request.header;
        result_reg.status <= s_request.decode_status;
        result_reg.session_cookie <= s_request.header.session_cookie;
        result_reg.group_id <= s_request.group_id;
        result_reg.group_generation <= s_request.group_generation;
        result_reg.operation_id <= s_request.operation_id;
        result_reg.operation_generation <= s_request.operation_generation;

        if (s_request.decode_status != PRISM_STATUS_OK) begin
          m_result_valid <= 1'b1;
          control_state <= STATE_RESULT;
        end else begin
          case (s_request.header.command)
            PRISM_CMD_OP_PREPARE: begin
              if (!request_session_valid) begin
                result_reg.status <= PRISM_STATUS_STALE_SESSION;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (!request_group_valid) begin
                result_reg.status <= PRISM_STATUS_NOT_FOUND;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (request_group_state != PRISM_GROUP_INSTALLED) begin
                result_reg.status <= PRISM_STATUS_INVALID_STATE;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (request_replay) begin
                result_reg.operation_state <= operation_state[request_slot];
                result_reg.operation_slot <= 16'(request_slot);
                result_reg.selected_accumulator_width <= selected_width[request_slot];
                result_reg.accumulation_inexact <= accumulation_inexact[request_slot];
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (request_exact) begin
                result_reg.status <= PRISM_STATUS_ALREADY_EXISTS;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (request_generation_mismatch) begin
                result_reg.status <= PRISM_STATUS_GENERATION_MISMATCH;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (!request_free) begin
                result_reg.status <= PRISM_STATUS_NO_OPERATION_SLOT;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (!route_geometry_valid) begin
                result_reg.status <= PRISM_STATUS_INVALID_RECORD;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else if (!selector_ready) begin
                result_reg.status <= PRISM_STATUS_RETRY;
                m_result_valid <= 1'b1;
                control_state <= STATE_RESULT;
              end else begin
                pending_session_cookie <= s_request.header.session_cookie;
                pending_group_id <= s_request.group_id;
                pending_group_generation <= s_request.group_generation;
                pending_operation_id <= s_request.operation_id;
                pending_operation_generation <= s_request.operation_generation;
                pending_descriptor <= s_request.operation_descriptor;
                pending_result_route_count <= s_request.result_route_count;
                pending_transaction <= s_request.header.transaction_id;
                pending_slot <= request_slot;
                pending_group_slot <= request_group_slot;
                pending_expected_contributors <= request_group_expected_contributors;
                pending_session_job_id <= request_session_job_id;
                for (int unsigned route = 0; route < MAX_RESULT_ROUTES; route++) begin
                  pending_routes[route] <= s_result_routes[route];
                end
                control_state <= STATE_WAIT_WIDTH;
              end
            end

            PRISM_CMD_OP_COMMIT: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= request_generation_mismatch
                  ? PRISM_STATUS_GENERATION_MISMATCH : PRISM_STATUS_NOT_FOUND;
              else if (operation_state[request_slot] == PRISM_OPERATION_PREPARED) begin
                operation_state[request_slot] <= PRISM_OPERATION_ACTIVE;
                result_reg.operation_state <= PRISM_OPERATION_ACTIVE;
              end else if (operation_state[request_slot] == PRISM_OPERATION_ACTIVE) begin
                result_reg.operation_state <= PRISM_OPERATION_ACTIVE;
              end else result_reg.status <= PRISM_STATUS_INVALID_STATE;
              m_result_valid <= 1'b1;
              control_state <= STATE_RESULT;
            end

            PRISM_CMD_OP_ABORT: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= PRISM_STATUS_NOT_FOUND;
              else if ((operation_state[request_slot] == PRISM_OPERATION_PREPARED)
                  || (operation_state[request_slot] == PRISM_OPERATION_ACTIVE)) begin
                operation_state[request_slot] <= PRISM_OPERATION_ABORTED;
                result_reg.operation_state <= PRISM_OPERATION_ABORTED;
              end else if (operation_state[request_slot] == PRISM_OPERATION_ABORTED) begin
                result_reg.operation_state <= PRISM_OPERATION_ABORTED;
              end else result_reg.status <= PRISM_STATUS_INVALID_STATE;
              m_result_valid <= 1'b1;
              control_state <= STATE_RESULT;
            end

            PRISM_CMD_OP_STATUS: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= PRISM_STATUS_NOT_FOUND;
              else begin
                result_reg.operation_state <= operation_state[request_slot];
                result_reg.operation_slot <= 16'(request_slot);
                result_reg.selected_accumulator_width <= selected_width[request_slot];
                result_reg.accumulation_inexact <= accumulation_inexact[request_slot];
              end
              m_result_valid <= 1'b1;
              control_state <= STATE_RESULT;
            end

            PRISM_CMD_OP_RELEASE: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= PRISM_STATUS_NOT_FOUND;
              else if ((operation_state[request_slot] == PRISM_OPERATION_COMPLETE)
                  || (operation_state[request_slot] == PRISM_OPERATION_ABORTED)
                  || (operation_state[request_slot] == PRISM_OPERATION_PREPARED)) begin
                valid[request_slot] <= 1'b0;
                operation_state[request_slot] <= PRISM_OPERATION_FREE;
              end else result_reg.status <= PRISM_STATUS_OPERATION_BUSY;
              m_result_valid <= 1'b1;
              control_state <= STATE_RESULT;
            end

            default: begin
              result_reg.status <= PRISM_STATUS_UNSUPPORTED_COMMAND;
              m_result_valid <= 1'b1;
              control_state <= STATE_RESULT;
            end
          endcase
        end
      end

      if ((control_state == STATE_WAIT_WIDTH) && selector_valid) begin
        valid[pending_slot] <= 1'b1;
        operation_state[pending_slot] <= PRISM_OPERATION_PREPARED;
        session_cookie[pending_slot] <= pending_session_cookie;
        key[pending_slot] <= '{
          job_id: pending_session_job_id,
          group_id: pending_group_id,
          group_generation: pending_group_generation,
          operation_id: pending_operation_id,
          operation_generation: pending_operation_generation
        };
        group_slot[pending_slot] <= pending_group_slot;
        expected_contributors[pending_slot] <= pending_expected_contributors;
        descriptor[pending_slot] <= pending_descriptor;
        selected_width[pending_slot] <= (pending_descriptor.accumulator_profile
            == PRISM_ACC_KULISCH_FP32) ? selector_selected_width : 16'd32;
        width_index[pending_slot] <= selector_width_index;
        accumulation_inexact[pending_slot] <=
            (pending_descriptor.accumulator_profile == PRISM_ACC_KULISCH_FP32)
            && selector_inexact;
        prepare_transaction[pending_slot] <= pending_transaction;
        for (int unsigned route = 0; route < MAX_RESULT_ROUTES; route++) begin
          if (16'(route) < pending_result_route_count) begin
            routes[pending_slot][route] <= pending_routes[route];
          end
        end
        result_reg.operation_state <= PRISM_OPERATION_PREPARED;
        result_reg.operation_slot <= 16'(pending_slot);
        result_reg.selected_accumulator_width <=
            (pending_descriptor.accumulator_profile
                == PRISM_ACC_KULISCH_FP32) ? selector_selected_width : 16'd32;
        result_reg.accumulation_inexact <=
            (pending_descriptor.accumulator_profile == PRISM_ACC_KULISCH_FP32)
            && selector_inexact;
        result_reg.status <= PRISM_STATUS_OK;
        m_result_valid <= 1'b1;
        control_state <= STATE_RESULT;
      end
    end
  end

endmodule
