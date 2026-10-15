//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_cmac_bringup.sv
// Module: prism_cmac_bringup
// Description: Brings one 100G CMAC of the OpenNIC shell up without a host driver.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

// The CMAC subsystem of the OpenNIC shell leaves its MAC disabled after
// reset: RS-FEC, receiver and transmitter are enabled through registers,
// which the host driver writes over PCIe. A design without a host does the
// same writes from here, in the order of the driver:
//
//   1. reset the subsystem (the reset also clears its registers),
//   2. enable RS-FEC on both directions,
//   3. enable the receiver and send remote fault indication,
//   4. wait until the receiver reports alignment,
//   5. enable the transmitter.
//
// The driver enables the transmitter right after the remote fault
// indication; waiting for alignment in between is the order the MAC's
// product guide gives.
// Afterwards the receiver status is read at intervals. When alignment is
// lost the transmitter goes back to remote fault indication until the
// receiver is aligned again.
//
// Addresses are relative to the CMAC subsystem. The status bits are latched
// by the MAC until read, so every look at the status reads it twice and
// uses the second value.
module prism_cmac_bringup #(
    // Clock cycles between two looks at the receiver status.
    parameter int unsigned POLL_CYCLES = 125000,
    // RS-FEC on both directions. Both ends of a 100G link must agree on it;
    // without it the two RS-FEC writes are left out and RS-FEC stays at its
    // reset value, off.
    parameter bit RS_FEC = 1'b1
) (
    input  logic        clk,
    input  logic        rst_n,
    // Reset handshake of the CMAC subsystem: a low pulse of one cycle asks
    // for a reset, and the subsystem holds done high once it has finished.
    output logic        m_reset_n,
    input  logic        s_reset_done,
    output logic        m_awvalid,
    output logic [31:0] m_awaddr,
    input  logic        m_awready,
    output logic        m_wvalid,
    output logic [31:0] m_wdata,
    input  logic        m_wready,
    input  logic        m_bvalid,
    input  logic [1:0]  m_bresp,
    output logic        m_bready,
    output logic        m_arvalid,
    output logic [31:0] m_araddr,
    input  logic        m_arready,
    input  logic        m_rvalid,
    input  logic [31:0] m_rdata,
    input  logic [1:0]  m_rresp,
    output logic        m_rready,
    // The receiver is aligned and the transmitter is enabled.
    output logic        m_link_up
);

  localparam logic [31:0] TX_CONFIGURATION = 32'h0000_000C;
  localparam logic [31:0] RX_CONFIGURATION = 32'h0000_0014;
  localparam logic [31:0] RX_STATUS = 32'h0000_0204;
  localparam logic [31:0] FEC_MODE_REGISTER = 32'h0000_1000;
  localparam logic [31:0] FEC_ENABLE_REGISTER = 32'h0000_107C;
  localparam logic [31:0] TX_ENABLED = 32'h0000_0001;
  localparam logic [31:0] TX_REMOTE_FAULT = 32'h0000_0010;
  localparam int unsigned ALIGNED_BIT = 1;
  // Cycles the subsystem takes to drop done after a reset request.
  localparam int unsigned SETTLE_CYCLES = 8;
  localparam int unsigned TIMER_W = $clog2((POLL_CYCLES > SETTLE_CYCLES
      ? POLL_CYCLES : SETTLE_CYCLES) + 1);

  typedef enum logic [3:0] {
    RESET, FEC_ENABLE, FEC_MODE, RX_ENABLE, TX_FAULT, AWAIT_ALIGNED,
    TX_ENABLE, WATCH
  } step_t;
  typedef enum logic [2:0] {
    START, SETTLE, RELEASED, ADDRESS, RESPONSE, PAUSE, READ, DATA
  } phase_t;

  step_t step;
  phase_t phase;
  logic [TIMER_W-1:0] timer;
  logic second_read;
  logic unused_responses;
  assign unused_responses = ^{m_bresp, m_rresp, m_rdata};

  initial begin
    if (POLL_CYCLES < 1) $fatal(1, "The status of the CMAC needs a poll interval");
  end

  function automatic logic [31:0] address_of(input step_t at);
    case (at)
      FEC_ENABLE: return FEC_ENABLE_REGISTER;
      FEC_MODE: return FEC_MODE_REGISTER;
      RX_ENABLE: return RX_CONFIGURATION;
      default: return TX_CONFIGURATION;
    endcase
  endfunction

  function automatic logic [31:0] value_of(input step_t at);
    case (at)
      FEC_ENABLE: return 32'h0000_0003;
      FEC_MODE: return 32'h0000_0007;
      RX_ENABLE: return 32'h0000_0001;
      TX_FAULT: return TX_REMOTE_FAULT;
      default: return TX_ENABLED;
    endcase
  endfunction

  function automatic step_t after(input step_t at);
    case (at)
      RESET: return RS_FEC ? FEC_ENABLE : RX_ENABLE;
      FEC_ENABLE: return FEC_MODE;
      FEC_MODE: return RX_ENABLE;
      RX_ENABLE: return TX_FAULT;
      TX_FAULT: return AWAIT_ALIGNED;
      AWAIT_ALIGNED: return TX_ENABLE;
      default: return WATCH;
    endcase
  endfunction

  assign m_araddr = RX_STATUS;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      step <= RESET;
      phase <= START;
      timer <= '0;
      second_read <= 1'b0;
      m_reset_n <= 1'b1;
      m_awvalid <= 1'b0;
      m_wvalid <= 1'b0;
      m_bready <= 1'b0;
      m_arvalid <= 1'b0;
      m_rready <= 1'b0;
      m_link_up <= 1'b0;
    end else begin
      m_reset_n <= 1'b1;
      case (phase)
        START: begin
          case (step)
            RESET: begin
              m_reset_n <= 1'b0;
              timer <= TIMER_W'(SETTLE_CYCLES);
              phase <= SETTLE;
            end
            AWAIT_ALIGNED, WATCH: begin
              timer <= TIMER_W'(POLL_CYCLES);
              phase <= PAUSE;
            end
            default: begin
              m_awaddr <= address_of(step);
              m_wdata <= value_of(step);
              m_awvalid <= 1'b1;
              m_wvalid <= 1'b1;
              phase <= ADDRESS;
            end
          endcase
        end
        SETTLE: begin
          timer <= timer - 1'b1;
          if (timer == 0) phase <= RELEASED;
        end
        RELEASED: begin
          if (s_reset_done) begin
            step <= after(step);
            phase <= START;
          end
        end
        ADDRESS: begin
          if (m_awready) m_awvalid <= 1'b0;
          if (m_wready) m_wvalid <= 1'b0;
          if ((!m_awvalid || m_awready) && (!m_wvalid || m_wready)) begin
            m_bready <= 1'b1;
            phase <= RESPONSE;
          end
        end
        RESPONSE: begin
          if (m_bvalid) begin
            m_bready <= 1'b0;
            if (step == TX_ENABLE) m_link_up <= 1'b1;
            step <= after(step);
            phase <= START;
          end
        end
        PAUSE: begin
          timer <= timer - 1'b1;
          if (timer == 0) begin
            second_read <= 1'b0;
            m_arvalid <= 1'b1;
            phase <= READ;
          end
        end
        READ: begin
          if (m_arready) begin
            m_arvalid <= 1'b0;
            m_rready <= 1'b1;
            phase <= DATA;
          end
        end
        DATA: begin
          if (m_rvalid) begin
            m_rready <= 1'b0;
            if (!second_read) begin
              second_read <= 1'b1;
              m_arvalid <= 1'b1;
              phase <= READ;
            end else begin
              phase <= START;
              if (step == AWAIT_ALIGNED) begin
                if (m_rdata[ALIGNED_BIT]) step <= TX_ENABLE;
              end else if (!m_rdata[ALIGNED_BIT]) begin
                m_link_up <= 1'b0;
                step <= TX_FAULT;
              end
            end
          end
        end
        default: phase <= START;
      endcase
    end
  end

endmodule
