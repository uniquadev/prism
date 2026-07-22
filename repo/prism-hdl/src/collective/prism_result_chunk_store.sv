//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_result_chunk_store.sv
// Module: prism_result_chunk_store
// Description: Assembles converted tiles into immutable reference-counted chunks.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_result_chunk_store #(
    parameter int unsigned LANES = 16,
    parameter int unsigned SLOTS = 64,
    parameter int unsigned READ_PORTS = 2,
    parameter int unsigned OPERATION_CONTEXTS = 8
) (
    input  logic                                  clk,
    input  logic                                  rst_n,
    input  prism_pkg::prism_tile_meta_t           s_meta,
    input  logic [LANES*32-1:0]                   s_element_bits,
    input  logic [LANES-1:0]                      s_element_keep,
    input  logic                                  s_accumulation_inexact,
    input  logic                                  s_valid,
    output logic                                  s_ready,
    output prism_pkg::prism_result_chunk_meta_t   m_chunk_meta,
    output logic [15:0]                           m_chunk_slot,
    output logic                                  m_chunk_valid,
    input  logic                                  m_chunk_ready,
    input  logic                                  arm_valid,
    input  logic [15:0]                           arm_slot,
    input  logic [15:0]                           arm_reference_count,
    input  logic [READ_PORTS-1:0]                 release_valid,
    input  logic [15:0]                           release_slot [0:READ_PORTS-1],
    input  logic [15:0]                           read_slot [0:READ_PORTS-1],
    input  logic [15:0]                           read_offset [0:READ_PORTS-1],
    output logic [511:0]                          read_data [0:READ_PORTS-1],
    output logic [READ_PORTS-1:0]                 read_slot_armed,
    output logic                                  operation_complete_valid,
    output logic [15:0]                           operation_complete_slot
);

  import prism_pkg::*;

  localparam int unsigned SLOT_W = prism_clog2_safe(SLOTS);
  localparam int unsigned OPERATION_W = prism_clog2_safe(OPERATION_CONTEXTS);
  localparam int unsigned PAYLOAD_W = prism_clog2_safe(PRISM_CHUNK_PAYLOAD_BYTES);

  logic slot_valid [0:SLOTS-1];
  logic slot_ready [0:SLOTS-1];
  logic slot_claimed [0:SLOTS-1];
  logic [15:0] slot_references [0:SLOTS-1];
  prism_result_chunk_meta_t slot_meta [0:SLOTS-1];
  logic [15:0] received_elements [0:SLOTS-1];
  logic [7:0] payload_memory [0:SLOTS-1][0:PRISM_CHUNK_PAYLOAD_BYTES-1];
  logic [23:0] emitted_chunks [0:OPERATION_CONTEXTS-1];
  logic [23:0] next_chunk_to_route [0:OPERATION_CONTEXTS-1];
  logic completion_pending [0:OPERATION_CONTEXTS-1];
  logic [23:0] completed_chunks_this_cycle [0:OPERATION_CONTEXTS-1];
  logic [23:0] completion_total_chunks [0:OPERATION_CONTEXTS-1];
  logic completion_found;
  logic [15:0] completion_slot;

  logic [23:0] lane_chunk [0:LANES-1];
  logic [15:0] lane_chunk_offset [0:LANES-1];
  logic first_chunk_present;
  logic second_chunk_present;
  logic [23:0] first_chunk;
  logic [23:0] second_chunk;
  logic match_first, free_first, match_second, free_second;
  logic [SLOT_W-1:0] first_slot, second_slot;
  logic [15:0] first_incoming_count, second_incoming_count;
  logic [15:0] first_expected_elements, second_expected_elements;
  logic [15:0] bytes_per_element;
  logic [15:0] elements_per_chunk;
  logic [23:0] total_chunks;
  logic output_found;
  logic [SLOT_W-1:0] output_slot;
  logic [15:0] releases_for_slot [0:SLOTS-1];
  // Storage consumes result geometry; arithmetic-only tile metadata ends at this boundary.
  logic unused_tile_meta_fields;
  assign unused_tile_meta_fields = ^s_meta;

  initial begin
    if ((LANES < 1) || (SLOTS < 2) || (READ_PORTS < 1)
        || (OPERATION_CONTEXTS < 1)) begin
      $fatal(1, "prism_result_chunk_store parameters are illegal");
    end
  end

  always_comb begin
    bytes_per_element = 16'(prism_bytes_per_element(
        prism_wire_format_e'(s_meta.output_format)));
    elements_per_chunk = 16'(prism_elements_per_chunk(
        prism_wire_format_e'(s_meta.output_format)));
    total_chunks = 24'(prism_chunk_count(s_meta.total_element_count,
        prism_wire_format_e'(s_meta.output_format)));
    first_chunk_present = 1'b0;
    second_chunk_present = 1'b0;
    first_chunk = '0;
    second_chunk = '0;
    first_incoming_count = '0;
    second_incoming_count = '0;
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      lane_chunk[lane] = '0;
      lane_chunk_offset[lane] = '0;
      if (elements_per_chunk != 0) begin
        lane_chunk[lane] = 24'(
            (s_meta.first_element + 32'(lane)) / 32'(elements_per_chunk));
        lane_chunk_offset[lane] = 16'(
            (s_meta.first_element + 32'(lane)) % 32'(elements_per_chunk));
      end
      if (s_element_keep[lane]) begin
        if (!first_chunk_present) begin
          first_chunk_present = 1'b1;
          first_chunk = lane_chunk[lane];
        end else if ((lane_chunk[lane] != first_chunk) && !second_chunk_present) begin
          second_chunk_present = 1'b1;
          second_chunk = lane_chunk[lane];
        end
      end
    end
    for (int unsigned lane = 0; lane < LANES; lane++) begin
      if (s_element_keep[lane] && (lane_chunk[lane] == first_chunk)) begin
        first_incoming_count = first_incoming_count + 1'b1;
      end
      if (s_element_keep[lane] && second_chunk_present && (lane_chunk[lane] == second_chunk)) begin
        second_incoming_count = second_incoming_count + 1'b1;
      end
    end
    first_expected_elements = (first_chunk + 24'd1 == total_chunks)
        ? 16'(s_meta.total_element_count - first_chunk * elements_per_chunk)
        : elements_per_chunk;
    second_expected_elements = (second_chunk + 24'd1 == total_chunks)
        ? 16'(s_meta.total_element_count - second_chunk * elements_per_chunk)
        : elements_per_chunk;
  end

  always_comb begin
    match_first = 1'b0;
    free_first = 1'b0;
    first_slot = '0;
    match_second = 1'b0;
    free_second = 1'b0;
    second_slot = '0;
    for (int unsigned slot = 0; slot < SLOTS; slot++) begin
      if (slot_valid[slot] && (slot_meta[slot].operation_slot == s_meta.operation_slot)
          && (slot_meta[slot].chunk_index == first_chunk) && !match_first) begin
        match_first = 1'b1;
        first_slot = SLOT_W'(slot);
      end
    end
    if (!match_first) begin
      for (int unsigned slot = 0; slot < SLOTS; slot++) begin
        if (!slot_valid[slot] && !free_first) begin
          free_first = 1'b1;
          first_slot = SLOT_W'(slot);
        end
      end
    end
    if (second_chunk_present) begin
      for (int unsigned slot = 0; slot < SLOTS; slot++) begin
        if (slot_valid[slot] && (slot_meta[slot].operation_slot == s_meta.operation_slot)
            && (slot_meta[slot].chunk_index == second_chunk) && !match_second) begin
          match_second = 1'b1;
          second_slot = SLOT_W'(slot);
        end
      end
      if (!match_second) begin
        for (int unsigned slot = 0; slot < SLOTS; slot++) begin
          if (!slot_valid[slot] && (SLOT_W'(slot) != first_slot) && !free_second) begin
            free_second = 1'b1;
            second_slot = SLOT_W'(slot);
          end
        end
      end
    end
    s_ready = first_chunk_present && (bytes_per_element != 0)
        && (match_first || free_first)
        && (!slot_ready[first_slot]) && !slot_claimed[first_slot]
        && (!second_chunk_present || ((match_second || free_second)
            && !slot_ready[second_slot] && !slot_claimed[second_slot]));
  end

  always_comb begin
    output_found = 1'b0;
    output_slot = '0;
    for (int unsigned slot = 0; slot < SLOTS; slot++) begin
      if (slot_valid[slot] && slot_ready[slot] && !slot_claimed[slot]
          && (slot_references[slot] == 0)
          && (slot_meta[slot].operation_slot < 16'(OPERATION_CONTEXTS))
          && (slot_meta[slot].chunk_index
              == next_chunk_to_route[OPERATION_W'(slot_meta[slot].operation_slot)])
          && !output_found) begin
        output_found = 1'b1;
        output_slot = SLOT_W'(slot);
      end
    end
    m_chunk_meta = slot_meta[output_slot];
    m_chunk_slot = 16'(output_slot);
    m_chunk_valid = output_found;
  end

  always_comb begin
    for (int unsigned slot = 0; slot < SLOTS; slot++) begin
      releases_for_slot[slot] = '0;
      for (int unsigned port = 0; port < READ_PORTS; port++) begin
        if (release_valid[port] && (release_slot[port] == 16'(slot))) begin
          releases_for_slot[slot] = releases_for_slot[slot] + 1'b1;
        end
      end
    end
    for (int unsigned port = 0; port < READ_PORTS; port++) begin
      read_data[port] = '0;
      read_slot_armed[port] = 1'b0;
      if ((read_slot[port] < 16'(SLOTS))
          && slot_valid[SLOT_W'(read_slot[port])]) begin
        read_slot_armed[port] =
            (slot_references[SLOT_W'(read_slot[port])] != 0);
        for (int unsigned octet = 0; octet < 64; octet++) begin
          if (read_offset[port] + 16'(octet)
              < slot_meta[SLOT_W'(read_slot[port])].payload_bytes) begin
            read_data[port][octet*8 +: 8] =
                payload_memory[SLOT_W'(read_slot[port])]
                    [PAYLOAD_W'(read_offset[port] + 16'(octet))];
          end
        end
      end
    end
  end

  always_comb begin
    for (int unsigned operation = 0; operation < OPERATION_CONTEXTS; operation++) begin
      completed_chunks_this_cycle[operation] = '0;
      completion_total_chunks[operation] = '0;
    end
    for (int unsigned slot = 0; slot < SLOTS; slot++) begin
      if (slot_valid[slot] && (slot_references[slot] != 0)
          && (releases_for_slot[slot] >= slot_references[slot])
          && (slot_meta[slot].operation_slot < 16'(OPERATION_CONTEXTS))) begin
        completed_chunks_this_cycle[OPERATION_W'(slot_meta[slot].operation_slot)] =
            completed_chunks_this_cycle[OPERATION_W'(slot_meta[slot].operation_slot)]
            + 24'd1;
        completion_total_chunks[OPERATION_W'(slot_meta[slot].operation_slot)] =
            slot_meta[slot].total_chunks;
      end
    end
    completion_found = 1'b0;
    completion_slot = '0;
    for (int unsigned operation = 0; operation < OPERATION_CONTEXTS; operation++) begin
      if (completion_pending[operation] && !completion_found) begin
        completion_found = 1'b1;
        completion_slot = 16'(operation);
      end
    end
    operation_complete_valid = completion_found;
    operation_complete_slot = completion_slot;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      for (int unsigned slot = 0; slot < SLOTS; slot++) begin
        slot_valid[slot] <= 1'b0;
        slot_ready[slot] <= 1'b0;
        slot_claimed[slot] <= 1'b0;
        slot_references[slot] <= '0;
        slot_meta[slot] <= '0;
        received_elements[slot] <= '0;
      end
      for (int unsigned operation = 0; operation < OPERATION_CONTEXTS; operation++) begin
        emitted_chunks[operation] <= '0;
        next_chunk_to_route[operation] <= '0;
        completion_pending[operation] <= 1'b0;
      end
    end else begin
      if (operation_complete_valid) begin
        completion_pending[OPERATION_W'(completion_slot)] <= 1'b0;
      end

      if (s_valid && s_ready) begin
        if (!match_first) begin
          slot_valid[first_slot] <= 1'b1;
          slot_ready[first_slot] <= first_incoming_count == first_expected_elements;
          slot_claimed[first_slot] <= 1'b0;
          slot_references[first_slot] <= '0;
          received_elements[first_slot] <= first_incoming_count;
          slot_meta[first_slot] <= '{
            key: s_meta.key,
            operation_slot: s_meta.operation_slot,
            group_slot: s_meta.group_slot,
            semantic: s_meta.semantic,
            output_format: s_meta.output_format,
            result_route_count: s_meta.result_route_count,
            chunk_index: first_chunk,
            total_chunks: total_chunks,
            payload_bytes: first_expected_elements * bytes_per_element,
            accumulation_inexact: s_accumulation_inexact
          };
        end else begin
          received_elements[first_slot] <= received_elements[first_slot] + first_incoming_count;
          slot_ready[first_slot] <= received_elements[first_slot] + first_incoming_count
              == first_expected_elements;
          slot_meta[first_slot].accumulation_inexact <=
              slot_meta[first_slot].accumulation_inexact || s_accumulation_inexact;
        end

        if (second_chunk_present) begin
          if (!match_second) begin
            slot_valid[second_slot] <= 1'b1;
            slot_ready[second_slot] <= second_incoming_count == second_expected_elements;
            slot_claimed[second_slot] <= 1'b0;
            slot_references[second_slot] <= '0;
            received_elements[second_slot] <= second_incoming_count;
            slot_meta[second_slot] <= '{
              key: s_meta.key,
              operation_slot: s_meta.operation_slot,
              group_slot: s_meta.group_slot,
              semantic: s_meta.semantic,
              output_format: s_meta.output_format,
              result_route_count: s_meta.result_route_count,
              chunk_index: second_chunk,
              total_chunks: total_chunks,
              payload_bytes: second_expected_elements * bytes_per_element,
              accumulation_inexact: s_accumulation_inexact
            };
          end else begin
            received_elements[second_slot] <= received_elements[second_slot] + second_incoming_count;
            slot_ready[second_slot] <= received_elements[second_slot] + second_incoming_count
                == second_expected_elements;
            slot_meta[second_slot].accumulation_inexact <=
                slot_meta[second_slot].accumulation_inexact || s_accumulation_inexact;
          end
        end

        for (int unsigned lane = 0; lane < LANES; lane++) begin
          if (s_element_keep[lane]) begin
            for (int unsigned octet = 0; octet < 4; octet++) begin
              if (octet < bytes_per_element) begin
                if (lane_chunk[lane] == first_chunk) begin
                  payload_memory[first_slot][lane_chunk_offset[lane] * bytes_per_element + octet]
                      <= s_element_bits[lane*32 + octet*8 +: 8];
                end else begin
                  payload_memory[second_slot][lane_chunk_offset[lane] * bytes_per_element + octet]
                      <= s_element_bits[lane*32 + octet*8 +: 8];
                end
              end
            end
          end
        end
      end

      if (m_chunk_valid && m_chunk_ready) begin
        slot_claimed[output_slot] <= 1'b1;
        next_chunk_to_route[OPERATION_W'(slot_meta[output_slot].operation_slot)]
            <= next_chunk_to_route[OPERATION_W'(slot_meta[output_slot].operation_slot)] + 1'b1;
      end
      if (arm_valid && (arm_slot < 16'(SLOTS))
          && slot_claimed[SLOT_W'(arm_slot)]) begin
        slot_claimed[SLOT_W'(arm_slot)] <= 1'b0;
        slot_references[SLOT_W'(arm_slot)] <= arm_reference_count;
        if (arm_reference_count == 0) begin
          slot_valid[SLOT_W'(arm_slot)] <= 1'b0;
          slot_ready[SLOT_W'(arm_slot)] <= 1'b0;
        end
      end

      for (int unsigned slot = 0; slot < SLOTS; slot++) begin
        if (releases_for_slot[slot] != 0) begin
          if (releases_for_slot[slot] >= slot_references[slot]) begin
            slot_references[slot] <= '0;
            slot_valid[slot] <= 1'b0;
            slot_ready[slot] <= 1'b0;
          end else begin
            slot_references[slot] <= slot_references[slot] - releases_for_slot[slot];
          end
        end
      end
      for (int unsigned operation = 0; operation < OPERATION_CONTEXTS; operation++) begin
        if (completed_chunks_this_cycle[operation] != 0) begin
          if (emitted_chunks[operation] + completed_chunks_this_cycle[operation]
              >= completion_total_chunks[operation]) begin
            emitted_chunks[operation] <= '0;
            next_chunk_to_route[operation] <= '0;
            completion_pending[operation] <= 1'b1;
          end else begin
            emitted_chunks[operation] <= emitted_chunks[operation]
                + completed_chunks_this_cycle[operation];
          end
        end
      end
    end
  end

endmodule
