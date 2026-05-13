
// SPDX-License-Identifier: CERN-OHL-P-2.0
// Copyright (c) 2026 Lorenzo Cipolletti
//
// Questo file fa parte del progetto Mini-Sharp.
// Vedere LICENSE e NOTICE nel root della repository per i dettagli.

`timescale 1ns / 1ps

import mini_sharp_pkg::*;

// Modulo: mini_sharp_switch_core
//
// Descrizione:
//   Core RTL di primo livello per il prototipo Mini-Sharp. Il modulo riceve un
//   frame Ethernet su interfaccia AXI4-Stream, ricostruisce il frame completo,
//   esegue il parsing Ethernet/Mini-Sharp e decide se inoltrare il frame in
//   bypass o inviarlo al collective_engine.
//
// Nota sulla FSM:
//   La FSM è implementata come macchina sincrona a singolo processo. Le uscite
//   principali sono registrate; in_tready è derivato combinazionalmente dallo
//   stato corrente. È quindi una FSM Moore-like con transizioni dipendenti dagli
//   handshake AXI4-Stream.
//
// Stati:
//   STATE_RX
//     Ricostruisce un frame completo a partire dai beat AXI4-Stream di ingresso.
//
//   STATE_PROCESS
//     Usa i parser combinazionali per decidere se il frame è una reduction
//     Mini-Sharp supportata o se deve essere inoltrato in bypass.
//
//   STATE_WAIT_ENGINE
//     Attende che il collective_engine termini la gestione del frame.
//
//   STATE_TX_PREPARE
//     Prepara il beat AXI4-Stream di uscita corrente.
//
//   STATE_TX_SEND
//     Mantiene out_tvalid alto finché il sink accetta il beat.
module mini_sharp_switch_core #(
    parameter int AXIS_WIDTH        = 512,
    parameter int MAX_PACKET_BYTES  = 2048,
    parameter int PAYLOAD_MAX_BYTES = 1024,
    parameter int NUM_CONTEXTS      = 16,
    parameter int MAX_CONTRIBUTIONS = 64,

    parameter logic [47:0] SWITCH_MAC = 48'h02_00_00_00_00_AA,
    parameter bit DEBUG = 0
) (
    input  logic                      clk,
    input  logic                      rst_n,

    input  logic [AXIS_WIDTH-1:0]     in_tdata,
    input  logic [(AXIS_WIDTH/8)-1:0] in_tstrb,
    input  logic [47:0]               in_tuser,
    output logic                      in_tready,
    input  logic                      in_tvalid,
    input  logic                      in_tlast,

    output logic [AXIS_WIDTH-1:0]     out_tdata,
    output logic [(AXIS_WIDTH/8)-1:0] out_tstrb,
    output logic [47:0]               out_tuser,
    input  logic                      out_tready,
    output logic                      out_tvalid,
    output logic                      out_tlast
);

  localparam int AXIS_BYTES = AXIS_WIDTH / 8;

  // =========================================================================
  // FSM (dichiarazione e documentazione)
  // =========================================================================
  // FSM tipo:
  //   Macchina sincrona single-process, Moore-like, con transizioni dipendenti
  //   dagli handshake AXI4-Stream. Le uscite principali sono registrate,
  //   mentre `in_tready` è derivato combinazionalmente dallo stato corrente.
  //
  // Stati:
  //   STATE_RX: ricostruisce frame dagli beat AXI; transita a STATE_PROCESS
  //             quando riceve un beat con in_tlast=1.
  //   STATE_PROCESS: esegue parsing e decide se inviare a collective_engine
  //                  o preparare il TX in bypass.
  //   STATE_WAIT_ENGINE: attende `done_valid` dall'engine e riceve frame di
  //                      uscita via `engine_out_valid`.
  //   STATE_TX_PREPARE: prepara il beat di uscita corrente (TDATA/TSTRB/TUSER).
  //   STATE_TX_SEND: manda i beat verso il sink rispettando `out_tready`.
  // =========================================================================
  // =========================================================================
  // STATE ENCODING
  // =========================================================================
  typedef enum logic [2:0] {
    STATE_RX          = 3'd0,
    STATE_PROCESS     = 3'd1,
    STATE_WAIT_ENGINE = 3'd2,
    STATE_TX_PREPARE  = 3'd3,
    STATE_TX_SEND     = 3'd4
  } state_e;

  state_e state;
  state_e next_state;

  logic [(MAX_PACKET_BYTES*8)-1:0] rx_frame;
  logic [15:0]                     rx_len;

  logic [(MAX_PACKET_BYTES*8)-1:0] tx_frame;
  logic [15:0]                     tx_len;
  logic [15:0]                     tx_offset;

  integer i;

  logic [47:0] eth_dst_mac;
  logic [47:0] eth_src_mac;
  logic [15:0] ethertype;
  logic        valid_eth_frame;
  logic        is_reduction_ethertype;

  // =========================================================================
  // INTERNAL REGISTERS
  // =========================================================================

  eth_parser #(
      .MAX_PACKET_BYTES(MAX_PACKET_BYTES)
  ) u_eth_parser (
      .frame(rx_frame),
      .frame_len(rx_len),
      .dst_mac(eth_dst_mac),
      .src_mac(eth_src_mac),
      .ethertype(ethertype),
      .is_reduction_ethertype(is_reduction_ethertype),
      .valid_eth_frame(valid_eth_frame)
  );

  logic        valid_minisharp;
  logic [31:0] chunk_id;
  logic [31:0] p_size;
  logic [7:0]  op_flags;
  logic [15:0] flow_id;
  logic [7:0]  collective_op;
  logic [7:0]  data_type;
  logic [7:0]  collective_flags;
  logic [7:0]  reserved;
  logic [15:0] expected_contributions;
  logic [15:0] contribution_index;
  logic        is_reduce_sum_int8;

  logic        is_supported_reduction;

  assign is_supported_reduction =
    valid_minisharp &&
    (collective_op == COLLECTIVE_REDUCE) &&
    (op_flags == REDUCE_OP_SUM) &&
    ((data_type == DTYPE_INT8) || (data_type == DTYPE_FP32));

  minisharp_parser #(
      .MAX_PACKET_BYTES(MAX_PACKET_BYTES)
  ) u_minisharp_parser (
      .frame(rx_frame),
      .frame_len(rx_len),
      .valid_minisharp(valid_minisharp),
      .chunk_id(chunk_id),
      .p_size(p_size),
      .op_flags(op_flags),
      .flow_id(flow_id),
      .collective_op(collective_op),
      .data_type(data_type),
      .collective_flags(collective_flags),
      .reserved(reserved),
      .expected_contributions(expected_contributions),
      .contribution_index(contribution_index),
      .is_reduce_sum_int8(is_reduce_sum_int8)
  );

  // =========================================================================
  // OUTPUT / INTERFACE SIGNALS
  // =========================================================================
  // Segnali di interfaccia verso `collective_engine` e verso il lato TX.
  logic engine_in_valid;
  logic engine_done_valid;
  logic engine_out_valid;

  logic [(MAX_PACKET_BYTES*8)-1:0] engine_out_frame;
  logic [15:0]                     engine_out_len;

  collective_engine #(
      .MAX_PACKET_BYTES(MAX_PACKET_BYTES),
      .PAYLOAD_MAX_BYTES(PAYLOAD_MAX_BYTES),
      .NUM_CONTEXTS(NUM_CONTEXTS),
      .MAX_CONTRIBUTIONS(MAX_CONTRIBUTIONS),
      .SWITCH_MAC(SWITCH_MAC),
      .REWRITE_SRC_MAC(1),
      .DEBUG(DEBUG)
  ) u_collective_engine (
      .clk(clk),
      .rst_n(rst_n),

      .in_valid(engine_in_valid),
      .in_frame(rx_frame),
      .in_frame_len(rx_len),

      .in_chunk_id(chunk_id),
      .in_p_size(p_size),
      .in_operation_flags(op_flags),
      .in_flow_id(flow_id),
      .in_collective_op(collective_op),
      .in_data_type(data_type),
      .in_collective_flags(collective_flags),
      .in_expected_contributions(expected_contributions),
      .in_contribution_index(contribution_index),

      .done_valid(engine_done_valid),
      .out_valid(engine_out_valid),
      .out_frame(engine_out_frame),
      .out_frame_len(engine_out_len)
  );
  // =========================================================================
  // OUTPUT LOGIC (combinational)
  // =========================================================================
  // `in_tready` è un segnale combinazionale derivato dallo stato corrente:
  //   - true quando la FSM è nello stato `STATE_RX` e il reset è rilasciato.
  assign in_tready = rst_n && (state == STATE_RX);

  // =========================================================================
  // NEXT-STATE / CONTROL LOGIC (combinational)
  // =========================================================================
  // Calcola `next_state` in modo puramente combinazionale. Non aggiornare
  // registri qui; l'aggiornamento avviene nel blocco sequenziale sottostante.
  always_comb begin
    next_state = state;
    unique case (state)
      STATE_RX: begin
        if (in_tvalid && in_tready && in_tlast) begin
          next_state = STATE_PROCESS;
        end
      end

      STATE_PROCESS: begin
        if (valid_eth_frame && is_reduction_ethertype && valid_minisharp && is_supported_reduction) begin
          next_state = STATE_WAIT_ENGINE;
        end else begin
          next_state = STATE_TX_PREPARE;
        end
      end

      STATE_WAIT_ENGINE: begin
        if (engine_done_valid) begin
          if (engine_out_valid) begin
            next_state = STATE_TX_PREPARE;
          end else begin
            next_state = STATE_RX;
          end
        end
      end

      STATE_TX_PREPARE: begin
        next_state = STATE_TX_SEND;
      end

      STATE_TX_SEND: begin
        if (out_tvalid && out_tready) begin
          if (out_tlast) begin
            next_state = STATE_RX;
          end else begin
            next_state = STATE_TX_PREPARE;
          end
        end
      end

      default: begin
        next_state = STATE_RX;
      end
    endcase
  end

  function automatic logic [15:0] count_strb;
    input logic [AXIS_BYTES-1:0] strb;
    integer k;
    begin
      count_strb = 16'd0;
      for (k = 0; k < AXIS_BYTES; k++) begin
        count_strb = count_strb + {15'd0, strb[k]};
      end
    end
  endfunction

  // =========================================================================
  // REGISTER UPDATE / OUTPUT LOGIC (single-process)
  // =========================================================================
  // Nota: questa FSM è implementata come single-process per minimizzare le
  // modifiche al datapath esistente. Le uscite AXI (`out_tdata`, `out_tstrb`,
  // `out_tvalid`, `out_tlast`) sono registrate all'interno di questo blocco.
  always_ff @(negedge rst_n or posedge clk) begin
    if (!rst_n) begin
      state           <= STATE_RX;

      rx_frame        <= '0;
      rx_len          <= 16'd0;

      tx_frame        <= '0;
      tx_len          <= 16'd0;
      tx_offset       <= 16'd0;

      out_tdata       <= '0;
      out_tstrb       <= '0;
      out_tuser       <= '0;
      out_tvalid      <= 1'b0;
      out_tlast       <= 1'b0;

      engine_in_valid <= 1'b0;
    end else begin
      engine_in_valid <= 1'b0;

      unique case (state)

        STATE_RX: begin
          out_tvalid <= 1'b0;
          out_tlast  <= 1'b0;
          out_tstrb  <= '0;

          if (in_tvalid && in_tready) begin
            for (i = 0; i < AXIS_BYTES; i++) begin
              if (in_tstrb[i]) begin
                if ((rx_len + i) < MAX_PACKET_BYTES) begin
                  rx_frame[8*(rx_len + i) +: 8] <= in_tdata[8*i +: 8];
                end
              end
            end

            rx_len <= rx_len + count_strb(in_tstrb);

            if (in_tlast) begin
              // next_state handled by combinational next_state logic
            end
          end
        end

        STATE_PROCESS: begin
          if (DEBUG) begin
            $display(
              "SWITCH PROCESS: time=%0t rx_len=%0d ethertype=0x%04h valid_eth=%0b is_red_eth=%0b valid_ms=%0b is_sum_int8=%0b chunk=%0d p_size=%0d op_flags=%0d coll_op=%0d dtype=%0d expected=%0d contrib=%0d",
              $time,
              rx_len,
              ethertype,
              valid_eth_frame,
              is_reduction_ethertype,
              valid_minisharp,
              is_reduce_sum_int8,
              chunk_id,
              p_size,
              op_flags,
              collective_op,
              data_type,
              expected_contributions,
              contribution_index
            );
          end

          if (valid_eth_frame &&
              is_reduction_ethertype &&
              valid_minisharp &&
              is_supported_reduction) begin
            engine_in_valid <= 1'b1;
            // next_state handled by combinational next_state logic
          end else begin
            tx_frame  <= rx_frame;
            tx_len    <= rx_len;
            tx_offset <= 16'd0;
            // next_state handled by combinational next_state logic
          end
        end

        STATE_WAIT_ENGINE: begin
          if (engine_done_valid) begin
            if (DEBUG) begin
              $display(
                "SWITCH ENGINE DONE: time=%0t engine_out_valid=%0b engine_out_len=%0d",
                $time,
                engine_out_valid,
                engine_out_len
              );
            end

            if (engine_out_valid) begin
              tx_frame  <= engine_out_frame;
              tx_len    <= engine_out_len;
              tx_offset <= 16'd0;
              // next_state handled by combinational next_state logic
            end else begin
              rx_frame <= '0;
              rx_len   <= 16'd0;
              // next_state handled by combinational next_state logic
            end
          end
        end

        STATE_TX_PREPARE: begin
          if (DEBUG) begin
            $display(
              "SWITCH TX PREPARE: time=%0t tx_len=%0d tx_offset=%0d",
              $time,
              tx_len,
              tx_offset
            );
          end

          out_tdata <= '0;
          out_tstrb <= '0;
          out_tuser <= {32'd0, tx_len};

          for (i = 0; i < AXIS_BYTES; i++) begin
            if ((tx_offset + i) < tx_len) begin
              out_tdata[8*i +: 8] <= tx_frame[8*(tx_offset + i) +: 8];
              out_tstrb[i]        <= 1'b1;
            end
          end

          out_tvalid <= 1'b1;
          out_tlast  <= ((tx_len - tx_offset) <= AXIS_BYTES);

          // next_state handled by combinational next_state logic
        end

        STATE_TX_SEND: begin
          if (out_tvalid && out_tready) begin
            if (DEBUG) begin
              $display(
                "SWITCH TX HANDSHAKE: time=%0t last=%0b tx_len=%0d tx_offset=%0d",
                $time,
                out_tlast,
                tx_len,
                tx_offset
              );
            end

            if (out_tlast) begin
              out_tvalid  <= 1'b0;
              out_tlast   <= 1'b0;
              out_tstrb   <= '0;
              out_tdata   <= '0;

              tx_offset <= 16'd0;
              tx_len    <= 16'd0;
              tx_frame  <= '0;

              rx_frame  <= '0;
              rx_len    <= 16'd0;

              // next_state handled by combinational next_state logic
            end else begin
              // Si inserisce un ciclo con valid basso per evitare che il sink
              // campioni due volte lo stesso beat mentre viene preparato il successivo.
              out_tvalid  <= 1'b0;
              out_tlast   <= 1'b0;
              out_tstrb   <= '0;
              out_tdata   <= '0;

              tx_offset <= tx_offset + AXIS_BYTES;
              // next_state handled by combinational next_state logic
            end
          end
        end

        default: begin
          // next_state handled by combinational next_state logic
        end

      endcase
      // Update state register
      state <= next_state;
    end
  end

endmodule
