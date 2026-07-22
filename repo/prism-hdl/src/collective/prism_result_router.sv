//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_result_router.sv
// Module: prism_result_router
// Description: Expands completed chunks into bounded per-destination packet jobs.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_result_router (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_result_chunk_meta_t       s_chunk_meta,
    input  logic [15:0]                               s_chunk_slot,
    input  logic                                      s_chunk_valid,
    output logic                                      s_chunk_ready,
    output logic [15:0]                               route_lookup_slot,
    output logic [15:0]                               route_lookup_index,
    input  logic                                      route_lookup_valid,
    input  prism_pkg::prism_result_route_t            route_lookup_route,
    output logic [15:0]                               replication_lookup_slot,
    output logic [15:0]                               replication_lookup_index,
    input  logic                                      replication_lookup_valid,
    input  prism_pkg::prism_replication_entry_t       replication_lookup_entry,
    input  logic [15:0]                               replication_lookup_count,
    output prism_pkg::prism_result_packet_job_t       m_job,
    output logic                                      m_job_valid,
    input  logic                                      m_job_ready,
    output logic                                      arm_valid,
    output logic [15:0]                               arm_slot,
    output logic [15:0]                               arm_reference_count
);

  import prism_pkg::*;

  typedef enum logic [2:0] {STATE_IDLE, STATE_ROUTE, STATE_REPLICATION, STATE_ARM} state_e;
  state_e state;
  prism_result_chunk_meta_t chunk_reg;
  logic [15:0] chunk_slot_reg;
  logic [15:0] route_index_reg;
  logic [15:0] replication_index_reg;
  logic [15:0] selected_replication_group;
  logic [15:0] job_count;
  logic route_matches;
  logic replication_matches;
  // The router carries the canonical replication entry; next-hop validation belongs to staging.
  logic unused_replication_entry_fields;
  assign unused_replication_entry_fields = ^replication_lookup_entry;

  assign s_chunk_ready = state == STATE_IDLE;
  assign route_lookup_slot = chunk_reg.operation_slot;
  assign route_lookup_index = route_index_reg;
  assign replication_lookup_slot = chunk_reg.group_slot;
  assign replication_lookup_index = replication_index_reg;
  assign route_matches = route_lookup_valid
      && (chunk_reg.chunk_index >= route_lookup_route.chunk_first)
      && (chunk_reg.chunk_index <= route_lookup_route.chunk_last);
  assign replication_matches = replication_lookup_valid
      && (replication_lookup_entry.replication_group_id == selected_replication_group);

  always_comb begin
    m_job = '0;
    m_job.chunk_slot = chunk_slot_reg;
    m_job.chunk = chunk_reg;
    m_job.result_path_id = replication_lookup_entry.result_path_id;
    m_job.egress_port = replication_lookup_entry.egress_port;
    m_job.destination_mac = replication_lookup_entry.destination_mac;
    m_job_valid = (state == STATE_REPLICATION) && replication_matches;
    arm_valid = state == STATE_ARM;
    arm_slot = chunk_slot_reg;
    arm_reference_count = job_count;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= STATE_IDLE;
      chunk_reg <= '0;
      chunk_slot_reg <= '0;
      route_index_reg <= '0;
      replication_index_reg <= '0;
      selected_replication_group <= '0;
      job_count <= '0;
    end else begin
      case (state)
        STATE_IDLE: begin
          if (s_chunk_valid && s_chunk_ready) begin
            chunk_reg <= s_chunk_meta;
            chunk_slot_reg <= s_chunk_slot;
            route_index_reg <= '0;
            job_count <= '0;
            state <= (s_chunk_meta.result_route_count == 0) ? STATE_ARM : STATE_ROUTE;
          end
        end

        STATE_ROUTE: begin
          if (route_matches) begin
            selected_replication_group <= route_lookup_route.replication_group_id;
            replication_index_reg <= '0;
            state <= STATE_REPLICATION;
          end else if (route_index_reg + 1'b1 >= chunk_reg.result_route_count) begin
            state <= STATE_ARM;
          end else begin
            route_index_reg <= route_index_reg + 1'b1;
          end
        end

        STATE_REPLICATION: begin
          if (!replication_matches || (m_job_valid && m_job_ready)) begin
            if (replication_matches) job_count <= job_count + 1'b1;
            if (replication_index_reg + 1'b1 >= replication_lookup_count) begin
              state <= STATE_ARM;
            end else begin
              replication_index_reg <= replication_index_reg + 1'b1;
            end
          end
        end

        STATE_ARM: state <= STATE_IDLE;
        default: state <= STATE_IDLE;
      endcase
    end
  end

endmodule
