//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_frame_planner.sv
// Module: prism_numbergroup_frame_planner
// Description: Assigns encoded tiles to frames and plans group coalescing and count patches.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Tiles are appended to the frame being built in one of two banks. A uniform
// tile opens a group that later uniform tiles of the same format extend; the
// count in its descriptor is then patched once, when the group ends. A group
// that was never extended already has its count and needs no patch.
//
// A tile that does not fit closes the frame. When the other bank is free and
// no patch is due, the same tile starts the next frame there in the same
// cycle, so a stream of small tiles loses no cycle between frames.
//
// What a tile is compared with is kept ready in registers: the bytes, groups
// and elements the open frame can still take, and the elements of the vector
// still to come. A decision is then one comparison per limit instead of a sum
// followed by a comparison. The plan of a tile leaves through a register.
module prism_numbergroup_frame_planner #(
    parameter int unsigned MTU_BYTES = 1500,
    parameter int unsigned HEADER_W = 448
) (
    input logic clk, rst_n, s_reset,
    input logic [HEADER_W-1:0] s_header,
    input logic [31:0] s_packet_id, s_total_elements, s_first_element,
    input logic [15:0] s_mtu, s_kulisch_bits, s_count, s_bytes,
    input logic [7:0] s_groups, s_first_frame_tiles, s_format,
    input logic s_uniform, s_encoding_valid, s_valid,
    // The single run of a uniform tile ends with padding bytes.
    input logic s_padded,
    output logic s_ready,
    output logic m_tile_valid,
    input logic m_tile_ready,
    output logic m_tile_bank, m_tile_strip_descriptor,
    output logic [15:0] m_tile_offset, m_tile_bytes,
    output logic m_patch_valid,
    input logic m_patch_ready,
    output logic m_patch_bank,
    output logic [15:0] m_patch_offset, m_patch_count,
    output logic [1:0] m_frame_valid,
    input logic [1:0] m_frame_ready,
    output logic [2*HEADER_W-1:0] m_frame_header,
    output logic [63:0] m_frame_packet_id, m_frame_first_element,
    output logic [31:0] m_frame_elements, m_frame_bytes,
    output logic [15:0] m_frame_groups,
    output logic [1:0] m_frame_last, m_bank_busy,
    input logic s_release_valid, s_release_bank,
    output logic m_fault
);
    localparam int unsigned OVERHEAD_BYTES = 42;
    logic bank, active, closing, known;
    logic [1:0] closed;
    logic [31:0] next_global, serial, total;
    logic [15:0] mtu, width, elements, body_bytes;
    logic [7:0] groups, first_tiles;
    logic open_valid, open_padded, open_extended;
    logic [7:0] open_format;
    logic [15:0] open_offset, open_count;
    logic extend_group, extending, patch_due, need_patch, fits, context_match;
    logic turn_over, admit, close_frame;
    logic [15:0] effective_bytes;
    logic [7:0] effective_groups;
    logic tile_fire, patch_fire, reset_context, valid_tile;
    logic [16:0] next_bytes, next_elements;
    logic [8:0] next_groups;
    // Bytes the open frame can still take, with and without the descriptor
    // of the tile; its groups and elements; the elements of the vector not
    // yet planned, valid once the operation is known.
    logic [15:0] room, room_extended, elements_left, frame_limit;
    logic [15:0] base_room, base_elements_left;
    logic [7:0] groups_left, base_groups_left;
    logic [31:0] vector_left, base_vector_left, next_vector_left;
    logic vector_left_high, base_vector_left_high, count_in_vector, last_tile;
    logic [32:0] packet_id_sum;
    logic stage_free, emit;

    // A group that ends with padding is closed: values appended after the
    // padding would not follow the values of the group.
    assign extend_group = active && open_valid && !open_padded && s_uniform
        && s_format == open_format;
    assign effective_bytes = s_bytes - (extend_group ? 16'd4 : 16'd0);
    assign effective_groups = extend_group ? 8'd0 : s_groups;
    // Compute both admission decisions before selecting descriptor coalescing.
    // Preserve the 16-bit subtraction even for malformed geometry.
    logic [15:0] stripped_bytes;
    logic [16:0] separate_next_bytes, extended_next_bytes;
    logic separate_fits, extended_fits, byte_limit_valid;
    assign stripped_bytes = s_bytes - 16'd4;
    assign separate_next_bytes = {1'b0,body_bytes}+{1'b0,s_bytes};
    assign extended_next_bytes = {1'b0,body_bytes}+{1'b0,stripped_bytes};
    assign next_bytes = extend_group ? extended_next_bytes : separate_next_bytes;
    assign next_elements = {1'b0,elements}+{1'b0,s_count};
    assign next_groups = {1'b0,groups}+{1'b0,effective_groups};
    assign separate_fits = s_bytes <= room && s_groups <= groups_left
        && s_count <= elements_left;
    assign extended_fits = s_bytes <= room_extended && s_count <= elements_left;
    assign fits = extend_group ? extended_fits : separate_fits;
    // An empty frame has all its room.
    assign frame_limit = s_mtu - 16'(OVERHEAD_BYTES);
    assign base_room = active ? room : frame_limit;
    assign base_groups_left = active ? groups_left : 8'd255;
    assign base_elements_left = active ? elements_left : 16'hffff;
    assign base_vector_left = known ? vector_left : s_total_elements;
    assign base_vector_left_high = known ? vector_left_high : |s_total_elements[31:16];
    assign next_vector_left = base_vector_left - 32'(s_count);
    assign count_in_vector = base_vector_left_high || s_count <= base_vector_left[15:0];
    assign last_tile = !base_vector_left_high && s_count == base_vector_left[15:0];
    assign packet_id_sum = {1'b0,s_packet_id}+{1'b0,serial};
    assign byte_limit_valid = extend_group
        ? stripped_bytes <= s_mtu-16'(OVERHEAD_BYTES)
        : s_bytes <= s_mtu-16'(OVERHEAD_BYTES);
    assign context_match = !known || (s_total_elements==total && s_mtu==mtu && s_kulisch_bits==width);
    // A non-fitting next tile closes the current group without consuming
    // that tile. Queue its patch immediately; no extra closing-state cycle.
    assign patch_due = active && open_valid && open_extended;
    assign need_patch = patch_due
        && (closing || (s_valid && (!extend_group || !fits)));
    assign turn_over = s_valid && active && !closing && !fits && !patch_due
        && !m_bank_busy[!bank];
    assign extending = extend_group && !turn_over;
    assign admit = !m_fault && !s_reset && !closing && !need_patch && context_match
        && (active ? fits || turn_over : !m_bank_busy[bank]);
    assign close_frame = (closing || (s_valid && active && !fits))
        && (!patch_due || patch_fire);
    assign m_patch_valid = need_patch && !m_fault && !s_reset;
    assign m_patch_bank = bank;
    assign m_patch_offset = open_offset;
    assign m_patch_count = open_count;
    assign patch_fire = m_patch_valid && m_patch_ready;
    // The plan register takes a tile whenever it is empty or its plan leaves.
    assign stage_free = !m_tile_valid || m_tile_ready;
    assign s_ready = admit && stage_free;
    assign tile_fire = s_valid && s_ready;
    assign emit = tile_fire && valid_tile;
    always_ff @(posedge clk) begin
        if (stage_free) begin
            m_tile_bank <= turn_over ? !bank : bank;
            m_tile_offset <= turn_over ? 16'd0 : body_bytes;
            m_tile_bytes <= turn_over ? s_bytes : effective_bytes;
            m_tile_strip_descriptor <= extending;
        end
    end
    always_ff @(posedge clk) begin
        if (!rst_n || reset_context) m_tile_valid <= 1'b0;
        else if (stage_free) m_tile_valid <= emit;
    end
    assign reset_context = s_reset && m_bank_busy == 0;
    assign valid_tile = s_encoding_valid && s_count != 0 && s_bytes >= 4
        && s_groups != 0 && s_bytes <= 16'(MTU_BYTES-OVERHEAD_BYTES)
        && s_mtu >= 576 && s_mtu <= 16'(MTU_BYTES)
        && s_kulisch_bits >= 278 && s_kulisch_bits <= 4096
        && s_total_elements != 0 && s_first_element == next_global
        && count_in_vector
        && byte_limit_valid
        // The packet id of the frame this tile opens does not wrap.
        && (active || !packet_id_sum[32])
        && (!turn_over || (!packet_id_sum[32] && packet_id_sum[31:0] != 32'hffff_ffff));

    always_ff @(posedge clk) begin
        if (!rst_n || reset_context) begin
            bank <= 0; active <= 0; closing <= 0; known <= 0;
            closed <= 0; next_global <= 0; serial <= 0; total <= 0;
            mtu <= 0; width <= 0; elements <= 0; body_bytes <= 0;
            groups <= 0; first_tiles <= 0;
            open_valid <= 0; open_padded <= 0; open_extended <= 0;
            open_format <= 0; open_offset <= 0; open_count <= 0;
            room <= 0; room_extended <= 0; groups_left <= 0; elements_left <= 0;
            vector_left <= 0; vector_left_high <= 0;
            m_frame_valid <= 0; m_bank_busy <= 0;
            m_frame_elements <= 0; m_frame_bytes <= 0;
            m_frame_groups <= 0; m_frame_last <= 0; m_fault <= 0;
        end else begin
            m_frame_valid <= m_frame_valid & ~m_frame_ready;
            if (s_release_valid) begin
                // Release means both writer and transmitter have completed.
                if (!closed[s_release_bank] || !m_bank_busy[s_release_bank]
                    || (m_frame_valid[s_release_bank] && !m_frame_ready[s_release_bank]))
                    m_fault <= 1;
                else begin
                    m_bank_busy[s_release_bank] <= 0;
                    closed[s_release_bank] <= 0;
                end
            end
            if (!m_fault && !s_reset) begin
                if (patch_fire) open_valid <= 0;
                if (s_valid && active && !closing && !fits) closing <= 1;
                // A tile that fails its checks raises the fault, which stops
                // the planner for good. Only what the fault does not cover is
                // kept from such a tile: the bank it would have opened stays
                // free. The counts of the frame take it like any other tile,
                // so the checks stay out of their way.
                if (tile_fire) begin
                    if (!valid_tile) m_fault <= 1;
                    if (!turn_over) begin
                        if (!active && valid_tile) begin
                            active <= 1;
                            m_bank_busy[bank] <= 1;
                        end
                        known <= 1; total <= s_total_elements; mtu <= s_mtu; width <= s_kulisch_bits;
                        next_global <= next_global+32'(s_count);
                        vector_left <= next_vector_left;
                        vector_left_high <= |next_vector_left[31:16];
                        elements <= next_elements[15:0];
                        body_bytes <= next_bytes[15:0];
                        groups <= next_groups[7:0];
                        room <= base_room-effective_bytes;
                        room_extended <= base_room-effective_bytes+16'd4;
                        groups_left <= base_groups_left-effective_groups;
                        elements_left <= base_elements_left-s_count;
                        if (serial==0 && s_first_frame_tiles!=0) first_tiles <= first_tiles+8'd1;
                        // A group still open here was never extended: it is
                        // left as it is when this tile does not extend it.
                        if (extending) begin
                            open_count <= open_count+s_count;
                            open_extended <= 1;
                        end else begin
                            open_valid <= s_uniform; open_extended <= 0;
                            open_format <= s_format;
                            open_offset <= body_bytes; open_count <= s_count;
                        end
                        if (s_uniform) open_padded <= s_padded;
                        if (last_tile
                            || (serial==0 && s_first_frame_tiles!=0
                                && first_tiles+8'd1>=s_first_frame_tiles)) closing <= 1;
                    end
                end
                // The final patch is already queued when patch_fire is true.
                // Store publication remains gated by patch completion.
                if (close_frame) begin
                    m_frame_elements[bank*16 +: 16] <= elements;
                    m_frame_bytes[bank*16 +: 16] <= body_bytes;
                    m_frame_groups[bank*8 +: 8] <= groups;
                    m_frame_last[bank] <= next_global==total;
                    m_frame_valid[bank] <= 1;
                    closed[bank] <= 1;
                    bank <= !bank; active <= 0; closing <= 0;
                    elements <= 0; body_bytes <= 0; groups <= 0;
                    open_valid <= 0;
                    serial <= serial+32'd1;
                end
                // The tile that did not fit is the first of the next frame.
                if (tile_fire && turn_over) begin
                    if (valid_tile) begin
                        active <= 1;
                        m_bank_busy[!bank] <= 1;
                    end
                    next_global <= next_global+32'(s_count);
                    vector_left <= next_vector_left;
                    vector_left_high <= |next_vector_left[31:16];
                    elements <= s_count;
                    body_bytes <= s_bytes;
                    groups <= s_groups;
                    room <= frame_limit-s_bytes;
                    room_extended <= frame_limit-s_bytes+16'd4;
                    groups_left <= 8'd255-s_groups;
                    elements_left <= 16'hffff-s_count;
                    open_valid <= s_uniform; open_extended <= 0; open_padded <= s_padded;
                    open_format <= s_format; open_offset <= 0; open_count <= s_count;
                    if (last_tile) closing <= 1;
                end
            end
        end
    end

    // The header, the packet id and the first element of a frame come from
    // the tile that opens it. They are taken from the tile at the head of the
    // queue whenever the bank it would open is free, whether or not the tile
    // is accepted in that cycle: the tile stays at the head until it is, and a
    // free bank needs none of the three. The wide header registers are so
    // loaded without waiting for the checks of the tile.
    always_ff @(posedge clk) begin
        if (s_valid && !active && !m_bank_busy[bank]) begin
            m_frame_header[bank*HEADER_W +: HEADER_W] <= s_header;
            m_frame_packet_id[bank*32 +: 32] <= packet_id_sum[31:0];
            m_frame_first_element[bank*32 +: 32] <= s_first_element;
        end
        if (s_valid && active && !m_bank_busy[!bank]) begin
            m_frame_header[(!bank)*HEADER_W +: HEADER_W] <= s_header;
            m_frame_packet_id[(!bank)*32 +: 32] <= packet_id_sum[31:0]+32'd1;
            m_frame_first_element[(!bank)*32 +: 32] <= s_first_element;
        end
    end
endmodule
