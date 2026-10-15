//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_native_ingress.sv
// Module: prism_single_native_ingress
// Description: Installed SINGLE context through bound DATA and parallel arithmetic.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_native_ingress #(
    parameter int unsigned CONTROL_PORT_INDEX = 1,
    parameter int unsigned FIRST_DATA_PORT = 2,
    parameter int unsigned DATA_PORTS = 2,
    parameter int unsigned KULISCH_W = 320,
    parameter int unsigned MAX_KULISCH_BITS = 4096,
    parameter int unsigned MAX_ORIGINAL_TERMS = 16,
    parameter int unsigned MAX_CHILDREN = 8,
    parameter int unsigned EXACT_BANKS = 8,
    parameter bit ENABLE_FP32_ACCUMULATION = 1'b1
) (
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic [511:0]                      s_control_tdata,
    input  logic [63:0]                       s_control_tkeep,
    input  logic                              s_control_tlast,
    input  logic                              s_control_tuser,
    input  logic                              s_control_tvalid,
    output logic                              s_control_tready,
    input  logic [511:0]                      s_data_tdata [0:DATA_PORTS-1],
    input  logic [63:0]                       s_data_tkeep [0:DATA_PORTS-1],
    input  logic [DATA_PORTS-1:0]             s_data_tlast,
    input  logic [DATA_PORTS-1:0]             s_data_tuser,
    input  logic [DATA_PORTS-1:0]             s_data_tvalid,
    output logic [DATA_PORTS-1:0]             s_data_tready,
    input  logic [47:0]                       s_local_mac,
    input  logic [47:0]                       s_manager_mac,
    input  logic [15:0]                       s_manager_port,
    input  logic [15:0]                       s_control_endpoint,
    input  logic [15:0]                       s_link_mtu,
    input  logic [15:0]                       s_usable_port_mask,
    input  logic                              s_shared_port_demux,
    input  prism_pkg::prism_operation_key_t   s_result_complete_operation,
    input  logic                              s_result_complete_valid,
    output logic [511:0]                      m_control_tdata,
    output logic [63:0]                       m_control_tkeep,
    output logic                              m_control_tlast,
    output logic                              m_control_tuser,
    output logic [15:0]                       m_control_frame_bytes,
    output logic                              m_control_tvalid,
    input  logic                              m_control_tready,
    output logic                              m_context_installed,
    output logic                              m_context_active,
    output logic                              m_context_complete,
    output prism_pkg::prism_operation_key_t   m_context_operation,
    output logic [1279:0]                     m_context_record,
    output logic [7:0]                        m_child_count,
    output logic                              m_inputs_drained,
    output logic                              m_arithmetic_error,
    output logic                              m_exact_arithmetic_fault,
    // The operation is being released: from the cycle after the release
    // until the datapath behind the receivers is empty and the banks are
    // cleared.
    output logic                              m_releasing,
    // A RESULT frame of the released operation is still leaving: the release
    // is not complete before its last beat.
    input  logic                              s_release_hold,
    output logic [DATA_PORTS*8-1:0]           m_receive_complete,
    output logic [DATA_PORTS-1:0]             m_data_event_valid,
    input  logic [DATA_PORTS-1:0]              m_data_event_ready,
    output logic [DATA_PORTS*3-1:0]           m_data_event_status,
    output logic [DATA_PORTS*32-1:0]          m_data_packet_ids,
    output logic [DATA_PORTS*3-1:0]           m_data_slots,
    output logic [DATA_PORTS*32-1:0]          m_data_watermarks,
    output logic [DATA_PORTS-1:0]             m_data_complete,
    output logic [DATA_PORTS-1:0]             m_data_binding_valid,
    input  logic [7:0]                        s_fast_result_read_slot,
    input  logic                              s_fast_result_read_valid,
    output logic                              s_fast_result_read_ready,
    output logic [31:0]                       m_fast_tile_first_element,
    output logic [15:0]                       m_fast_tile_keep,
    output logic [511:0]                      m_fast_tile_bits,
    output logic                              m_fast_tile_error,
    output logic                              m_fast_tile_valid,
    input  logic                              m_fast_tile_ready,
    output logic [31:0]                       m_rounded_auto_tile_first_element,
    output logic [127:0]                      m_rounded_auto_tile_keep,
    output logic [4095:0]                     m_rounded_auto_tile_bits,
    output logic                              m_rounded_auto_tile_error,
    output logic                              m_rounded_auto_tile_valid,
    input  logic                              m_rounded_auto_tile_ready,
    output logic [31:0]                       m_exact_tile_first_element,
    output logic [127:0]                      m_exact_tile_keep,
    output logic [1023:0]                     m_exact_tile_tags,
    output logic [128*KULISCH_W-1:0]                    m_exact_tile_integers,
    output logic                              m_exact_tile_error,
    output logic                              m_exact_tile_valid,
    input  logic                              m_exact_tile_ready,
    output logic                              m_result_store_fault
);

  import prism_pkg::*;

  // Keep the receiver structurally bounded by the admitted child capacity.
  localparam int unsigned RECEIVER_CHILDREN = (MAX_CHILDREN < 2) ? 2 : MAX_CHILDREN;

  logic [1279:0] context_word;
  logic [71:0] unused_context_prefix;
  logic [7:0] result_count, accumulator, partial_wire;
  logic [7:0] output_format, accepted_mask, rank_mask, collective_kind;
  logic [31:0] original_terms, maximum_terms, total_elements, window_bytes;
  logic [15:0] kulisch_bits, mtu, window_intervals;
  logic [127:0] local_endpoints, peer_endpoints, local_ports, rank_ids;
  logic [383:0] peer_macs;
  logic [63:0] native_masks;
  logic [7:0] result_enabled;
  logic stage_pulse, commit_pulse, release_pulse;
  // A release, also one that aborts an operation while its DATA arrives,
  // first empties the datapath: tiles that leave the receivers and results
  // that leave the banks are dropped, and no new frame is taken, until the
  // receivers, the tile buffers and the banks are idle. Then the banks are
  // cleared, which they do only when they are idle.
  typedef enum logic [1:0] {FLOW, DRAIN, CLEAR, SETTLE} release_state_t;
  release_state_t release_state;
  logic [1:0] release_count;
  logic draining, drain_next, bank_release, datapath_idle, result_read_valid;
  // A read of the exact banks is granted; the rounding has places for the
  // tiles that are on their way to it.
  logic exact_read_fire, round_request_ready;
  (* dont_touch = "true" *) logic [DATA_PORTS-1:0] drain_tiles;
  // The same flag for the receivers, which lie apart from the tile path.
  (* dont_touch = "true" *) logic [DATA_PORTS-1:0] drain_receivers;
  (* dont_touch = "true" *) logic drain_results;
  logic [DATA_PORTS-1:0] tile_valid, tile_ready;
  logic [DATA_PORTS-1:0] receiver_tile_valid, receiver_tile_ready;
  logic [DATA_PORTS-1:0] receiver_raw_valid, receiver_raw_ready;
  logic [DATA_PORTS-1:0] tile_serializer_ready, exact_dispatch_ready;
  logic [DATA_PORTS-1:0] arb_tile_valid, arb_tile_ready;
  logic [DATA_PORTS-1:0] dual_exact_ready;
  logic [DATA_PORTS-1:0] dual_rounded_ready;
  logic [DATA_PORTS-1:0] receiver_idle;
  logic [DATA_PORTS-1:0] receiver_arithmetic_error;
  logic all_covered;
  logic [31:0] tile_first [0:DATA_PORTS-1];
  logic [31:0] receiver_tile_first [0:DATA_PORTS-1];
  logic [31:0] receiver_raw_first [0:DATA_PORTS-1];
  logic [7:0] tile_format [0:DATA_PORTS-1];
  logic [7:0] receiver_tile_format [0:DATA_PORTS-1];
  logic [7:0] receiver_raw_format [0:DATA_PORTS-1];
  logic [7:0] tile_count [0:DATA_PORTS-1];
  logic [7:0] receiver_tile_count [0:DATA_PORTS-1];
  logic [7:0] receiver_raw_count [0:DATA_PORTS-1];
  logic [2:0] tile_contributor [0:DATA_PORTS-1];
  logic [2:0] receiver_tile_contributor [0:DATA_PORTS-1];
  logic [2:0] receiver_raw_contributor [0:DATA_PORTS-1];
  logic [511:0] tile_bits [0:DATA_PORTS-1];
  logic [511:0] receiver_tile_bits [0:DATA_PORTS-1];
  logic [511:0] receiver_raw_bits [0:DATA_PORTS-1];
  logic [63:0] tile_keep [0:DATA_PORTS-1];
  logic [63:0] receiver_tile_keep [0:DATA_PORTS-1];
  logic [63:0] receiver_raw_keep [0:DATA_PORTS-1];
  prism_tile_meta_t tile_meta [0:DATA_PORTS-1], selected_meta;
  logic [511:0] selected_bits;
  logic [15:0] selected_keep;
  logic selected_valid, selected_ready;
  logic fast_mode, fast_exact;
  logic wide_exact_result;
  logic exact_ready, exact_release_ready;
  logic exact_arithmetic_fault_event, exact_merge_fault_event;
  logic [31:0] rounded_result_first;
  logic [127:0] exact_result_present;
  logic [15:0] rounded_result_present;
  logic [1023:0] exact_result_tags;
  logic [128*KULISCH_W-1:0] exact_result_integers;
  logic [511:0] rounded_result_bits;
  logic [127:0] stored_result_present;
  logic [4095:0] stored_result_bits;
  logic [7:0] stored_result_slot;
  logic stored_result_error, stored_result_valid, stored_result_ready;
  logic rounded_results_complete, wide_rounded_auto;
  logic [7:0] exact_result_slot, rounded_result_slot;
  logic exact_result_valid, exact_result_read_ready;
  logic rounded_result_valid, rounded_result_ready, rounded_result_read_ready;
  logic rounded_result_error, fast_rounded_fault, rounded_backend_fault;
  logic rounded_ready, rounded_release_ready;
  logic fast_exact_fault;
  logic exact_round_ready, exact_round_valid, exact_round_error;
  logic [31:0] exact_round_first;
  logic [15:0] exact_round_keep;
  logic [511:0] exact_round_bits;
  logic unused_context;
  assign unused_context = ^{unused_context_prefix, result_count,
      original_terms, maximum_terms, window_bytes, window_intervals,
      accumulator, partial_wire, output_format, accepted_mask, rank_mask,
      collective_kind, rank_ids, result_enabled, stage_pulse, commit_pulse};

  initial begin
    if (MAX_CHILDREN < 1 || MAX_CHILDREN > 8
        || MAX_ORIGINAL_TERMS < MAX_CHILDREN
        || KULISCH_W < 278 + $clog2(MAX_ORIGINAL_TERMS)
        || KULISCH_W > 320 || (KULISCH_W & 1) != 0
        || (EXACT_BANKS != 4 && EXACT_BANKS != 8)
        || (ENABLE_FP32_ACCUMULATION && DATA_PORTS == 2 && EXACT_BANKS != 8))
      $fatal(1, "SINGLE arithmetic parameters exceed implemented bounds");
    if (DATA_PORTS < 1 || DATA_PORTS > 8 || FIRST_DATA_PORT + DATA_PORTS > 16)
      $fatal(1, "SINGLE native ingress requires bounded physical data ports");
  end

  localparam int unsigned EXACT_LANES = EXACT_BANKS * 16;

  // How results leave is decoded from the operation context, which is stable
  // long before the first result and until the last one. The decoded choices
  // are registered, so the context does not sit in any result handshake.
  logic exact_path;
  always_ff @(posedge clk) begin
    wide_exact_result <= DATA_PORTS <= 2 && fast_exact
        && (output_format == PRISM_FORMAT_KULISCH || output_format == 8'hff);
    wide_rounded_auto <= DATA_PORTS == 2 && !fast_exact
        && output_format == 8'hff;
    exact_path <= fast_mode && fast_exact
        && (output_format == PRISM_FORMAT_KULISCH || output_format == 8'hff);
  end

  assign {unused_context_prefix, m_child_count, result_count, original_terms,
      maximum_terms, total_elements, kulisch_bits, mtu, window_intervals,
      window_bytes, accumulator, partial_wire, output_format, accepted_mask,
      rank_mask, collective_kind, local_endpoints, peer_endpoints, local_ports,
      rank_ids, peer_macs, native_masks, result_enabled} = context_word;
  assign m_context_record = context_word;
  assign m_releasing = draining;
  // The STAGE parser bounds the vector and MTU before the context can activate.
  // Do not carry those static comparisons through every arithmetic ready path.
  // The flag is used through registers, one of them next to each data port,
  // so the lifecycle does not reach into the handshakes of the tiles. DATA
  // follows a COMMIT by many cycles, and a release drains what a late tile
  // leaves behind.
  (* dont_touch = "true" *) logic [DATA_PORTS-1:0] fast_mode_port;
  always_ff @(posedge clk) begin
    fast_mode <= m_context_active;
    fast_mode_port <= {DATA_PORTS{m_context_active}};
  end
  // STAGE installs the policy before COMMIT permits DATA. Keep its comparison
  // off the bank-ready and RAM-address paths by registering the local choice.
  if (ENABLE_FP32_ACCUMULATION) begin : gen_policy_select
    always_ff @(posedge clk) begin
      if (!rst_n) fast_exact <= 1'b0;
      else fast_exact <= accumulator == PRISM_ACC_KULISCH_FIXED;
    end
  end else begin : gen_exact_only
    assign fast_exact = 1'b1;
  end

  always_comb begin
    all_covered = m_child_count != 0;
    for (integer child = 0; child < 8; child++) begin
      logic found;
      found = 1'b0;
      for (integer port = 0; port < DATA_PORTS; port++)
        found |= m_receive_complete[port*8 + child];
      if (child < int'(m_child_count) && !found) all_covered = 1'b0;
    end
  end
  // The inputs stay drained once they are, until the operation is released,
  // so the flag is given through a register.
  assign drain_next = release_pulse || (release_state != FLOW
      && !(release_state == SETTLE && release_count == 2'd3));
  always_ff @(posedge clk) begin
    datapath_idle <= (&receiver_idle) && !(|receiver_tile_valid) && !(|tile_valid)
        && !selected_valid && exact_release_ready && rounded_release_ready
        && !s_release_hold;
  end
  // No result is read while the datapath is emptied.
  assign result_read_valid = s_fast_result_read_valid && !drain_results;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      release_state <= FLOW;
      release_count <= '0;
      draining <= 1'b0;
      drain_tiles <= '0;
      drain_receivers <= '0;
      drain_results <= 1'b0;
      bank_release <= 1'b0;
    end else begin
      draining <= drain_next;
      drain_tiles <= {DATA_PORTS{drain_next}};
      drain_receivers <= {DATA_PORTS{drain_next}};
      drain_results <= drain_next;
      bank_release <= 1'b0;
      case (release_state)
        FLOW: begin
          release_count <= '0;
          if (release_pulse) release_state <= DRAIN;
        end
        // The idle flag lags the datapath by a register, as the drain flags
        // do: the datapath counts as empty after four idle cycles in a row.
        DRAIN: begin
          if (!datapath_idle) release_count <= '0;
          else if (release_count == 2'd3) begin
            release_count <= '0;
            bank_release <= 1'b1;
            release_state <= CLEAR;
          end else release_count <= release_count + 2'd1;
        end
        CLEAR: release_state <= SETTLE;
        // The banks clear their presence bits two cycles after the pulse.
        default: begin
          release_count <= release_count + 2'd1;
          if (release_count == 2'd3) release_state <= FLOW;
        end
      endcase
    end
  end
  always_ff @(posedge clk) begin
    if (!rst_n || release_pulse || draining) m_inputs_drained <= 1'b0;
    else m_inputs_drained <= m_context_active && all_covered
        && (&receiver_idle) && !(|receiver_tile_valid) && !(|tile_valid)
        && (fast_exact ? exact_release_ready : rounded_release_ready)
        && (fast_exact || rounded_results_complete)
        && !m_result_store_fault;
  end
  assign m_arithmetic_error = (|receiver_arithmetic_error) || fast_rounded_fault;
  assign m_exact_arithmetic_fault = fast_exact_fault;

  prism_single_control_plane #(
      .PORT_INDEX(CONTROL_PORT_INDEX),
      .SUPPORTED_POLICY_BITS(ENABLE_FP32_ACCUMULATION ? 4'b1101 : 4'b1100),
      .MAX_ELEMENTS(4096), .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS), .MAX_CHILDREN(MAX_CHILDREN)
  ) u_control (
      .clk(clk), .rst_n(rst_n),
      .s_axis_tdata(s_control_tdata), .s_axis_tkeep(s_control_tkeep),
      .s_axis_tlast(s_control_tlast), .s_axis_tuser(s_control_tuser),
      .s_axis_tvalid(s_control_tvalid), .s_axis_tready(s_control_tready),
      .s_local_mac(s_local_mac), .s_manager_mac(s_manager_mac),
      .s_manager_port(s_manager_port),
      .s_control_endpoint(s_control_endpoint), .s_link_mtu(s_link_mtu),
      .s_usable_port_mask(s_usable_port_mask),
      .s_shared_port_demux(s_shared_port_demux),
      .s_complete_operation(s_result_complete_operation),
      .s_complete_valid(s_result_complete_valid),
      .m_context_installed(m_context_installed),
      .m_context_active(m_context_active),
      .m_context_complete(m_context_complete),
      .m_context_operation(m_context_operation), .m_context(context_word),
      .m_stage_pulse(stage_pulse), .m_commit_pulse(commit_pulse),
      .m_release_pulse(release_pulse),
      .m_axis_tdata(m_control_tdata), .m_axis_tkeep(m_control_tkeep),
      .m_axis_tlast(m_control_tlast), .m_axis_tuser(m_control_tuser),
      .m_frame_bytes(m_control_frame_bytes),
      .m_axis_tvalid(m_control_tvalid), .m_axis_tready(m_control_tready)
  );

  for (genvar port = 0; port < DATA_PORTS; port++) begin : gen_port
    logic [626:0] buffered_tile;
    logic [RECEIVER_CHILDREN-1:0] receive_complete;
    assign m_receive_complete[port*8 +: 8] = 8'(receive_complete);
    assign tile_meta[port] = '{default: '0, first_element: tile_first[port],
        input_format: tile_format[port], element_count: tile_count[port],
        contributor_id: 16'(tile_contributor[port])};
    prism_single_data_receiver #(
        .PORT_INDEX(FIRST_DATA_PORT + port),
        .MAX_CHILDREN(RECEIVER_CHILDREN), .CHILD_W(3)
    ) u_receiver (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(s_data_tdata[port]),
        .s_axis_tkeep(s_data_tkeep[port]),
        .s_axis_tlast(s_data_tlast[port]),
        .s_axis_tuser(s_data_tuser[port]),
        .s_axis_tvalid(s_data_tvalid[port]),
        .s_axis_tready(s_data_tready[port]),
        .s_active(m_context_active),
        .s_operation(m_context_operation),
        .s_total_elements(total_elements), .s_mtu(mtu),
        .s_kulisch_bits(kulisch_bits), .s_local_mac(s_local_mac),
        .s_child_count(m_child_count),
        .s_local_endpoints(local_endpoints[RECEIVER_CHILDREN*16-1:0]),
        .s_peer_endpoints(peer_endpoints[RECEIVER_CHILDREN*16-1:0]), .s_local_ports(local_ports[RECEIVER_CHILDREN*16-1:0]),
        .s_peer_macs(peer_macs[RECEIVER_CHILDREN*48-1:0]), .s_native_masks(native_masks[RECEIVER_CHILDREN*8-1:0]),
        .s_release(release_pulse), .s_hold(drain_receivers[port]),
        .m_receive_complete(receive_complete),
        .m_arithmetic_error(receiver_arithmetic_error[port]),
        .m_idle(receiver_idle[port]),
        .m_tile_first_element(receiver_raw_first[port]),
        .m_tile_format(receiver_raw_format[port]),
        .m_tile_count(receiver_raw_count[port]),
        .m_tile_contributor_slot(receiver_raw_contributor[port]),
        .m_tile_bits(receiver_raw_bits[port]),
        .m_tile_keep(receiver_raw_keep[port]),
        .m_tile_valid(receiver_raw_valid[port]),
        .m_tile_ready(receiver_raw_ready[port]),
        .m_frame_event_valid(m_data_event_valid[port]),
        .m_frame_event_ready(m_data_event_ready[port]),
        .m_frame_event_status(m_data_event_status[port*3 +: 3]),
        .m_frame_packet_id(m_data_packet_ids[port*32 +: 32]),
        .m_frame_binding_valid(m_data_binding_valid[port]),
        .m_frame_contributor_slot(m_data_slots[port*3 +: 3]),
        .m_frame_cumulative_element(m_data_watermarks[port*32 +: 32]),
        .m_frame_complete(m_data_complete[port])
    );
    // Decouple the receiver's tile-builder credits from the arithmetic banks.
    // The two-entry buffer still accepts one tile on every cycle in steady state.
    prism_elastic_skid_buffer #(
        .WIDTH(627)
    ) u_receiver_tile_buffer (
        .clk(clk), .rst_n(rst_n),
        .s_data({receiver_raw_bits[port], receiver_raw_first[port],
            receiver_raw_format[port], receiver_raw_count[port],
            receiver_raw_contributor[port], receiver_raw_keep[port]}),
        .s_valid(receiver_raw_valid[port]), .s_ready(receiver_raw_ready[port]),
        .m_data(buffered_tile), .m_valid(receiver_tile_valid[port]),
        .m_ready(receiver_tile_ready[port])
    );
    assign {receiver_tile_bits[port], receiver_tile_first[port],
        receiver_tile_format[port], receiver_tile_count[port],
        receiver_tile_contributor[port], receiver_tile_keep[port]} = buffered_tile;
    prism_native_tile_serializer #(.CHILD_W(3)) u_tile_serializer (
        .clk(clk), .rst_n(rst_n),
        .s_first_element(receiver_tile_first[port]),
        .s_format(receiver_tile_format[port]),
        .s_contributor_slot(receiver_tile_contributor[port]),
        .s_bits(receiver_tile_bits[port]),
        .s_keep(receiver_tile_keep[port]),
        .s_valid(receiver_tile_valid[port] && !drain_tiles[port]
            && !(DATA_PORTS <= 2 && fast_mode_port[port] && fast_exact)),
        .s_ready(tile_serializer_ready[port]),
        .m_first_element(tile_first[port]),
        .m_format(tile_format[port]), .m_count(tile_count[port]),
        .m_contributor_slot(tile_contributor[port]),
        .m_bits(tile_bits[port]), .m_keep(tile_keep[port][15:0]),
        .m_valid(tile_valid[port]), .m_ready(tile_ready[port])
    );
    assign receiver_tile_ready[port] = drain_tiles[port]
        || (DATA_PORTS <= 2 && fast_mode_port[port] && fast_exact
            ? exact_dispatch_ready[port] : tile_serializer_ready[port]);
    assign tile_keep[port][63:16] = '0;
    wire unused_port = ^tile_keep[port][63:16];
    assign arb_tile_valid[port] = tile_valid[port] && !drain_tiles[port]
        && fast_exact && DATA_PORTS != 2;
    assign tile_ready[port] = drain_tiles[port]
        || (fast_mode_port[port] && !fast_exact
            ? dual_rounded_ready[port]
            : DATA_PORTS <= 2 && fast_mode_port[port] && fast_exact
                ? dual_exact_ready[port] : arb_tile_ready[port]);
  end

  logic [15:0] selected_source_keep [0:DATA_PORTS-1];
  prism_tile_arbiter #(.PORTS(DATA_PORTS)) u_tile_arbiter (
      .clk(clk), .rst_n(rst_n), .s_meta(tile_meta),
      .s_element_bits(tile_bits), .s_element_keep(selected_source_keep),
      .s_valid(arb_tile_valid), .s_ready(arb_tile_ready),
      .m_meta(selected_meta), .m_element_bits(selected_bits),
      .m_element_keep(selected_keep),
      .m_valid(selected_valid), .m_ready(selected_ready)
  );

  for (genvar port = 0; port < DATA_PORTS; port++) begin : gen_keep
    assign selected_source_keep[port] = tile_keep[port][15:0];
  end

  assign selected_ready = draining || exact_ready;

  if (DATA_PORTS <= 2) begin : gen_striped_exact
    logic [DATA_PORTS-1:0] read_ready, bank_release_ready, result_valid;
    logic [DATA_PORTS-1:0] arithmetic_fault;
    logic [7:0] result_slot [0:DATA_PORTS-1];
    logic [EXACT_LANES-1:0] result_present [0:DATA_PORTS-1];
    logic [EXACT_LANES*8-1:0] result_tags [0:DATA_PORTS-1];
    logic [EXACT_LANES*KULISCH_W-1:0] result_integers [0:DATA_PORTS-1];
    logic merge_ready, merge_error;

    for (genvar port = 0; port < DATA_PORTS; port++) begin : gen_bank
      prism_striped_exact_tile_port #(
          .KULISCH_W(KULISCH_W), .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS),
          .BANKS(EXACT_BANKS), .RESULT_LANES(EXACT_LANES)
      ) u_bank (
          .clk(clk), .rst_n(rst_n),
          .s_first_element(receiver_tile_first[port]),
          .s_format(receiver_tile_format[port]),
          .s_bits(receiver_tile_bits[port]),
          .s_keep(receiver_tile_keep[port]),
          .s_valid(receiver_tile_valid[port] && fast_mode_port[port] && fast_exact
              && !drain_tiles[port]),
          .s_ready(exact_dispatch_ready[port]), .s_flush(drain_tiles[port]),
          .s_release(bank_release), .s_release_ready(bank_release_ready[port]),
          .s_result_slot(s_fast_result_read_slot),
          .s_wide_result(wide_exact_result),
          .s_result_read_valid(exact_read_fire),
          .s_result_read_ready(read_ready[port]),
          .m_result_slot(result_slot[port]),
          .m_result_present(result_present[port]),
          .m_result_tags(result_tags[port]),
          .m_result_integers(result_integers[port]),
          .m_result_valid(result_valid[port]),
          .m_arithmetic_fault(arithmetic_fault[port])
      );
      assign dual_exact_ready[port] = exact_dispatch_ready[port];
    end

    logic [EXACT_LANES-1:0] merged_present;
    logic [EXACT_LANES*8-1:0] merged_tags;
    logic [EXACT_LANES*KULISCH_W-1:0] merged_integers;
    assign exact_result_present = 128'(merged_present);
    assign exact_result_tags = 1024'(merged_tags);
    assign exact_result_integers = (128*KULISCH_W)'(merged_integers);

    if (DATA_PORTS == 2) begin : gen_merge
      prism_exact_tile_merge2 #(.KULISCH_W(KULISCH_W), .LANES(EXACT_LANES)) u_merge (
          .clk(clk), .rst_n(rst_n),
          .s_slot(result_slot[0]),
          .s_present0(result_present[0]),
          .s_tags0(result_tags[0]),
          .s_integers0(result_integers[0]),
          .s_present1(result_present[1]),
          .s_tags1(result_tags[1]),
          .s_integers1(result_integers[1]),
          .s_valid(&result_valid), .s_ready(merge_ready),
          .m_slot(exact_result_slot),
          .m_present(merged_present),
          .m_tags(merged_tags),
          .m_integers(merged_integers),
          .m_error(merge_error),
          .m_valid(exact_result_valid), .m_ready(1'b1)
      );

      // Both ports are read together: their banks are empty before the first
      // request, and every request is granted to both in the same cycle.
      always_ff @(posedge clk) begin
        if (rst_n && (&result_valid) && result_slot[0] != result_slot[1])
          $fatal(1, "Exact result banks returned mismatched slots");
        if (rst_n && result_valid[0] != result_valid[1])
          $fatal(1, "Exact result banks of the two ports returned their results apart");
        if (rst_n && (&result_valid) && !merge_ready)
          $fatal(1, "Exact result merge was not ready for a result");
      end
    end else begin : gen_direct_readout
      // Two ranks sharing one port already accumulate in the same banks.
      assign exact_result_slot = result_slot[0];
      assign merged_present = result_present[0];
      assign merged_tags = result_tags[0];
      assign merged_integers = result_integers[0];
      assign exact_result_valid = result_valid[0];
      assign merge_ready = 1'b1;
      assign merge_error = 1'b0;
    end

    assign exact_ready = 1'b1;
    assign exact_release_ready = &bank_release_ready;
    assign exact_result_read_ready = &read_ready;
    assign exact_arithmetic_fault_event = |arithmetic_fault;
    assign exact_merge_fault_event = exact_result_valid && merge_error;

  end else begin : gen_single_exact
    logic value_valid;
    logic [31:0] value_errors;
    logic [15:0] narrow_present;
    logic [127:0] narrow_tags;
    logic [16*KULISCH_W-1:0] narrow_integers;
    assign dual_exact_ready = '0;
    assign exact_dispatch_ready = '0;
    assign exact_arithmetic_fault_event = value_valid && (|value_errors);
    assign exact_merge_fault_event = 1'b0;

    prism_exact_native_tile_pipeline #(
        .RANGES(256), .KULISCH_W(KULISCH_W), .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS)
    ) u_bank (
        .clk(clk), .rst_n(rst_n),
        .s_slot(selected_meta.first_element[11:4]),
        .s_first_element(selected_meta.first_element),
        .s_format(selected_meta.input_format),
        .s_element_bits(selected_bits), .s_element_keep(selected_keep),
        .s_valid(selected_valid && fast_mode && fast_exact && !draining),
        .s_ready(exact_ready), .s_release(bank_release),
        .s_release_ready(exact_release_ready),
        .s_result_slot(s_fast_result_read_slot),
        .s_result_read_arm(result_read_valid && fast_mode && fast_exact),
        .s_result_read_valid(exact_read_fire),
        .s_result_read_ready(exact_result_read_ready),
        .m_result_slot(exact_result_slot),
        .m_result_present(narrow_present),
        .m_result_tags(narrow_tags),
        .m_result_integers(narrow_integers),
        .m_result_valid(exact_result_valid),
        .m_first_element(), .m_element_keep(),
        .m_kulisch_tags(), .m_kulisch_integers(),
        .m_errors(value_errors),
        .m_valid(value_valid), .m_ready(1'b1)
    );
    assign exact_result_present = {{112{1'b0}}, narrow_present};
    assign exact_result_tags = {{896{1'b0}}, narrow_tags};
    assign exact_result_integers = {{112*KULISCH_W{1'b0}}, narrow_integers};
  end

  if (ENABLE_FP32_ACCUMULATION) begin : gen_arrival_round
    localparam int unsigned STORE_STRIPES = DATA_PORTS == 2 ? 8 : 1;
    logic [DATA_PORTS-1:0] arrival_valid;
    logic result_store_write_ready;
    logic [STORE_STRIPES*16-1:0] local_result_present;
    logic [STORE_STRIPES*512-1:0] local_result_bits;

    assign rounded_ready = 1'b1;
    assign arrival_valid = tile_valid & ~drain_tiles
        & {DATA_PORTS{fast_mode && !fast_exact}};
    prism_fp32_arrival_backend #(.PORTS(DATA_PORTS)) u_arrival (
        .clk(clk), .rst_n(rst_n), .s_release(release_pulse),
        .s_total_elements(total_elements), .s_children(m_child_count[3:0]),
        .s_first(tile_first), .s_format(tile_format),
        .s_bits(tile_bits), .s_keep(selected_source_keep),
        .s_valid(arrival_valid), .s_ready(dual_rounded_ready),
        .m_slot(rounded_result_slot), .m_present(rounded_result_present),
        .m_bits(rounded_result_bits), .m_error(rounded_result_error),
        .m_valid(rounded_result_valid), .m_ready(rounded_result_ready),
        .m_idle(rounded_release_ready), .m_fault(rounded_backend_fault)
    );

    prism_fp32_rounded_result_store #(.STRIPES(STORE_STRIPES))
    u_result_store (
        .clk(clk), .rst_n(rst_n), .s_release(release_pulse),
        .s_total_elements(total_elements),
        .s_slot(rounded_result_slot),
        .s_present(rounded_result_present), .s_bits(rounded_result_bits),
        .s_error(rounded_result_error),
        .s_valid(rounded_result_valid), .s_ready(result_store_write_ready),
        .m_all_written(rounded_results_complete),
        .s_result_slot(s_fast_result_read_slot),
        .s_wide_read(wide_rounded_auto),
        .s_result_read_valid(result_read_valid && fast_mode && !fast_exact),
        .s_result_read_ready(rounded_result_read_ready),
        .m_result_slot(stored_result_slot),
        .m_result_present(local_result_present),
        .m_result_bits(local_result_bits),
        .m_result_error(stored_result_error),
        .m_result_valid(stored_result_valid),
        .m_result_ready(stored_result_ready)
    );
    assign rounded_result_ready = result_store_write_ready;
    assign stored_result_present =
        {{(128-STORE_STRIPES*16){1'b0}}, local_result_present};
    assign stored_result_bits =
        {{(4096-STORE_STRIPES*512){1'b0}}, local_result_bits};

  end else begin : gen_no_arrival_round
    assign rounded_backend_fault = 1'b0;
    assign dual_rounded_ready = '0;
    assign rounded_ready = 1'b1;
    assign rounded_release_ready = 1'b1;
    assign rounded_results_complete = 1'b1;
    assign rounded_result_slot = '0;
    assign rounded_result_present = '0;
    assign rounded_result_bits = '0;
    assign rounded_result_error = 1'b0;
    assign rounded_result_valid = 1'b0;
    assign rounded_result_ready = 1'b0;
    assign rounded_result_read_ready = 1'b0;
    assign stored_result_slot = '0;
    assign stored_result_present = '0;
    assign stored_result_bits = '0;
    assign stored_result_error = 1'b0;
    assign stored_result_valid = 1'b0;
  end

  // Whether exact results leave through the final rounding. The operation
  // context is stable long before the first result and until the last one,
  // so a registered copy next to the rounding tile serves its handshakes and
  // keeps the lifecycle registers out of its enables.
  logic round_path;
  always_ff @(posedge clk) begin
    round_path <= fast_mode && fast_exact && output_format != PRISM_FORMAT_KULISCH
        && output_format != 8'hff;
  end

  prism_exact_final_round_tile #(.KULISCH_W(KULISCH_W)) u_fast_round (
      .clk(clk), .rst_n(rst_n),
      .s_first_element(32'(exact_result_slot) << 4),
      .s_element_keep(exact_result_present[15:0]),
      .s_kulisch_tags(exact_result_tags[127:0]),
      .s_kulisch_integers(exact_result_integers[16*KULISCH_W-1:0]),
      .s_output_format(output_format),
      .s_valid(exact_result_valid && round_path && !drain_results),
      .s_ready(exact_round_ready), .m_request_ready(round_request_ready),
      .s_enable(round_path), .s_fault(fast_exact_fault), .s_flush(drain_results),
      .m_first_element(exact_round_first),
      .m_element_keep(exact_round_keep),
      .m_element_bits(exact_round_bits),
      .m_error(exact_round_error),
      .m_valid(exact_round_valid),
      .m_ready(m_fast_tile_ready)
  );

  // The banks return a result for one cycle. The exact egress has reserved
  // its storage before it asks, and a read for the rounding is granted only
  // while the rounding has places for the tiles already on their way.
  assign exact_read_fire = s_fast_result_read_valid && s_fast_result_read_ready
      && fast_exact;
  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (rst_n && exact_result_valid && round_path && !drain_results && !exact_round_ready)
      $fatal(1, "A bank result for the rounding found no place");
  end
  // synthesis translate_on
  wire unused_exact_tile_ready = m_exact_tile_ready;
  assign stored_result_ready = fast_mode && !fast_exact
      && (wide_rounded_auto ? m_rounded_auto_tile_ready : m_fast_tile_ready);
  assign s_fast_result_read_ready = fast_mode && !drain_results
      && (fast_exact ? exact_result_read_ready && (!round_path || round_request_ready)
          : rounded_result_read_ready);
  assign rounded_result_first = 32'(stored_result_slot) << 4;
  assign m_fast_tile_first_element = fast_exact
      ? exact_round_first : rounded_result_first;
  assign m_fast_tile_keep = fast_exact
      ? exact_round_keep : stored_result_present[15:0];
  assign m_fast_tile_bits = fast_exact
      ? exact_round_bits : stored_result_bits[511:0];
  // The rounding tile qualifies its own output with the path and the fault
  // of the operation.
  assign m_fast_tile_error = fast_exact
      ? exact_round_error : (stored_result_error || fast_rounded_fault);
  assign m_fast_tile_valid = fast_exact ? exact_round_valid
      : fast_mode && !wide_rounded_auto && stored_result_valid;
  assign m_rounded_auto_tile_first_element = 32'(stored_result_slot) << 7;
  assign m_rounded_auto_tile_keep = stored_result_present;
  assign m_rounded_auto_tile_bits = stored_result_bits;
  assign m_rounded_auto_tile_error = stored_result_error || fast_rounded_fault;
  assign m_rounded_auto_tile_valid = fast_mode && wide_rounded_auto
      && stored_result_valid;
  assign m_exact_tile_first_element = 32'(exact_result_slot) << 4;
  assign m_exact_tile_keep = exact_result_present;
  assign m_exact_tile_tags = exact_result_tags;
  assign m_exact_tile_integers = exact_result_integers;
  assign m_exact_tile_error = fast_exact_fault;
  assign m_exact_tile_valid = exact_path && exact_result_valid && !drain_results;
  assign m_result_store_fault = fast_exact_fault || fast_rounded_fault;

  always_ff @(posedge clk) begin
    if (!rst_n || release_pulse || draining) fast_exact_fault <= 1'b0;
    else if (exact_arithmetic_fault_event || exact_merge_fault_event)
      fast_exact_fault <= 1'b1;
  end

  if (ENABLE_FP32_ACCUMULATION) begin : gen_rounded_fault
    always_ff @(posedge clk) begin
      if (!rst_n || release_pulse || draining) fast_rounded_fault <= 1'b0;
      else if (rounded_backend_fault || (rounded_result_valid && rounded_result_ready
          && rounded_result_error)) fast_rounded_fault <= 1'b1;
    end
  end else begin : gen_no_rounded_fault
    assign fast_rounded_fault = 1'b0;
  end

endmodule
