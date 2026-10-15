//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_committed_store.sv
// Module: prism_numbergroup_committed_store
// Description: Appends encoded chunks to two frame buffers, patches group counts and transmits.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// Two frames are built at a time, each in two memories of 64-byte words
// (even and odd words) so that a chunk can complete two words in one cycle.
// The bytes of the word being filled wait in a residual register.
//
// A chunk extends the body of its frame: its offset is the number of body
// bytes written so far, and it arrives already moved to its position inside
// a word (the body starts 56 bytes into the first word, after the header).
// A patch rewrites the count of a group descriptor that is already stored.
// If the descriptor is still in the residual register it is changed there;
// otherwise its word is read in one cycle and written back in the next.
// Either way appending waits for a single cycle. The first descriptor of a
// body, the one a frame with a single group patches when it closes, is kept
// in a register and patched there at once. A frame is transmitted once its
// header is known and no patch is pending for it.
//
// The memories are written from registers, one cycle after a word is
// complete. The transmitter therefore sees a word one cycle after it is
// counted, a patch that reads a word still on its way takes it from the write
// register, and a patch written to a memory counts as done one cycle later.
// What decides a write does not wait for comparisons of lengths: a chunk
// says itself how many words it completes, and that a body is complete with
// bytes left in its word register is found one cycle ahead.
module prism_numbergroup_committed_store #(
    parameter int unsigned MTU_BYTES = 1500
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          s_reset,
    input  logic [1:0]    s_bank_busy,
    input  logic [1:0]    s_frame_valid,
    output logic [1:0]    s_frame_ready,
    input  logic [895:0]  s_frame_header,
    input  logic [63:0]   s_frame_packet_id,
    input  logic [31:0]   s_frame_body_bytes,
    input  logic [1:0]    s_frame_last,
    input  logic          s_chunk_valid,
    output logic          s_chunk_ready,
    input  logic          s_chunk_bank,
    input  logic [15:0]   s_chunk_offset,
    input  logic [7:0]    s_chunk_bytes,
    // Words of the frame that the chunk completes: 0, 1 or 2.
    input  logic [1:0]    s_chunk_flush,
    input  logic [1535:0] s_chunk_window,
    input  logic          s_patch_valid,
    output logic          s_patch_ready,
    input  logic          s_patch_bank,
    input  logic [15:0]   s_patch_offset,
    input  logic [15:0]   s_patch_count,
    output logic [511:0]  m_axis_tdata,
    output logic [63:0]   m_axis_tkeep,
    output logic          m_axis_tvalid,
    output logic          m_axis_tlast,
    input  logic          m_axis_tready,
    output logic [15:0]   m_frame_bytes,
    output logic [31:0]   m_packet_id,
    output logic          m_last_frame_done,
    output logic          m_release_valid,
    output logic          m_release_bank,
    output logic          m_fault
);

  localparam int unsigned MAX_WORDS = (MTU_BYTES + 14 + 63) / 64;
  localparam int unsigned HALF_WORDS = (MAX_WORDS + 1) / 2;
  localparam int unsigned ADDR_W = $clog2(HALF_WORDS);
  localparam int unsigned WORD_W = $clog2(MAX_WORDS + 1);

  typedef enum logic [1:0] {PATCH_IDLE, PATCH_READ, PATCH_WRITE} patch_state_t;

  logic [511:0] memory [0:3][0:HALF_WORDS-1];
  logic [511:0] read_word [0:3];
  logic [511:0] write_data [0:3];
  logic [ADDR_W-1:0] read_address [0:3];
  logic [ADDR_W-1:0] write_address [0:3];
  logic [3:0] write_enable;
  // The write port of the memories, registered.
  logic [3:0] store_enable;
  logic [ADDR_W-1:0] store_address [0:3];
  logic [511:0] store_data [0:3];
  logic [WORD_W-1:0] visible_words [0:1];
  logic [1:0] finalize_due;
  logic landed_valid, landed_bank, patch_bypass;
  logic [1:0] planned, last;
  logic [447:0] header [0:1];
  logic [31:0] packet_id [0:1];
  logic [15:0] body_bytes [0:1];
  logic [15:0] written [0:1];
  logic [511:0] residual [0:1];
  logic [5:0] residual_bytes [0:1];
  logic [WORD_W-1:0] committed_words [0:1];
  logic [3:0] patch_pending [0:1];
  logic [31:0] first_descriptor [0:1];
  logic tx_bank;
  logic [WORD_W-1:0] tx_word;
  logic clear_valid, clear_bank;
  logic reset_context, store_reset_n;

  patch_state_t patch_state;
  logic patch_queue_ready, patch_valid, patch_bank, patch_start, patch_busy, patch_push;
  logic patch_in_residual, patch_residual_write, patch_memory_write, patch_blocks;
  logic patch_residual_reg;
  logic patch_first, patch_done, patch_done_bank;
  logic [15:0] patch_offset, patch_count;
  logic [2:0] patch_occupancy;
  logic patch_bank_reg;
  logic [15:0] patch_absolute_reg, patch_count_reg;
  logic [511:0] patch_word_reg, patch_data;
  logic [1:0] patch_memory;

  logic finalize_valid, finalize_bank, chunk_fire, chunk_shape_valid;
  logic [1535:0] append_window;
  logic [7:0] append_count;
  logic [1:0] flush_words;

  logic tx_valid, tx_ready, tx_last, tx_fire;
  logic [15:0] tx_frame_bytes, tx_remaining;
  logic [511:0] tx_data;
  logic [63:0] tx_keep;
  logic output_last_frame;

  assign reset_context = s_reset && s_bank_busy == 0 && !patch_valid && !patch_busy;
  assign store_reset_n = rst_n && !reset_context;

  // ---------------------------------------------------------------- patches
  prism_elastic_fifo #(
      .WIDTH(33), .DEPTH(4), .REGISTER_READY(1), .READY_ON_POP(0)
  ) u_patches (
      .clk(clk), .rst_n(store_reset_n),
      .s_data({s_patch_bank, s_patch_offset, s_patch_count}),
      .s_valid(s_patch_valid && !m_fault), .s_ready(patch_queue_ready),
      .m_data({patch_bank, patch_offset, patch_count}), .m_valid(patch_valid),
      .m_ready(patch_start), .occupancy(patch_occupancy)
  );
  assign s_patch_ready = patch_queue_ready && !m_fault;
  assign patch_push = s_patch_valid && s_patch_ready;
  assign patch_busy = patch_state != PATCH_IDLE;
  // A patch starts once its four descriptor bytes have been written. The
  // body only grows, so appending in the same cycle does not matter.
  assign patch_start = !patch_busy && !landed_valid && patch_valid && !m_fault
      && {1'b0, patch_offset} + 17'd4 <= {1'b0, written[patch_bank]};
  assign patch_memory = {patch_bank_reg, patch_absolute_reg[6]};
  // A patch takes two cycles and nothing is appended during them. In the
  // first its word is read and it is found out whether the word is in memory
  // (below committed_words) or still in the word register; the second writes
  // it there. The decision is a register, so the append handshake waits for
  // the state of the patch and not for that comparison.
  assign patch_in_residual
      = WORD_W'(patch_absolute_reg >> 6) >= committed_words[patch_bank_reg];
  assign patch_residual_write = patch_state == PATCH_WRITE && patch_residual_reg;
  assign patch_memory_write = patch_state == PATCH_WRITE && !patch_residual_reg;
  assign patch_blocks = patch_busy;
  assign patch_first = patch_start && patch_offset == 0;
  // A patch in the word register is done when it is written there; one in
  // a memory when its word has left the write register.
  assign patch_done = patch_first || patch_residual_write || landed_valid;
  assign patch_done_bank = patch_first ? patch_bank
      : landed_valid ? landed_bank : patch_bank_reg;
  assign patch_bypass = store_enable[patch_memory]
      && store_address[patch_memory] == ADDR_W'(patch_absolute_reg >> 7);
  always_comb begin
    patch_data = patch_word_reg;
    patch_data[(int'(patch_absolute_reg[5:0])+2)*8 +: 8] = patch_count_reg[15:8];
    patch_data[(int'(patch_absolute_reg[5:0])+3)*8 +: 8] = patch_count_reg[7:0];
  end

  // ---------------------------------------------------------------- append
  assign finalize_bank = !finalize_due[0];
  assign finalize_valid = !patch_blocks && !m_fault && finalize_due[finalize_bank];
  assign s_chunk_ready = !m_fault && !patch_blocks && !finalize_valid
      && s_bank_busy[s_chunk_bank];
  assign chunk_fire = s_chunk_valid && s_chunk_ready;
  assign chunk_shape_valid = s_chunk_bytes != 0 && s_chunk_bytes <= 128
      && s_chunk_offset == written[s_chunk_bank]
      && {1'b0, written[s_chunk_bank]} + 17'(s_chunk_bytes) <= 17'(MTU_BYTES - 42)
      && (!planned[s_chunk_bank]
          || {1'b0, written[s_chunk_bank]} + 17'(s_chunk_bytes)
              <= 17'(body_bytes[s_chunk_bank]));
  assign append_window = 1536'(residual[s_chunk_bank]) | s_chunk_window;
  assign append_count = 8'(residual_bytes[s_chunk_bank]) + s_chunk_bytes;
  assign flush_words = s_chunk_flush;
  assign s_frame_ready = ~planned;

  // --------------------------------------------------------------- memories
  // A memory has one write and one asynchronous read address. A frame with
  // a pending patch is not transmitted, so the patch and the transmitter
  // share the read.
  for (genvar m = 0; m < 4; m++) begin : ram_ports
    assign read_address[m] = patch_state == PATCH_READ && patch_memory == 2'(m)
        ? ADDR_W'(patch_absolute_reg >> 7) : ADDR_W'(tx_word >> 1);
    assign read_word[m] = memory[m][read_address[m]];
    always_ff @(posedge clk) begin
      if (store_enable[m]) memory[m][store_address[m]] <= store_data[m];
    end
    always_ff @(posedge clk) begin
      store_address[m] <= write_address[m];
      store_data[m] <= write_data[m];
    end
  end
  // A memory belongs to one frame and holds its even or its odd words. The
  // next word of a frame goes to the memory of its parity and, when a chunk
  // completes two words, the word after it to the other one. What is written
  // is chosen from registers alone; only the enable waits for the handshake.
  for (genvar m = 0; m < 4; m++) begin : write_port
    localparam int unsigned BANK = m / 2;
    localparam int unsigned PARITY = m % 2;
    logic patch_here, final_here, first_here;
    assign patch_here = patch_memory_write && patch_memory == 2'(m);
    assign final_here = finalize_due[BANK] && finalize_bank == 1'(BANK);
    // The first completed word carries the bytes of the word register.
    assign first_here = committed_words[BANK][0] == 1'(PARITY);
    assign write_data[m] = patch_here ? patch_data
        : final_here ? residual[BANK]
        : first_here ? (residual[BANK] | s_chunk_window[511:0]) : s_chunk_window[1023:512];
    assign write_address[m] = patch_here ? ADDR_W'(patch_absolute_reg >> 7)
        : first_here || final_here ? ADDR_W'(committed_words[BANK] >> 1)
        : ADDR_W'((committed_words[BANK] + WORD_W'(1)) >> 1);
    assign write_enable[m] = patch_here
        || (finalize_valid && final_here && first_here)
        || (chunk_fire && s_chunk_bank == 1'(BANK)
            && (first_here ? flush_words != 0 : flush_words == 2'd2));
  end

  // --------------------------------------------------------------- transmit
  assign tx_frame_bytes = 16'd56 + body_bytes[tx_bank];
  assign tx_remaining = tx_frame_bytes - (16'(tx_word) << 6);
  assign tx_valid = planned[tx_bank] && patch_pending[tx_bank] == 0
      && tx_word < visible_words[tx_bank];
  assign tx_last = tx_valid && tx_remaining <= 64;
  assign tx_keep = !tx_valid ? 64'b0
      : tx_remaining >= 64 ? '1 : (64'h1 << tx_remaining) - 64'd1;
  assign tx_fire = tx_valid && tx_ready;
  always_comb begin
    tx_data = read_word[{tx_bank, tx_word[0]}];
    if (tx_word == 0) tx_data[479:0] = {first_descriptor[tx_bank], header[tx_bank]};
  end
  // The frame buffer is free as soon as its last word has been read; the
  // word itself leaves through a register.
  assign m_release_valid = tx_fire && tx_last;
  assign m_release_bank = tx_bank;
  prism_elastic_register #(.WIDTH(512 + 64 + 2 + 16 + 32)) u_output (
      .clk(clk), .rst_n(store_reset_n),
      .s_data({tx_data, tx_keep, tx_last, last[tx_bank], tx_frame_bytes, packet_id[tx_bank]}),
      .s_valid(tx_valid), .s_ready(tx_ready),
      .m_data({m_axis_tdata, m_axis_tkeep, m_axis_tlast, output_last_frame, m_frame_bytes,
          m_packet_id}),
      .m_valid(m_axis_tvalid), .m_ready(m_axis_tready)
  );
  assign m_last_frame_done = m_axis_tvalid && m_axis_tready && m_axis_tlast
      && output_last_frame;

  // ------------------------------------------------------------------ state
  always_ff @(posedge clk) begin
    if (chunk_fire && s_chunk_offset == 0)
      first_descriptor[s_chunk_bank] <= s_chunk_window[56*8 +: 32];
    if (patch_first) first_descriptor[patch_bank][31:16] <= {patch_count[7:0], patch_count[15:8]};
    if (patch_start) begin
      patch_bank_reg <= patch_bank;
      patch_absolute_reg <= 16'd56 + patch_offset;
      patch_count_reg <= patch_count;
    end
    if (patch_state == PATCH_READ) begin
      patch_word_reg <= patch_bypass ? store_data[patch_memory] : read_word[patch_memory];
      patch_residual_reg <= patch_in_residual;
    end
    landed_bank <= patch_bank_reg;
    clear_bank <= tx_bank;
  end
  always_ff @(posedge clk) begin
    if (!store_reset_n) begin
      planned <= '0;
      last <= '0;
      tx_bank <= 1'b0;
      tx_word <= '0;
      clear_valid <= 1'b0;
      store_enable <= '0;
      landed_valid <= 1'b0;
      finalize_due <= '0;
      m_fault <= 1'b0;
      patch_state <= PATCH_IDLE;
      for (int b = 0; b < 2; b++) begin
        header[b] <= '0;
        packet_id[b] <= '0;
        body_bytes[b] <= '0;
        written[b] <= '0;
        residual[b] <= '0;
        residual_bytes[b] <= 6'd56;
        committed_words[b] <= '0;
        visible_words[b] <= '0;
        patch_pending[b] <= '0;
      end
    end else begin
      store_enable <= write_enable;
      landed_valid <= patch_memory_write;
      for (int b = 0; b < 2; b++) begin
        visible_words[b] <= committed_words[b];
        // A complete body with bytes left in its word register is flushed
        // in the cycle after this is seen, and once.
        finalize_due[b] <= planned[b] && written[b] == body_bytes[b]
            && residual_bytes[b] != 0 && !(finalize_valid && finalize_bank == 1'(b));
      end
      case (patch_state)
        PATCH_IDLE: if (patch_start && !patch_first) patch_state <= PATCH_READ;
        PATCH_READ: patch_state <= PATCH_WRITE;
        default: patch_state <= PATCH_IDLE;
      endcase
      for (int b = 0; b < 2; b++) begin
        case ({patch_push && s_patch_bank == 1'(b), patch_done && patch_done_bank == 1'(b)})
          2'b10: patch_pending[b] <= patch_pending[b] + 4'd1;
          2'b01: patch_pending[b] <= patch_pending[b] - 4'd1;
          default: begin end
        endcase
        if (s_frame_valid[b] && s_frame_ready[b]) begin
          if (!s_bank_busy[b] || s_frame_body_bytes[b*16 +: 16] == 0
              || s_frame_body_bytes[b*16 +: 16] > 16'(MTU_BYTES - 42)
              || written[b] > s_frame_body_bytes[b*16 +: 16]) begin
            m_fault <= 1'b1;
          end else begin
            planned[b] <= 1'b1;
            last[b] <= s_frame_last[b];
            header[b] <= s_frame_header[b*448 +: 448];
            packet_id[b] <= s_frame_packet_id[b*32 +: 32];
            body_bytes[b] <= s_frame_body_bytes[b*16 +: 16];
          end
        end
      end
      if (patch_push && (!s_bank_busy[s_patch_bank] || planned[s_patch_bank]
          || s_patch_offset[1:0] != 0 || s_patch_count == 0)) m_fault <= 1'b1;
      // A chunk that does not continue its body is a fault, and the fault
      // is final. The chunk is appended all the same, so that the check of
      // its shape is not part of every write enable.
      if (chunk_fire) begin
        if (!chunk_shape_valid) m_fault <= 1'b1;
        written[s_chunk_bank] <= written[s_chunk_bank] + 16'(s_chunk_bytes);
        committed_words[s_chunk_bank] <= committed_words[s_chunk_bank] + WORD_W'(flush_words);
        case (flush_words)
          0: residual[s_chunk_bank] <= append_window[511:0];
          1: residual[s_chunk_bank] <= append_window[1023:512];
          default: residual[s_chunk_bank] <= append_window[1535:1024];
        endcase
        residual_bytes[s_chunk_bank] <= 6'(append_count - 8'(flush_words) * 8'd64);
      end
      if (patch_residual_write) begin
        residual[patch_bank_reg][(int'(patch_absolute_reg[5:0])+2)*8 +: 8]
            <= patch_count_reg[15:8];
        residual[patch_bank_reg][(int'(patch_absolute_reg[5:0])+3)*8 +: 8]
            <= patch_count_reg[7:0];
      end
      if (finalize_valid) begin
        committed_words[finalize_bank] <= committed_words[finalize_bank] + WORD_W'(1);
        residual_bytes[finalize_bank] <= '0;
      end
      // The word register of a frame is emptied in the cycle after its last
      // word has been read. The next frame of that bank has to be planned
      // and encoded first, so its first chunk is still cycles away.
      clear_valid <= tx_fire && tx_last;
      if (clear_valid) residual[clear_bank] <= '0;
      if (tx_fire) begin
        if (tx_last) begin
          planned[tx_bank] <= 1'b0;
          written[tx_bank] <= '0;
          committed_words[tx_bank] <= '0;
          residual_bytes[tx_bank] <= 6'd56;
          tx_bank <= !tx_bank;
          tx_word <= '0;
        end else begin
          tx_word <= tx_word + WORD_W'(1);
        end
      end
    end
  end

  // synthesis translate_off
  // An accepted chunk lies exactly behind the bytes of the word so far and
  // holds nothing beyond its own length.
  logic [1535:0] verification_low, verification_high;
  assign verification_low = s_chunk_window
      & ((1536'd1 << (int'(residual_bytes[s_chunk_bank])*8)) - 1536'd1);
  assign verification_high = s_chunk_window >> (int'(append_count)*8);
  always_ff @(posedge clk) begin
    if (store_reset_n && chunk_fire && chunk_shape_valid) begin
      assert (verification_low == '0);
      assert (verification_high == '0);
      assert (residual_bytes[s_chunk_bank] == 6'(s_chunk_offset + 16'd56));
      assert (s_chunk_flush == (append_count >= 128 ? 2'd2 : append_count >= 64 ? 2'd1 : 2'd0))
          else $error("chunk flush %0d with %0d bytes behind %0d at offset %0d", s_chunk_flush,
              s_chunk_bytes, residual_bytes[s_chunk_bank], s_chunk_offset);
    end
    if (store_reset_n) begin
      // The transmitter never reads a word that is still in the write register.
      for (int m = 0; m < 4; m++)
        assert (!(store_enable[m] && tx_valid && tx_bank == 1'(m / 2) && tx_word[0] == 1'(m % 2)
            && store_address[m] == ADDR_W'(tx_word >> 1)));
    end
    if (store_reset_n && clear_valid) begin
      assert (!(chunk_fire && s_chunk_bank == clear_bank));
      assert (!(finalize_valid && finalize_bank == clear_bank));
    end
  end
  // synthesis translate_on

endmodule
