//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_native_core.sv
// Module: prism_single_native_core
// Description: SINGLE rank ingress through RESULT transmission.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_native_core #(
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
    output logic [511:0]                      m_control_tdata,
    output logic [63:0]                       m_control_tkeep,
    output logic                              m_control_tlast,
    output logic                              m_control_tuser,
    output logic [15:0]                       m_control_frame_bytes,
    output logic                              m_control_tvalid,
    input  logic                              m_control_tready,
    output logic [15:0]                       m_result_port,
    output logic [511:0]                      m_result_tdata,
    output logic [63:0]                       m_result_tkeep,
    output logic                              m_result_tlast,
    output logic [15:0]                       m_result_frame_bytes,
    output logic                              m_result_tvalid,
    input  logic                              m_result_tready,
    output logic                              m_context_installed,
    output logic                              m_context_active,
    output logic                              m_context_complete,
    output logic [7:0]                        m_result_sent_mask,
    output logic                              m_result_all_sent,
    output logic                              m_fault
);

  import prism_pkg::*;
  localparam int unsigned RESULT_LANES = DATA_PORTS <= 2 ? EXACT_BANKS*16 : 16;

  prism_operation_key_t context_operation;
  logic [1279:0] context_word;
  logic [71:0] unused_prefix;
  logic [7:0] child_count, result_count, output_format, result_enabled;
  logic [7:0] accumulator, partial_wire, accepted_mask, rank_mask;
  logic [7:0] collective_kind;
  logic [31:0] original_terms, maximum_terms, total_elements, window_bytes;
  logic [15:0] kulisch_bits, mtu, window_intervals;
  logic [127:0] local_endpoints, peer_endpoints, local_ports, rank_ids;
  logic [383:0] peer_macs;
  logic [63:0] native_masks;
  logic [DATA_PORTS*8-1:0] receive_complete;
  logic [7:0] unused_child_count;
  logic [DATA_PORTS-1:0] data_event_valid;
  logic [DATA_PORTS*3-1:0] data_event_status;
  logic [DATA_PORTS*32-1:0] data_packet_ids, data_watermarks;
  logic [DATA_PORTS*3-1:0] data_slots;
  logic [DATA_PORTS-1:0] data_complete, data_binding_valid;
  logic [DATA_PORTS-1:0] data_event_ready;
  logic inputs_drained, releasing, egress_start_ready, egress_started;
  logic completion_pending, start_request;
  logic arithmetic_error, exact_arithmetic_fault;
  logic error_output, select_exact_egress, output_exact;
  logic start_due, start_exact, start_error;
  logic rounded_auto_output, rounded_auto_wide;
  logic complete_signaled;
  logic egress_fault, store_fault;
  logic exact_egress_fault;
  logic exact_start_ready;
  logic [7:0] fast_read_slot;
  logic fast_read_valid, fast_read_ready;
  logic [7:0] native_read_slot, exact_read_slot;
  logic native_read_valid, native_read_ready;
  logic exact_read_valid, exact_read_ready;
  logic [31:0] fast_tile_first;
  logic [15:0] fast_tile_keep;
  logic [511:0] fast_tile_bits;
  logic fast_tile_error, fast_tile_valid, fast_tile_ready;
  logic [31:0] buffered_tile_first;
  logic [15:0] buffered_tile_keep;
  logic [511:0] buffered_tile_bits;
  logic buffered_tile_error, buffered_tile_valid, buffered_tile_ready;
  logic [31:0] rounded_auto_tile_first;
  logic [127:0] rounded_auto_tile_keep;
  logic [4095:0] rounded_auto_tile_bits;
  logic rounded_auto_tile_error, rounded_auto_tile_valid;
  logic rounded_auto_tile_ready;
  logic native_egress_tile_ready, exact_egress_tile_ready;
  logic [31:0] exact_tile_first;
  logic [127:0] exact_tile_keep;
  logic [1023:0] exact_tile_tags;
  logic [128*KULISCH_W-1:0] exact_tile_integers;
  logic exact_tile_error, exact_tile_valid, exact_tile_ready;
  logic [15:0] native_result_port, exact_result_port;
  logic [511:0] native_result_data, exact_result_data;
  logic [63:0] native_result_keep, exact_result_keep;
  logic native_result_last, exact_result_last;
  logic [15:0] native_result_bytes, exact_result_bytes;
  logic native_result_valid, exact_result_valid;
  logic [7:0] native_sent_mask, exact_sent_mask;
  logic native_all_sent, exact_all_sent;
  logic exact_output;
  wire unused_context = ^{unused_prefix, original_terms, maximum_terms,
      window_bytes, accumulator, partial_wire, accepted_mask, rank_mask,
      collective_kind, kulisch_bits, mtu, window_intervals, rank_ids,
      native_masks, receive_complete, unused_child_count,
      data_event_status,
      data_packet_ids, data_watermarks, data_slots, data_complete,
      data_binding_valid};

  assign {unused_prefix, child_count, result_count, original_terms,
      maximum_terms, total_elements, kulisch_bits, mtu, window_intervals,
      window_bytes, accumulator, partial_wire, output_format, accepted_mask,
      rank_mask, collective_kind, local_endpoints, peer_endpoints, local_ports,
      rank_ids, peer_macs, native_masks, result_enabled} = context_word;
  assign exact_output = output_format == PRISM_FORMAT_KULISCH
      || output_format == 8'hff;
  // Capture completion once, before driving the egress configuration enables.
  // The context remains installed until release; no payload is buffered here.
  // The request and the choice of the egress are taken from registers, so
  // the error flags of the receivers do not reach the enables of the egress
  // context in the cycle they are read.
  assign start_request = start_due && !egress_started;
  assign error_output = arithmetic_error || exact_arithmetic_fault;
  assign rounded_auto_output = ENABLE_FP32_ACCUMULATION && output_format == 8'hff
      && accumulator != PRISM_ACC_KULISCH_FIXED;
  assign rounded_auto_wide = rounded_auto_output && DATA_PORTS == 2;
  assign select_exact_egress = exact_output || error_output;
  // The egress that is started owns the stored results and the output until
  // the operation is released. Its choice is kept in a register from the
  // start on, so the context and the error flags, which do not change once
  // the inputs are drained, stay out of the read and output paths.
  always_ff @(posedge clk) begin
    if (!rst_n) output_exact <= 1'b0;
    else if (start_request) output_exact <= start_exact;
  end
  always_ff @(posedge clk) begin
    start_exact <= select_exact_egress;
    start_error <= error_output;
  end
  assign fast_read_slot = output_exact ? exact_read_slot : native_read_slot;
  assign fast_read_valid = output_exact ? exact_read_valid : native_read_valid;
  assign native_read_ready = fast_read_ready && !output_exact;
  assign exact_read_ready = fast_read_ready && output_exact;
  assign buffered_tile_ready = rounded_auto_output
      ? (!rounded_auto_wide && exact_egress_tile_ready)
      : native_egress_tile_ready;
  assign rounded_auto_tile_ready = rounded_auto_wide && exact_egress_tile_ready;
  assign exact_tile_ready = !rounded_auto_output && exact_egress_tile_ready;
  assign m_result_port = output_exact ? exact_result_port : native_result_port;
  assign m_result_tdata = output_exact ? exact_result_data : native_result_data;
  assign m_result_tkeep = output_exact ? exact_result_keep : native_result_keep;
  assign m_result_tlast = output_exact ? exact_result_last : native_result_last;
  assign m_result_frame_bytes = output_exact ? exact_result_bytes : native_result_bytes;
  // Set while a release clears the egress between two frames; see below.
  logic egress_clear;
  assign m_result_tvalid = !egress_clear
      && (output_exact ? exact_result_valid : native_result_valid);
  assign m_result_sent_mask = output_exact ? exact_sent_mask : native_sent_mask;
  // A RESULT is complete when its last beat has left the output buffer too.
  assign m_result_all_sent = output_exact
      ? exact_all_sent && !exact_result_valid : native_all_sent && !native_result_valid;

  // A release clears the egress between frames: a RESULT frame whose first
  // beat has left is sent to its end, and nothing of the operation follows.
  // The release reaches the output through a register of its own, which can
  // lie with the output buffers; the drain lasts many cycles, so the cycle
  // this costs at either end changes nothing.
  logic result_in_frame;
  (* dont_touch = "true" *) logic output_releasing;
  always_ff @(posedge clk) begin
    if (!rst_n) result_in_frame <= 1'b0;
    else if (m_result_tvalid && m_result_tready) result_in_frame <= !m_result_tlast;
  end
  always_ff @(posedge clk) output_releasing <= releasing;
  assign egress_clear = output_releasing && !result_in_frame;

  // Each egress hands its frames to a skid buffer. The selection between the
  // two then meets only the flags of the buffers instead of the output
  // registers of both egress paths.
  logic [15:0] native_stream_port, exact_stream_port, native_stream_bytes, exact_stream_bytes;
  logic [511:0] native_stream_data, exact_stream_data;
  logic [63:0] native_stream_keep, exact_stream_keep;
  logic native_stream_last, exact_stream_last, native_stream_valid, exact_stream_valid;
  logic native_stream_ready, exact_stream_ready;
  prism_axis_skid_buffer #(.DATA_W(512), .USER_W(32)) u_native_output (
      .clk(clk), .rst_n(rst_n && !egress_clear),
      .s_axis_tdata(native_stream_data), .s_axis_tkeep(native_stream_keep),
      .s_axis_tlast(native_stream_last),
      .s_axis_tuser({native_stream_port, native_stream_bytes}),
      .s_axis_tvalid(native_stream_valid), .s_axis_tready(native_stream_ready),
      .m_axis_tdata(native_result_data), .m_axis_tkeep(native_result_keep),
      .m_axis_tlast(native_result_last),
      .m_axis_tuser({native_result_port, native_result_bytes}),
      .m_axis_tvalid(native_result_valid),
      .m_axis_tready(m_result_tready && !output_exact && !egress_clear)
  );
  prism_axis_skid_buffer #(.DATA_W(512), .USER_W(32)) u_exact_output (
      .clk(clk), .rst_n(rst_n && !egress_clear),
      .s_axis_tdata(exact_stream_data), .s_axis_tkeep(exact_stream_keep),
      .s_axis_tlast(exact_stream_last),
      .s_axis_tuser({exact_stream_port, exact_stream_bytes}),
      .s_axis_tvalid(exact_stream_valid), .s_axis_tready(exact_stream_ready),
      .m_axis_tdata(exact_result_data), .m_axis_tkeep(exact_result_keep),
      .m_axis_tlast(exact_result_last),
      .m_axis_tuser({exact_result_port, exact_result_bytes}),
      .m_axis_tvalid(exact_result_valid),
      .m_axis_tready(m_result_tready && output_exact && !egress_clear)
  );
  assign m_fault = egress_fault || exact_egress_fault || store_fault;

  prism_single_native_ingress #(
      .CONTROL_PORT_INDEX(CONTROL_PORT_INDEX),
      .FIRST_DATA_PORT(FIRST_DATA_PORT), .DATA_PORTS(DATA_PORTS),
      .KULISCH_W(KULISCH_W), .MAX_KULISCH_BITS(MAX_KULISCH_BITS),
      .MAX_ORIGINAL_TERMS(MAX_ORIGINAL_TERMS), .MAX_CHILDREN(MAX_CHILDREN),
      .EXACT_BANKS(EXACT_BANKS),
      .ENABLE_FP32_ACCUMULATION(ENABLE_FP32_ACCUMULATION)
  ) u_ingress (
      .clk(clk), .rst_n(rst_n),
      .s_control_tdata(s_control_tdata), .s_control_tkeep(s_control_tkeep),
      .s_control_tlast(s_control_tlast), .s_control_tuser(s_control_tuser),
      .s_control_tvalid(s_control_tvalid),
      .s_control_tready(s_control_tready),
      .s_data_tdata(s_data_tdata), .s_data_tkeep(s_data_tkeep),
      .s_data_tlast(s_data_tlast), .s_data_tuser(s_data_tuser),
      .s_data_tvalid(s_data_tvalid), .s_data_tready(s_data_tready),
      .s_local_mac(s_local_mac), .s_manager_mac(s_manager_mac),
      .s_manager_port(s_manager_port),
      .s_control_endpoint(s_control_endpoint), .s_link_mtu(s_link_mtu),
      .s_usable_port_mask(s_usable_port_mask),
      .s_shared_port_demux(s_shared_port_demux),
      .s_result_complete_operation(context_operation),
      .s_result_complete_valid(m_result_all_sent && !complete_signaled),
      .m_control_tdata(m_control_tdata), .m_control_tkeep(m_control_tkeep),
      .m_control_tlast(m_control_tlast), .m_control_tuser(m_control_tuser),
      .m_control_frame_bytes(m_control_frame_bytes),
      .m_control_tvalid(m_control_tvalid),
      .m_control_tready(m_control_tready),
      .m_context_installed(m_context_installed),
      .m_context_active(m_context_active),
      .m_context_complete(m_context_complete),
      .m_context_operation(context_operation),
      .m_context_record(context_word), .m_child_count(unused_child_count),
      .m_inputs_drained(inputs_drained),
      .m_arithmetic_error(arithmetic_error),
      .m_exact_arithmetic_fault(exact_arithmetic_fault),
      .m_releasing(releasing), .s_release_hold(result_in_frame),
      .m_receive_complete(receive_complete),
      .m_data_event_valid(data_event_valid),
      .m_data_event_ready(data_event_ready),
      .m_data_event_status(data_event_status),
      .m_data_packet_ids(data_packet_ids), .m_data_slots(data_slots),
      .m_data_watermarks(data_watermarks),
      .m_data_complete(data_complete),
      .m_data_binding_valid(data_binding_valid),
      .s_fast_result_read_slot(fast_read_slot),
      .s_fast_result_read_valid(fast_read_valid),
      .s_fast_result_read_ready(fast_read_ready),
      .m_fast_tile_first_element(fast_tile_first),
      .m_fast_tile_keep(fast_tile_keep),
      .m_fast_tile_bits(fast_tile_bits),
      .m_fast_tile_error(fast_tile_error),
      .m_fast_tile_valid(fast_tile_valid),
      .m_fast_tile_ready(fast_tile_ready),
      .m_rounded_auto_tile_first_element(rounded_auto_tile_first),
      .m_rounded_auto_tile_keep(rounded_auto_tile_keep),
      .m_rounded_auto_tile_bits(rounded_auto_tile_bits),
      .m_rounded_auto_tile_error(rounded_auto_tile_error),
      .m_rounded_auto_tile_valid(rounded_auto_tile_valid),
      .m_rounded_auto_tile_ready(rounded_auto_tile_ready),
      .m_exact_tile_first_element(exact_tile_first),
      .m_exact_tile_keep(exact_tile_keep),
      .m_exact_tile_tags(exact_tile_tags),
      .m_exact_tile_integers(exact_tile_integers),
      .m_exact_tile_error(exact_tile_error),
      .m_exact_tile_valid(exact_tile_valid),
      .m_exact_tile_ready(exact_tile_ready),
      .m_result_store_fault(store_fault)
  );

  assign data_event_ready = '1;

  prism_elastic_skid_buffer #(.WIDTH(561)) u_result_tile_buffer (
      .clk(clk), .rst_n(rst_n && !releasing),
      .s_data({fast_tile_first, fast_tile_keep, fast_tile_bits,
          fast_tile_error}),
      .s_valid(fast_tile_valid), .s_ready(fast_tile_ready),
      .m_data({buffered_tile_first, buffered_tile_keep,
          buffered_tile_bits, buffered_tile_error}),
      .m_valid(buffered_tile_valid), .m_ready(buffered_tile_ready)
  );

  prism_single_native_stream_egress u_result_egress (
      .clk(clk), .rst_n(rst_n),
      .s_start_valid(start_request && !start_exact),
      .s_start_ready(egress_start_ready),
      .s_clear(egress_clear), .s_operation(context_operation),
      .s_element_count(total_elements), .s_mtu(mtu),
      .s_output_format(output_format), .s_child_count(child_count),
      .s_result_count(result_count), .s_result_enabled(result_enabled),
      .s_local_endpoints(local_endpoints),
      .s_peer_endpoints(peer_endpoints), .s_local_ports(local_ports),
      .s_peer_macs(peer_macs), .s_local_mac(s_local_mac),
      .m_store_read_slot(native_read_slot),
      .m_store_read_valid(native_read_valid),
      .m_store_read_ready(native_read_ready),
      .s_tile_first_element(buffered_tile_first),
      .s_tile_keep(buffered_tile_keep), .s_tile_bits(buffered_tile_bits),
      .s_tile_error(buffered_tile_error),
      .s_tile_valid(buffered_tile_valid), .s_tile_ready(native_egress_tile_ready),
      .m_egress_port(native_stream_port),
      .m_axis_tdata(native_stream_data),
      .m_axis_tkeep(native_stream_keep),
      .m_axis_tlast(native_stream_last),
      .m_axis_frame_bytes(native_stream_bytes),
      .m_axis_tvalid(native_stream_valid),
      .m_axis_tready(native_stream_ready),
      .m_sent_mask(native_sent_mask), .m_all_sent(native_all_sent),
      .m_fault(egress_fault)
  );

  prism_single_kulisch_stream_egress #(
      .LANES(RESULT_LANES), .KULISCH_W(KULISCH_W), .MAX_KULISCH_BITS(MAX_KULISCH_BITS)
  ) u_exact_result_egress (
      .clk(clk), .rst_n(rst_n),
      .s_start_valid(start_request && start_exact),
      .s_start_ready(exact_start_ready), .s_clear(egress_clear),
      .s_operation(context_operation), .s_element_count(total_elements),
      .s_mtu(mtu), .s_kulisch_bits(kulisch_bits),
      .s_auto_output(output_format == 8'hff),
      .s_native_input(rounded_auto_output),
      .s_native_wide(rounded_auto_wide),
      .s_error_only(start_error),
      .s_child_count(child_count),
      .s_result_enabled(result_enabled),
      .s_local_endpoints(local_endpoints),
      .s_peer_endpoints(peer_endpoints), .s_local_ports(local_ports),
      .s_peer_macs(peer_macs), .s_local_mac(s_local_mac),
      .m_store_read_slot(exact_read_slot),
      .m_store_read_valid(exact_read_valid),
      .m_store_read_ready(exact_read_ready),
      .s_tile_first_element(rounded_auto_output
          ? (rounded_auto_wide ? rounded_auto_tile_first : buffered_tile_first)
          : exact_tile_first),
      .s_tile_keep(rounded_auto_output
          ? (rounded_auto_wide ? rounded_auto_tile_keep[RESULT_LANES-1:0]
              : {{(RESULT_LANES-16){1'b0}}, buffered_tile_keep})
          : exact_tile_keep[RESULT_LANES-1:0]),
      .s_tile_tags(rounded_auto_output
          ? '0 : exact_tile_tags[RESULT_LANES*8-1:0]),
      .s_tile_integers(rounded_auto_output
          ? '0 : exact_tile_integers[RESULT_LANES*KULISCH_W-1:0]),
      .s_tile_native_bits(rounded_auto_output
          ? (rounded_auto_wide ? rounded_auto_tile_bits[RESULT_LANES*32-1:0]
              : {{(RESULT_LANES-16)*32{1'b0}}, buffered_tile_bits}) : '0),
      .s_tile_error(rounded_auto_output
          ? (rounded_auto_wide ? rounded_auto_tile_error : buffered_tile_error)
          : exact_tile_error),
      .s_tile_valid(rounded_auto_output
          ? (rounded_auto_wide ? rounded_auto_tile_valid : buffered_tile_valid)
          : exact_tile_valid),
      .s_tile_ready(exact_egress_tile_ready),
      .m_egress_port(exact_stream_port),
      .m_axis_tdata(exact_stream_data),
      .m_axis_tkeep(exact_stream_keep),
      .m_axis_tlast(exact_stream_last),
      .m_axis_frame_bytes(exact_stream_bytes),
      .m_axis_tvalid(exact_stream_valid),
      .m_axis_tready(exact_stream_ready),
      .m_sent_mask(exact_sent_mask), .m_all_sent(exact_all_sent),
      .m_fault(exact_egress_fault)
  );

  always_ff @(posedge clk) begin
    if (!rst_n || releasing) begin
      egress_started <= 1'b0;
      completion_pending <= 1'b0;
      start_due <= 1'b0;
      complete_signaled <= 1'b0;
    end else begin
      if (m_context_active && (inputs_drained || error_output))
        completion_pending <= 1'b1;
      if (start_request
          && (start_exact ? exact_start_ready : egress_start_ready))
        egress_started <= 1'b1;
      start_due <= m_context_active && completion_pending;
      if (m_result_all_sent) complete_signaled <= 1'b1;
    end
  end

endmodule
