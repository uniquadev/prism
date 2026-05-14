
// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

module collective_engine #(
    parameter int MAX_PACKET_BYTES  = 2048,
    parameter int PAYLOAD_MAX_BYTES = 1024,
    parameter int NUM_CONTEXTS      = 16,
    parameter int MAX_CONTRIBUTIONS = 64,

    parameter logic [47:0] SWITCH_MAC = 48'h02_00_00_00_00_AA,
    parameter bit REWRITE_SRC_MAC = 1,
    parameter bit DEBUG = 0
) (
    input  logic                            clk,
    input  logic                            rst_n,

    input  logic                            in_valid,
    input  logic [(MAX_PACKET_BYTES*8)-1:0] in_frame,
    input  logic [15:0]                     in_frame_len,

    input  logic [31:0]                     in_chunk_id,
    input  logic [31:0]                     in_p_size,
    input  logic [7:0]                      in_operation_flags,
    input  logic [15:0]                     in_flow_id,
    input  logic [7:0]                      in_collective_op,
    input  logic [7:0]                      in_data_type,
    input  logic [7:0]                      in_collective_flags,
    input  logic [15:0]                     in_expected_contributions,
    input  logic [15:0]                     in_contribution_index,

    output logic                            done_valid,
    output logic                            out_valid,
    output logic [(MAX_PACKET_BYTES*8)-1:0] out_frame,
    output logic [15:0]                     out_frame_len
);

  // =========================================================================
  // STATE ENCODING
  // =========================================================================

  typedef enum logic [2:0] {
    STATE_IDLE       = 3'd0,
    STATE_LANE_READ  = 3'd1,
    STATE_LANE_EXEC  = 3'd2,
    STATE_LANE_WRITE = 3'd3,
    STATE_EMIT       = 3'd4
  } state_e;

  state_e state;

  // =========================================================================
  // CONTEXT TABLE
  // =========================================================================

  logic                    ctx_valid        [NUM_CONTEXTS];
  logic [31:0]             ctx_chunk_id     [NUM_CONTEXTS];
  logic [15:0]             ctx_flow_id      [NUM_CONTEXTS];
  logic [7:0]              ctx_op_flags     [NUM_CONTEXTS];
  logic [31:0]             ctx_p_size       [NUM_CONTEXTS];
  logic [15:0]             ctx_expected     [NUM_CONTEXTS];
  logic [15:0]             ctx_received     [NUM_CONTEXTS];
  logic [MAX_CONTRIBUTIONS-1:0] ctx_seen [NUM_CONTEXTS];

  logic [(MAX_PACKET_BYTES*8)-1:0] ctx_template_frame [NUM_CONTEXTS];

  // Accumulatore interno FP32.
  // INT8 usa offset consecutivi; FP32 usa offset 0,4,8,...
  logic [31:0] acc_fp32 [NUM_CONTEXTS][PAYLOAD_MAX_BYTES];

  // =========================================================================
  // PENDING FRAME / LANE PIPELINE REGISTERS
  // =========================================================================

  logic [(MAX_PACKET_BYTES*8)-1:0] pending_frame;
  logic [(MAX_PACKET_BYTES*8)-1:0] work_out_frame;

  logic [15:0] pending_frame_len;
  logic [31:0] pending_chunk_id;
  logic [31:0] pending_p_size;
  logic [7:0]  pending_op_flags;
  logic [15:0] pending_flow_id;
  logic [7:0]  pending_collective_op;
  logic [7:0]  pending_data_type;
  logic [7:0]  pending_collective_flags;
  logic [15:0] pending_expected;
  logic [15:0] pending_contribution_index;

  logic        pending_is_new_context;
  logic        pending_emit;
  logic [15:0] pending_received_after;
  int          pending_ctx_idx;

  logic [31:0] lane_offset;

  logic found;
  logic allocated;
  logic is_new_context;
  int   ctx_idx;

  logic [15:0] received_before;
  logic [15:0] received_after;

  fp32_alu_op_e decoded_alu_op;
  logic         accumulation_supported;
  logic         needs_finalization;

  logic [31:0] converter_sample_fp32;
  logic [2:0]  converter_lane_bytes;
  logic        input_dtype_supported;

  logic [31:0] encoded_bytes;
  logic [2:0]  output_lane_bytes;
  logic        output_dtype_supported;

  logic [31:0] current_acc_fp32;
  logic [31:0] alu_result_fp32;

  logic [31:0] pipe_acc_fp32;
  logic [31:0] pipe_sample_fp32;
  logic [31:0] pipe_result_fp32;
  logic [31:0] pipe_lane_offset;
  logic [2:0]  pipe_lane_bytes;
  fp32_alu_op_e pipe_alu_op;

  integer i;
  integer b;

  // =========================================================================
  // COMBINATIONAL SUBMODULES
  // =========================================================================

  reduction_op_decoder u_reduction_op_decoder (
      .op_flags(pending_op_flags),
      .alu_op(decoded_alu_op),
      .accumulation_supported(accumulation_supported),
      .needs_finalization(needs_finalization)
  );

  reduction_input_converter #(
      .MAX_PACKET_BYTES(MAX_PACKET_BYTES)
  ) u_reduction_input_converter (
      .frame(pending_frame),
      .byte_offset(lane_offset),
      .data_type(pending_data_type),
      .sample_fp32(converter_sample_fp32),
      .lane_bytes(converter_lane_bytes),
      .data_type_supported(input_dtype_supported)
  );

  fp32_alu u_fp32_alu (
      .alu_op(pipe_alu_op),
      .lhs_fp32(pipe_acc_fp32),
      .rhs_fp32(pipe_sample_fp32),
      .result_fp32(alu_result_fp32)
  );

  reduction_output_converter u_reduction_output_converter (
      .value_fp32(pipe_result_fp32),
      .data_type(pending_data_type),
      .encoded_bytes(encoded_bytes),
      .lane_bytes(output_lane_bytes),
      .data_type_supported(output_dtype_supported)
  );

  // =========================================================================
  // COMBINATIONAL HELPERS
  // =========================================================================

  always_comb begin
    current_acc_fp32 = 32'd0;

    if (!pending_is_new_context &&
        pending_ctx_idx >= 0 &&
        pending_ctx_idx < NUM_CONTEXTS &&
        lane_offset < PAYLOAD_MAX_BYTES) begin
      current_acc_fp32 = acc_fp32[pending_ctx_idx][lane_offset];
    end
  end

  function automatic logic contribution_index_supported;
    input logic [15:0] contribution_index;
    begin
      contribution_index_supported = contribution_index < MAX_CONTRIBUTIONS;
    end
  endfunction

  function automatic logic payload_size_supported;
    input logic [31:0] p_size;
    begin
      payload_size_supported = p_size <= PAYLOAD_MAX_BYTES;
    end
  endfunction

  function automatic logic payload_alignment_supported;
    input logic [31:0] p_size;
    input logic [7:0]  data_type;
    begin
      unique case (data_type)
        DTYPE_INT8: payload_alignment_supported = 1'b1;
        DTYPE_FP32: payload_alignment_supported = (p_size[1:0] == 2'b00);
        default:    payload_alignment_supported = 1'b0;
      endcase
    end
  endfunction

  // =========================================================================
  // REGISTER UPDATE / FSM
  // =========================================================================

  always_ff @(negedge rst_n or posedge clk) begin
    if (!rst_n) begin
      state         <= STATE_IDLE;
      done_valid    <= 1'b0;
      out_valid     <= 1'b0;
      out_frame     <= '0;
      out_frame_len <= 16'd0;

      pending_frame              <= '0;
      work_out_frame             <= '0;
      pending_frame_len          <= 16'd0;
      pending_chunk_id           <= 32'd0;
      pending_p_size             <= 32'd0;
      pending_op_flags           <= 8'd0;
      pending_flow_id            <= 16'd0;
      pending_collective_op      <= 8'd0;
      pending_data_type          <= 8'd0;
      pending_collective_flags   <= 8'd0;
      pending_expected           <= 16'd0;
      pending_contribution_index <= 16'd0;
      pending_is_new_context     <= 1'b0;
      pending_emit               <= 1'b0;
      pending_received_after     <= 16'd0;
      pending_ctx_idx            <= -1;
      lane_offset                <= 32'd0;

      pipe_acc_fp32     <= 32'd0;
      pipe_sample_fp32  <= 32'd0;
      pipe_result_fp32  <= 32'd0;
      pipe_lane_offset  <= 32'd0;
      pipe_lane_bytes   <= 3'd0;
      pipe_alu_op       <= FP32_ALU_PASS;

      for (i = 0; i < NUM_CONTEXTS; i++) begin
        ctx_valid[i]          <= 1'b0;
        ctx_chunk_id[i]       <= 32'd0;
        ctx_flow_id[i]        <= 16'd0;
        ctx_op_flags[i]       <= 8'd0;
        ctx_p_size[i]         <= 32'd0;
        ctx_expected[i]       <= 16'd0;
        ctx_received[i]       <= 16'd0;
        ctx_seen[i]           <= '0;
        ctx_template_frame[i] <= '0;

        for (b = 0; b < PAYLOAD_MAX_BYTES; b++) begin
          acc_fp32[i][b] <= 32'd0;
        end
      end
    end else begin
      done_valid <= 1'b0;
      out_valid  <= 1'b0;

      unique case (state)

        STATE_IDLE: begin
          if (in_valid) begin
            found          = 1'b0;
            allocated      = 1'b0;
            is_new_context = 1'b0;
            ctx_idx        = -1;

            if (DEBUG) begin
              $display(
                "ENGINE IN: time=%0t chunk=%0d p_size=%0d op_flags=%0d flow_id=%0d coll_op=%0d dtype=%0d expected=%0d contrib=%0d",
                $time,
                in_chunk_id,
                in_p_size,
                in_operation_flags,
                in_flow_id,
                in_collective_op,
                in_data_type,
                in_expected_contributions,
                in_contribution_index
              );
            end

            if (in_collective_op != COLLECTIVE_REDUCE) begin
              if (DEBUG) begin
                $display("COLLECTIVE_ENGINE: unsupported collective_op=%0d", in_collective_op);
              end
              done_valid <= 1'b1;
            end else if (!payload_size_supported(in_p_size)) begin
              if (DEBUG) begin
                $display("COLLECTIVE_ENGINE: unsupported p_size=%0d max=%0d",
                         in_p_size, PAYLOAD_MAX_BYTES);
              end
              done_valid <= 1'b1;
            end else if (!payload_alignment_supported(in_p_size, in_data_type)) begin
              if (DEBUG) begin
                $display("COLLECTIVE_ENGINE: unsupported payload alignment p_size=%0d dtype=%0d",
                         in_p_size, in_data_type);
              end
              done_valid <= 1'b1;
            end else if (!contribution_index_supported(in_contribution_index)) begin
              if (DEBUG) begin
                $display("COLLECTIVE_ENGINE: unsupported contribution_index=%0d max=%0d",
                         in_contribution_index, MAX_CONTRIBUTIONS);
              end
              done_valid <= 1'b1;
            end else begin
              for (i = 0; i < NUM_CONTEXTS; i++) begin
                if (ctx_valid[i] &&
                    ctx_chunk_id[i] == in_chunk_id &&
                    ctx_flow_id[i] == in_flow_id) begin
                  found   = 1'b1;
                  ctx_idx = i;
                end
              end

              if (!found) begin
                for (i = 0; i < NUM_CONTEXTS; i++) begin
                  if (!ctx_valid[i] && !allocated) begin
                    allocated      = 1'b1;
                    is_new_context = 1'b1;
                    ctx_idx        = i;

                    ctx_valid[i]          <= 1'b1;
                    ctx_chunk_id[i]       <= in_chunk_id;
                    ctx_flow_id[i]        <= in_flow_id;
                    ctx_op_flags[i]       <= in_operation_flags;
                    ctx_p_size[i]         <= in_p_size;
                    ctx_expected[i]       <= in_expected_contributions;
                    ctx_seen[i]           <= '0;
                    ctx_template_frame[i] <= in_frame;
                  end
                end
              end

              if (ctx_idx < 0) begin
                if (DEBUG) begin
                  $display("COLLECTIVE_ENGINE: no free context chunk_id=%0d flow_id=%0d",
                           in_chunk_id, in_flow_id);
                end
                done_valid <= 1'b1;
              end else if (!is_new_context && ctx_seen[ctx_idx][in_contribution_index]) begin
                if (DEBUG) begin
                  $display("COLLECTIVE_ENGINE: duplicate contribution chunk=%0d contrib=%0d ignored",
                           in_chunk_id, in_contribution_index);
                end
                done_valid <= 1'b1;
              end else begin
                received_before = is_new_context ? 16'd0 : ctx_received[ctx_idx];
                received_after  = received_before + 16'd1;

                pending_frame              <= in_frame;
                pending_frame_len          <= in_frame_len;
                pending_chunk_id           <= in_chunk_id;
                pending_p_size             <= in_p_size;
                pending_op_flags           <= in_operation_flags;
                pending_flow_id            <= in_flow_id;
                pending_collective_op      <= in_collective_op;
                pending_data_type          <= in_data_type;
                pending_collective_flags   <= in_collective_flags;
                pending_expected           <= in_expected_contributions;
                pending_contribution_index <= in_contribution_index;
                pending_is_new_context     <= is_new_context;
                pending_emit               <= (received_after >= in_expected_contributions);
                pending_received_after     <= received_after;
                pending_ctx_idx            <= ctx_idx;
                lane_offset                <= 32'd0;

                work_out_frame <= is_new_context ? in_frame : ctx_template_frame[ctx_idx];

                state <= STATE_LANE_READ;
              end
            end
          end
        end

        STATE_LANE_READ: begin
          if (!input_dtype_supported || !accumulation_supported || needs_finalization) begin
            if (DEBUG) begin
              $display(
                "COLLECTIVE_ENGINE: unsupported reduction path op_flags=%0d dtype=%0d",
                pending_op_flags,
                pending_data_type
              );
            end
            done_valid <= 1'b1;
            state      <= STATE_IDLE;
          end else begin
            pipe_acc_fp32    <= current_acc_fp32;
            pipe_sample_fp32 <= converter_sample_fp32;
            pipe_lane_offset <= lane_offset;
            pipe_lane_bytes  <= converter_lane_bytes;
            pipe_alu_op      <= decoded_alu_op;

            state <= STATE_LANE_EXEC;
          end
        end

        STATE_LANE_EXEC: begin
          pipe_result_fp32 <= alu_result_fp32;
          state            <= STATE_LANE_WRITE;
        end

        STATE_LANE_WRITE: begin
          acc_fp32[pending_ctx_idx][pipe_lane_offset] <= pipe_result_fp32;

          if (pending_emit) begin
            for (b = 0; b < 4; b++) begin
              if (b < pipe_lane_bytes) begin
                work_out_frame[
                  8*(MINISHARP_PAYLOAD_OFFSET + pipe_lane_offset + b) +: 8
                ] <= encoded_bytes[8*b +: 8];
              end
            end
          end

          if ((pipe_lane_offset + pipe_lane_bytes) >= pending_p_size) begin
            ctx_seen[pending_ctx_idx][pending_contribution_index] <= 1'b1;
            ctx_received[pending_ctx_idx] <= pending_received_after;

            if (pending_emit) begin
              state <= STATE_EMIT;
            end else begin
              done_valid <= 1'b1;
              state      <= STATE_IDLE;
            end
          end else begin
            lane_offset <= pipe_lane_offset + pipe_lane_bytes;
            state       <= STATE_LANE_READ;
          end
        end

        STATE_EMIT: begin
          if (DEBUG) begin
            $display(
              "ENGINE OUTPUT: time=%0t ctx=%0d chunk=%0d flow_id=%0d op_flags=%0d p_size=%0d dtype=%0d",
              $time,
              pending_ctx_idx,
              pending_chunk_id,
              pending_flow_id,
              pending_op_flags,
              pending_p_size,
              pending_data_type
            );
          end

          done_valid    <= 1'b1;
          out_valid     <= 1'b1;
          out_frame     <= work_out_frame;
          out_frame_len <= MINISHARP_PAYLOAD_OFFSET + pending_p_size[15:0];

          if (REWRITE_SRC_MAC) begin
            out_frame[8*(ETH_SRC_OFFSET + 0) +: 8] <= SWITCH_MAC[47:40];
            out_frame[8*(ETH_SRC_OFFSET + 1) +: 8] <= SWITCH_MAC[39:32];
            out_frame[8*(ETH_SRC_OFFSET + 2) +: 8] <= SWITCH_MAC[31:24];
            out_frame[8*(ETH_SRC_OFFSET + 3) +: 8] <= SWITCH_MAC[23:16];
            out_frame[8*(ETH_SRC_OFFSET + 4) +: 8] <= SWITCH_MAC[15:8];
            out_frame[8*(ETH_SRC_OFFSET + 5) +: 8] <= SWITCH_MAC[7:0];
          end

          // Mini-Sharp emitted header fields are little-endian.
          out_frame[8*(FLOW_ID_OFFSET + 0) +: 8] <= pending_flow_id[7:0];
          out_frame[8*(FLOW_ID_OFFSET + 1) +: 8] <= pending_flow_id[15:8];

          out_frame[8*(EXPECTED_CONTRIB_OFFSET + 0) +: 8] <= 8'h01;
          out_frame[8*(EXPECTED_CONTRIB_OFFSET + 1) +: 8] <= 8'h00;

          out_frame[8*(CONTRIBUTION_INDEX_OFFSET + 0) +: 8] <= 8'h00;
          out_frame[8*(CONTRIBUTION_INDEX_OFFSET + 1) +: 8] <= 8'h00;

          ctx_valid[pending_ctx_idx]    <= 1'b0;
          ctx_received[pending_ctx_idx] <= 16'd0;
          ctx_seen[pending_ctx_idx]     <= '0;

          state <= STATE_IDLE;
        end

        default: begin
          state <= STATE_IDLE;
        end

      endcase
    end
  end

endmodule
