//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_group_table.sv
// Module: prism_group_table
// Description: Owns staged groups, contributor bindings, and replication entries.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_group_table #(
    parameter int unsigned GROUPS = 8,
    parameter int unsigned NUM_PORTS = 2,
    parameter int unsigned MAX_CONTRIBUTORS = 2,
    parameter int unsigned MAX_REPLICATION_ENTRIES = 2
) (
    input  logic                                      clk,
    input  logic                                      rst_n,
    input  prism_pkg::prism_control_request_t         s_request,
    input  prism_pkg::prism_contributor_binding_t     s_contributors [0:MAX_CONTRIBUTORS-1],
    input  prism_pkg::prism_replication_entry_t       s_replication_entries [0:MAX_REPLICATION_ENTRIES-1],
    input  logic                                      s_request_valid,
    output logic                                      s_request_ready,
    input  logic                                      request_session_valid,
    input  logic [63:0]                               request_session_job_id,
    input  logic                                      request_group_has_operations,
    output prism_pkg::prism_control_result_t          m_result,
    output logic                                      m_result_valid,
    input  logic                                      m_result_ready,
    input  logic [63:0]                               session_query_cookie,
    output logic                                      session_has_groups,
    input  logic [63:0]                               lookup_job_id,
    input  logic [15:0]                               lookup_group_id,
    input  logic [15:0]                               lookup_group_generation,
    output logic                                      lookup_valid,
    output logic [15:0]                               lookup_slot,
    output prism_pkg::prism_group_state_e             lookup_state,
    output prism_pkg::prism_group_descriptor_t        lookup_descriptor,
    input  logic [15:0]                               contributor_lookup_slot,
    input  logic [15:0]                               contributor_lookup_id,
    output logic                                      contributor_lookup_valid,
    output prism_pkg::prism_contributor_binding_t     contributor_lookup_binding,
    input  logic [15:0]                               replication_lookup_slot,
    input  logic [15:0]                               replication_lookup_index,
    output logic                                      replication_lookup_valid,
    output prism_pkg::prism_replication_entry_t       replication_lookup_entry,
    output logic [15:0]                               replication_lookup_count
);

  import prism_pkg::*;

  localparam int unsigned SLOT_W = prism_clog2_safe(GROUPS);
  localparam int unsigned CONTRIBUTOR_W = prism_clog2_safe(MAX_CONTRIBUTORS);
  localparam int unsigned REPLICATION_W = prism_clog2_safe(MAX_REPLICATION_ENTRIES);

  logic valid [0:GROUPS-1];
  prism_group_state_e state [0:GROUPS-1];
  logic [63:0] session_cookie [0:GROUPS-1];
  logic [63:0] job_id [0:GROUPS-1];
  logic [15:0] group_id [0:GROUPS-1];
  logic [15:0] group_generation [0:GROUPS-1];
  prism_group_descriptor_t descriptor [0:GROUPS-1];
  logic [15:0] contributor_count [0:GROUPS-1];
  prism_contributor_binding_t contributors [0:GROUPS-1][0:MAX_CONTRIBUTORS-1];
  logic [15:0] replication_count [0:GROUPS-1];
  prism_replication_entry_t replication_entries [0:GROUPS-1][0:MAX_REPLICATION_ENTRIES-1];
  logic [63:0] stage_transaction [0:GROUPS-1];

  logic request_exact;
  logic request_generation_mismatch;
  logic request_free;
  logic request_replay;
  logic [SLOT_W-1:0] request_slot;
  logic stage_config_valid;
  prism_control_result_t result_reg;
  // The shared request envelope contains fields owned by the session and operation tables.
  logic unused_request_fields;
  assign unused_request_fields = ^s_request;

  initial begin
    if ((GROUPS < 1) || (NUM_PORTS < 1) || (MAX_CONTRIBUTORS < 1)
        || (MAX_REPLICATION_ENTRIES < 1)) begin
      $fatal(1, "prism_group_table parameters are illegal");
    end
  end

  always_comb begin
    session_has_groups = 1'b0;
    lookup_valid = 1'b0;
    lookup_slot = '0;
    lookup_state = PRISM_GROUP_FREE;
    lookup_descriptor = '0;
    for (int unsigned slot = 0; slot < GROUPS; slot++) begin
      if (valid[slot] && (session_cookie[slot] == session_query_cookie)) begin
        session_has_groups = 1'b1;
      end
      if (valid[slot] && (job_id[slot] == lookup_job_id)
          && (group_id[slot] == lookup_group_id)
          && (group_generation[slot] == lookup_group_generation) && !lookup_valid) begin
        lookup_valid = 1'b1;
        lookup_slot = 16'(slot);
        lookup_state = state[slot];
        lookup_descriptor = descriptor[slot];
      end
    end

    contributor_lookup_valid = 1'b0;
    contributor_lookup_binding = '0;
    if ((contributor_lookup_slot < 16'(GROUPS))
        && valid[SLOT_W'(contributor_lookup_slot)]
        && (contributor_lookup_id
            < contributor_count[SLOT_W'(contributor_lookup_slot)])) begin
      contributor_lookup_valid = 1'b1;
      contributor_lookup_binding = contributors[SLOT_W'(contributor_lookup_slot)]
          [CONTRIBUTOR_W'(contributor_lookup_id)];
    end

    replication_lookup_valid = 1'b0;
    replication_lookup_entry = '0;
    replication_lookup_count = '0;
    if ((replication_lookup_slot < 16'(GROUPS))
        && valid[SLOT_W'(replication_lookup_slot)]) begin
      replication_lookup_count = replication_count[SLOT_W'(replication_lookup_slot)];
      if (replication_lookup_index
          < replication_count[SLOT_W'(replication_lookup_slot)]) begin
        replication_lookup_valid = 1'b1;
        replication_lookup_entry = replication_entries[SLOT_W'(replication_lookup_slot)]
            [REPLICATION_W'(replication_lookup_index)];
      end
    end
  end

  always_comb begin
    request_exact = 1'b0;
    request_generation_mismatch = 1'b0;
    request_free = 1'b0;
    request_replay = 1'b0;
    request_slot = '0;
    for (int unsigned slot = 0; slot < GROUPS; slot++) begin
      if (valid[slot] && (session_cookie[slot] == s_request.header.session_cookie)
          && (group_id[slot] == s_request.group_id)) begin
        if ((group_generation[slot] == s_request.group_generation) && !request_exact) begin
          request_exact = 1'b1;
          request_slot = SLOT_W'(slot);
          request_replay = (stage_transaction[slot] == s_request.header.transaction_id);
        end else if (group_generation[slot] != s_request.group_generation) begin
          request_generation_mismatch = 1'b1;
        end
      end
    end
    if (!request_exact) begin
      for (int unsigned slot = 0; slot < GROUPS; slot++) begin
        if (!valid[slot] && !request_free) begin
          request_free = 1'b1;
          request_slot = SLOT_W'(slot);
        end
      end
    end

    stage_config_valid = request_session_valid
        && (s_request.group_descriptor.node_role == PRISM_ROLE_SINGLE)
        && !s_request.upstream_action.has_parent
        && (s_request.contributor_count == s_request.group_descriptor.expected_local_contributors)
        && (s_request.contributor_count <= 16'(MAX_CONTRIBUTORS))
        && (s_request.replication_entry_count <= 16'(MAX_REPLICATION_ENTRIES));
    for (int unsigned contributor = 0; contributor < MAX_CONTRIBUTORS; contributor++) begin
      if (contributor < s_request.contributor_count) begin
        stage_config_valid &=
            s_contributors[contributor].contributor_id == 16'(contributor);
        stage_config_valid &=
            s_contributors[contributor].ingress_port < 16'(NUM_PORTS);
        for (int unsigned prior = 0; prior < MAX_CONTRIBUTORS; prior++) begin
          if (prior < contributor) begin
            stage_config_valid &= !((s_contributors[prior].ingress_port
                == s_contributors[contributor].ingress_port)
                && (s_contributors[prior].source_mac == s_contributors[contributor].source_mac));
          end
        end
      end
    end
    for (int unsigned entry = 0; entry < MAX_REPLICATION_ENTRIES; entry++) begin
      if (entry < s_request.replication_entry_count) begin
        stage_config_valid &=
            s_replication_entries[entry].egress_port < 16'(NUM_PORTS);
        stage_config_valid &= s_replication_entries[entry].next_hop_type == 8'h02;
        for (int unsigned prior = 0; prior < MAX_REPLICATION_ENTRIES; prior++) begin
          if (prior < entry) begin
            stage_config_valid &= !((s_replication_entries[prior].replication_group_id
                == s_replication_entries[entry].replication_group_id)
                && (s_replication_entries[prior].result_path_id
                    == s_replication_entries[entry].result_path_id));
          end
        end
      end
    end
  end

  assign s_request_ready = !m_result_valid || m_result_ready;
  assign m_result = result_reg;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      result_reg <= '0;
      m_result_valid <= 1'b0;
      for (int unsigned slot = 0; slot < GROUPS; slot++) begin
        valid[slot] <= 1'b0;
        state[slot] <= PRISM_GROUP_FREE;
        session_cookie[slot] <= '0;
        job_id[slot] <= '0;
        group_id[slot] <= '0;
        group_generation[slot] <= '0;
        descriptor[slot] <= '0;
        contributor_count[slot] <= '0;
        replication_count[slot] <= '0;
        stage_transaction[slot] <= '0;
        for (int unsigned contributor = 0; contributor < MAX_CONTRIBUTORS; contributor++) begin
          contributors[slot][contributor] <= '0;
        end
        for (int unsigned entry = 0; entry < MAX_REPLICATION_ENTRIES; entry++) begin
          replication_entries[slot][entry] <= '0;
        end
      end
    end else begin
      if (m_result_valid && m_result_ready) m_result_valid <= 1'b0;

      if (s_request_valid && s_request_ready) begin
        result_reg <= '0;
        result_reg.header <= s_request.header;
        result_reg.status <= s_request.decode_status;
        result_reg.session_cookie <= s_request.header.session_cookie;
        result_reg.group_id <= s_request.group_id;
        result_reg.group_generation <= s_request.group_generation;
        m_result_valid <= 1'b1;

        if (s_request.decode_status == PRISM_STATUS_OK) begin
          case (s_request.header.command)
            PRISM_CMD_GROUP_STAGE: begin
              if (!request_session_valid) begin
                result_reg.status <= PRISM_STATUS_STALE_SESSION;
              end else if (request_replay) begin
                result_reg.group_state <= state[request_slot];
              end else if (request_exact) begin
                result_reg.status <= PRISM_STATUS_ALREADY_EXISTS;
              end else if (request_generation_mismatch) begin
                result_reg.status <= PRISM_STATUS_GENERATION_MISMATCH;
              end else if (!request_free) begin
                result_reg.status <= PRISM_STATUS_NO_GROUP_SLOT;
              end else if (!stage_config_valid) begin
                result_reg.status <= PRISM_STATUS_INVALID_RECORD;
              end else begin
                valid[request_slot] <= 1'b1;
                state[request_slot] <= PRISM_GROUP_STAGED;
                session_cookie[request_slot] <= s_request.header.session_cookie;
                job_id[request_slot] <= request_session_job_id;
                group_id[request_slot] <= s_request.group_id;
                group_generation[request_slot] <= s_request.group_generation;
                descriptor[request_slot] <= s_request.group_descriptor;
                contributor_count[request_slot] <= s_request.contributor_count;
                replication_count[request_slot] <= s_request.replication_entry_count;
                stage_transaction[request_slot] <= s_request.header.transaction_id;
                result_reg.group_state <= PRISM_GROUP_STAGED;
                for (int unsigned contributor = 0; contributor < MAX_CONTRIBUTORS; contributor++) begin
                  if (contributor < s_request.contributor_count) begin
                    contributors[request_slot][contributor] <= s_contributors[contributor];
                  end
                end
                for (int unsigned entry = 0; entry < MAX_REPLICATION_ENTRIES; entry++) begin
                  if (entry < s_request.replication_entry_count) begin
                    replication_entries[request_slot][entry] <= s_replication_entries[entry];
                  end
                end
              end
            end

            PRISM_CMD_GROUP_COMMIT: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= request_generation_mismatch
                  ? PRISM_STATUS_GENERATION_MISMATCH : PRISM_STATUS_NOT_FOUND;
              else if (state[request_slot] == PRISM_GROUP_STAGED) begin
                state[request_slot] <= PRISM_GROUP_INSTALLED;
                result_reg.group_state <= PRISM_GROUP_INSTALLED;
              end else if (state[request_slot] == PRISM_GROUP_INSTALLED) begin
                result_reg.group_state <= PRISM_GROUP_INSTALLED;
              end else result_reg.status <= PRISM_STATUS_INVALID_STATE;
            end

            PRISM_CMD_GROUP_ABORT: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= PRISM_STATUS_NOT_FOUND;
              else if (state[request_slot] != PRISM_GROUP_STAGED) begin
                result_reg.status <= PRISM_STATUS_INVALID_STATE;
              end else begin
                valid[request_slot] <= 1'b0;
                state[request_slot] <= PRISM_GROUP_FREE;
              end
            end

            PRISM_CMD_GROUP_STATUS: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= PRISM_STATUS_NOT_FOUND;
              else result_reg.group_state <= state[request_slot];
            end

            PRISM_CMD_GROUP_DESTROY: begin
              if (!request_session_valid) result_reg.status <= PRISM_STATUS_STALE_SESSION;
              else if (!request_exact) result_reg.status <= PRISM_STATUS_NOT_FOUND;
              else if (state[request_slot] != PRISM_GROUP_INSTALLED) begin
                result_reg.status <= PRISM_STATUS_INVALID_STATE;
              end else if (request_group_has_operations) begin
                result_reg.status <= PRISM_STATUS_GROUP_BUSY;
              end else begin
                valid[request_slot] <= 1'b0;
                state[request_slot] <= PRISM_GROUP_FREE;
              end
            end

            default: result_reg.status <= PRISM_STATUS_UNSUPPORTED_COMMAND;
          endcase
        end
      end
    end
  end

endmodule
