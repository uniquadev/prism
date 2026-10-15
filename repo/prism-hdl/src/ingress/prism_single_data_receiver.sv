//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_single_data_receiver.sv
// Module: prism_single_data_receiver
// Description: Validated, bound DATA frames into aligned native arithmetic tiles.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

module prism_single_data_receiver #(
    parameter int unsigned PORT_INDEX = 0,
    parameter int unsigned MAX_MTU = 1500,
    parameter int unsigned WINDOW_PACKETS = 2,
    // Admission uses element indices; one frame can carry this many INT8 values.
    parameter int unsigned WINDOW_ELEMENTS = WINDOW_PACKETS * 4 * ((MAX_MTU
        - prism_pkg::PRISM_CONTROL_WORD_BYTES
        - prism_pkg::PRISM_DATA_HEADER_BYTES
        - prism_pkg::PRISM_NUMBERGROUP_DESCRIPTOR_BYTES) / 4),
    parameter int unsigned MAX_CHILDREN = 8,
    parameter int unsigned CHILD_W = $clog2(MAX_CHILDREN)
) (
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic [511:0]                      s_axis_tdata,
    input  logic [63:0]                       s_axis_tkeep,
    input  logic                              s_axis_tlast,
    input  logic                              s_axis_tuser,
    input  logic                              s_axis_tvalid,
    output logic                              s_axis_tready,
    input  logic                              s_active,
    input  prism_pkg::prism_operation_key_t   s_operation,
    input  logic [31:0]                       s_total_elements,
    input  logic [15:0]                       s_mtu,
    input  logic [15:0]                       s_kulisch_bits,
    input  logic [47:0]                       s_local_mac,
    input  logic [7:0]                        s_child_count,
    input  logic [MAX_CHILDREN*16-1:0]        s_local_endpoints,
    input  logic [MAX_CHILDREN*16-1:0]        s_peer_endpoints,
    input  logic [MAX_CHILDREN*16-1:0]        s_local_ports,
    input  logic [MAX_CHILDREN*48-1:0]        s_peer_macs,
    input  logic [MAX_CHILDREN*8-1:0]         s_native_masks,
    input  logic                              s_release,
    // The datapath behind the receiver is being emptied: no new frame is
    // taken from the port until this is over.
    input  logic                              s_hold,
    output logic [MAX_CHILDREN-1:0]           m_receive_complete,
    output logic                              m_arithmetic_error,
    output logic                              m_idle,
    output logic [31:0]                       m_tile_first_element,
    output logic [7:0]                        m_tile_format,
    output logic [7:0]                        m_tile_count,
    output logic [CHILD_W-1:0]              m_tile_contributor_slot,
    output logic [511:0]                      m_tile_bits,
    output logic [63:0]                       m_tile_keep,
    output logic                              m_tile_valid,
    input  logic                              m_tile_ready,
    output logic                              m_frame_event_valid,
    input  logic                              m_frame_event_ready,
    output logic [2:0]                        m_frame_event_status,
    output logic [31:0]                       m_frame_packet_id,
    output logic                              m_frame_binding_valid,
    output logic [CHILD_W-1:0]              m_frame_contributor_slot,
    output logic [31:0]                       m_frame_cumulative_element,
    output logic                              m_frame_complete
);

  import prism_pkg::*;
  localparam int unsigned MAX_PACKET_ELEMENTS = 4 * ((MAX_MTU
      - PRISM_CONTROL_WORD_BYTES - PRISM_DATA_HEADER_BYTES
      - PRISM_NUMBERGROUP_DESCRIPTOR_BYTES) / 4);
  localparam int unsigned DATA_OVERHEAD_BYTES = PRISM_CONTROL_WORD_BYTES
      + PRISM_DATA_HEADER_BYTES + PRISM_NUMBERGROUP_DESCRIPTOR_BYTES;
  typedef enum logic [1:0] {
    ADMIT_IDLE, ADMIT_WAIT, ADMIT_READ, ADMIT_REJECT
  } admission_state_t;
  admission_state_t admission_state;
  prism_numbergroup_header_t header;
  prism_numbergroup_header_t validator_header [0:1];
  prism_tile_meta_t base_meta, tile_meta;
  logic [15:0] frame_bytes, read_address, reader_read_address;
  logic [15:0] validator_frame_bytes [0:1];
  logic [15:0] fast_read_address;
  logic [7:0] read_data;
  logic [7:0] validator_read_data [0:1];
  logic [4:0] format_mask;
  logic [4:0] validator_format_mask [0:1];
  logic frame_valid, frame_accept, validator_ready;
  logic [1:0] validator_valid, validator_accept;
  logic [1:0] validator_input_ready;
  logic validator_consume, input_frame_end;
  logic rx_bank, process_bank;
  logic [1:0] frames_pending;
  logic [2:0] frame_error;
  logic [2:0] validator_error [0:1];
  logic [31:0] global_index;
  logic [7:0] format_id, group_index, value_byte;
  logic [15:0] value_bytes, byte_index;
  logic element_last_byte, group_last_byte, packet_last_byte;
  logic value_valid, value_ready, reader_ready, reader_done;
  logic window_s_ready, window_m_valid, window_m_ready;
  logic window_release_ready, release_pending;
  logic rx_in_progress, allow_input;
  logic [1:0] window_reason;
  logic [15:0] active_window_elements;
  logic [MAX_CHILDREN-1:0] window_complete;
  logic [MAX_CHILDREN*32-1:0] window_watermarks;
  logic raw_frame_event, event_pending;
  logic [2:0] event_status_reg;
  logic [CHILD_W-1:0] event_slot_reg;
  logic [31:0] event_packet_id_reg, event_cumulative_reg;
  logic event_binding_reg, event_complete_reg;
  logic [511:0] read_word, read_next_word;
  logic [511:0] validator_word [0:1], validator_next_word [0:1];
  logic read_finished_now, commit_frame;
  logic fast_native_mode, fast_done, fast_tile_valid, fast_tile_ready;
  logic start_fast_native;
  logic [7:0] fast_format, selected_fast_format;
  logic [31:0] fast_tile_first;
  logic [7:0] fast_tile_count;
  logic [511:0] fast_tile_bits, scalar_tile_bits;
  logic [63:0] fast_tile_keep;
  logic [63:0] scalar_tile_keep;
  logic scalar_tile_valid, scalar_tile_ready;
  logic binding_found, eligible, terminal_error;
  logic [CHILD_W-1:0] binding_slot, selected_slot;
  logic [7:0] binding_mask;
  logic unused_fields;
  assign unused_fields = ^{frame_bytes, frame_error, group_index,
      value_bytes, group_last_byte, reader_ready, binding_mask};

  initial begin
    if (MAX_MTU < 576 || MAX_CHILDREN < 2 || MAX_CHILDREN > 16
        || CHILD_W < $clog2(MAX_CHILDREN)
        || WINDOW_ELEMENTS < WINDOW_PACKETS * MAX_PACKET_ELEMENTS
        || WINDOW_ELEMENTS > 65535 || WINDOW_PACKETS < 1
        || WINDOW_PACKETS > 8)
      $fatal(1, "SINGLE DATA receiver requires bounded windows and children");
  end

  assign m_idle = admission_state == ADMIT_IDLE && !frame_valid
      && !release_pending && !rx_in_progress && !m_tile_valid
      && !event_pending && frames_pending == 0;
  assign m_receive_complete = window_complete;
  // The deployed MTU sets the receive span; MAX_MTU only sizes hardware.
  assign active_window_elements = int'(s_mtu) >= DATA_OVERHEAD_BYTES
      && int'(s_mtu) <= MAX_MTU
      ? 16'(WINDOW_PACKETS * ((int'(s_mtu) - DATA_OVERHEAD_BYTES) & 32'hffff_fffc))
      : '0;
  assign m_tile_first_element = fast_native_mode ? fast_tile_first
      : tile_meta.first_element;
  assign m_tile_format = fast_native_mode ? fast_format
      : tile_meta.input_format;
  assign m_tile_count = fast_native_mode ? fast_tile_count
      : tile_meta.element_count;
  assign m_tile_contributor_slot = fast_native_mode ? selected_slot
      : CHILD_W'(tile_meta.contributor_id);
  assign m_tile_bits = fast_native_mode ? fast_tile_bits : scalar_tile_bits;
  assign m_tile_keep = fast_native_mode ? fast_tile_keep
      : scalar_tile_keep;
  assign m_tile_valid = fast_native_mode ? fast_tile_valid : scalar_tile_valid;
  assign fast_tile_ready = fast_native_mode && m_tile_ready;
  assign selected_fast_format = format_mask == 5'b00001 ? PRISM_FORMAT_INT8
      : format_mask == 5'b00010 ? PRISM_FORMAT_FP16
      : format_mask == 5'b00100 ? PRISM_FORMAT_BF16 : PRISM_FORMAT_FP32;
  assign start_fast_native = admission_state == ADMIT_WAIT
      && window_m_valid && window_reason == 0
      && header.group_count == 8'd1
      && format_mask inside {5'b00001, 5'b00010, 5'b00100, 5'b01000};
  assign scalar_tile_ready = !fast_native_mode && m_tile_ready;
  assign m_frame_packet_id = event_packet_id_reg;
  assign m_frame_contributor_slot = event_slot_reg;
  assign m_frame_binding_valid = event_binding_reg;
  assign m_frame_cumulative_element = event_cumulative_reg;
  assign m_frame_complete = event_complete_reg;
  assign read_address = reader_read_address;
  assign allow_input = rx_in_progress
      || (!release_pending && !s_release && !s_hold);
  assign input_frame_end = s_axis_tvalid && s_axis_tready && s_axis_tlast;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      rx_bank <= 1'b0;
      process_bank <= 1'b0;
      frames_pending <= '0;
    end else begin
      if (input_frame_end) rx_bank <= !rx_bank;
      if (validator_consume) process_bank <= !process_bank;
      case ({input_frame_end, validator_consume})
        2'b10: frames_pending <= frames_pending + 2'd1;
        2'b01: frames_pending <= frames_pending - 2'd1;
        default: frames_pending <= frames_pending;
      endcase
    end
  end

  // What the header of a frame says against the operation is found for each
  // frame buffer on its own and registered. A validator has the header from
  // the first beat of its frame and reports the frame at least two cycles
  // later, and the operation does not change while it is active, so the
  // registered answer is that of the frame by the time the frame is reported.
  logic [1:0] checked_found, checked_addressed, checked_data, checked_terminal;
  logic [CHILD_W-1:0] checked_slot [0:1];
  logic [7:0] checked_mask [0:1];
  for (genvar bank = 0; bank < 2; bank++) begin : gen_header_check
    prism_numbergroup_header_t checked;
    logic found, addressed, in_vector;
    logic [CHILD_W-1:0] slot;
    logic [7:0] mask;
    logic [32:0] frame_end;
    assign checked = validator_header[bank];
    always_comb begin
      found = 1'b0;
      slot = '0;
      mask = '0;
      for (integer child = 0; child < MAX_CHILDREN; child++) begin
        if (child < int'(s_child_count) && !found
            && checked.destination_endpoint == s_local_endpoints[child*16 +: 16]
            && checked.source_endpoint == s_peer_endpoints[child*16 +: 16]
            && checked.stream_id == s_local_endpoints[child*16 +: 16]
            && checked.ingress_port == s_local_ports[child*16 +: 16]
            && checked.source_mac == s_peer_macs[child*48 +: 48]) begin
          found = 1'b1;
          slot = CHILD_W'(child);
          mask = s_native_masks[child*8 +: 8];
        end
      end
    end
    assign addressed = checked.key == s_operation
        && checked.packet_class == PRISM_OP_COL_DATA
        && checked.destination_mac == s_local_mac;
    assign frame_end = {1'b0, checked.first_element} + 33'(checked.element_count);
    assign in_vector = s_total_elements != 0
        && frame_end <= {1'b0, s_total_elements}
        && checked.flags[0] == (frame_end == {1'b0, s_total_elements});
    always_ff @(posedge clk) begin
      checked_found[bank] <= found;
      checked_slot[bank] <= slot;
      checked_mask[bank] <= mask;
      checked_addressed[bank] <= checked.key == s_operation
          && checked.destination_mac == s_local_mac;
      checked_data[bank] <= addressed && found && in_vector
          && (checked.flags & PRISM_DATA_FLAG_ACCUMULATION_INEXACT) == 0;
      checked_terminal[bank] <= addressed && found
          && checked.flags == (PRISM_DATA_FLAG_LAST | PRISM_DATA_FLAG_ACCUMULATION_INEXACT);
    end
  end
  assign binding_found = checked_found[process_bank];
  assign binding_slot = checked_slot[process_bank];
  assign binding_mask = checked_mask[process_bank];
  assign eligible = s_active && checked_data[process_bank]
      && (format_mask & ~binding_mask[4:0]) == 0;
  assign terminal_error = frame_valid && frame_accept
      && s_active && checked_terminal[process_bank];

  assign header = validator_header[process_bank];
  assign frame_bytes = validator_frame_bytes[process_bank];
  assign format_mask = validator_format_mask[process_bank];
  assign frame_accept = validator_accept[process_bank];
  assign frame_error = validator_error[process_bank];
  assign frame_valid = validator_valid[process_bank];
  assign read_data = validator_read_data[process_bank];
  assign read_word = validator_word[process_bank];
  assign read_next_word = validator_next_word[process_bank];
  assign validator_ready = validator_input_ready[rx_bank];
  assign read_finished_now = (fast_native_mode && fast_done)
      || (!fast_native_mode && reader_done);
  assign commit_frame = admission_state == ADMIT_READ && read_finished_now;
  assign validator_consume = frame_valid && (!frame_accept
      || (admission_state == ADMIT_IDLE && terminal_error)
      || (admission_state == ADMIT_IDLE && !event_pending && !eligible)
      || admission_state == ADMIT_REJECT
      || commit_frame);

  for (genvar bank = 0; bank < 2; bank++) begin : gen_validator
    prism_numbergroup_frame_validator #(
        .MAX_MTU(MAX_MTU), .PORT_INDEX(PORT_INDEX)
    ) u_validator (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tlast(s_axis_tlast), .s_axis_tuser(s_axis_tuser),
        .s_axis_tvalid(s_axis_tvalid && allow_input && rx_bank == 1'(bank)),
        .s_axis_tready(validator_input_ready[bank]),
        .s_mtu(s_mtu), .s_kulisch_bits(s_kulisch_bits),
        .m_header(validator_header[bank]),
        .m_frame_bytes(validator_frame_bytes[bank]),
        .m_format_mask(validator_format_mask[bank]),
        .m_accept(validator_accept[bank]),
        .m_error_code(validator_error[bank]),
        .m_valid(validator_valid[bank]),
        .m_ready(validator_consume && process_bank == 1'(bank)),
        .m_read_address(read_address), .m_read_data(validator_read_data[bank]),
        .m_read_word_address(fast_read_address),
        .m_read_word_data(validator_word[bank]),
        .m_read_next_word_data(validator_next_word[bank]),
        .m_copy_word_address('0),
        .m_copy_word_data()
    );
  end

  assign s_axis_tready = validator_ready && allow_input;

  // The window prepares the admission of the frame in either bank from the
  // header registers of the banks, which are loaded with the first beat of
  // a frame, several cycles before the frame is offered.
  prism_numbergroup_interval_window #(
      .WINDOW_ELEMENTS(WINDOW_ELEMENTS), .CONTRIBUTORS(MAX_CHILDREN),
      .CONTRIBUTOR_W(CHILD_W), .CANDIDATES(2)
  ) u_window (
      .clk(clk), .rst_n(rst_n),
      .s_first_element({validator_header[1].first_element,
          validator_header[0].first_element}),
      .s_element_count({validator_header[1].element_count,
          validator_header[0].element_count}),
      .s_total_elements(s_total_elements),
      .s_window_elements(active_window_elements),
      .s_candidate(process_bank),
      .s_contributor_slot(binding_slot), .s_last(header.flags[0]),
      .s_valid(admission_state == ADMIT_IDLE && frame_valid
          && !event_pending && frame_accept && eligible),
      .s_ready(window_s_ready),
      .s_release(release_pending && admission_state == ADMIT_IDLE
          && !frame_valid),
      .s_release_ready(window_release_ready),
      .m_complete(window_complete),
      .m_watermarks(window_watermarks),
      .m_reason(window_reason), .m_valid(window_m_valid),
      .m_ready(window_m_ready)
  );

  assign window_m_ready = admission_state == ADMIT_WAIT;
  assign raw_frame_event = frame_valid && frame_accept && (
      (admission_state == ADMIT_IDLE && !event_pending && !eligible
          && !terminal_error)
      || admission_state == ADMIT_REJECT
      || commit_frame);
  assign m_frame_event_valid = event_pending;
  assign m_frame_event_status = event_status_reg;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      m_arithmetic_error <= 1'b0;
      admission_state <= ADMIT_IDLE;
      selected_slot <= '0;
      release_pending <= 1'b0;
      rx_in_progress <= 1'b0;
      event_pending <= 1'b0;
      event_status_reg <= '0;
      event_slot_reg <= '0;
      event_packet_id_reg <= '0;
      event_cumulative_reg <= '0;
      event_binding_reg <= 1'b0;
      event_complete_reg <= 1'b0;
      fast_native_mode <= 1'b0;
      fast_format <= '0;
    end else begin
      if (s_release || s_hold) m_arithmetic_error <= 1'b0;
      else if (admission_state == ADMIT_IDLE && terminal_error)
        m_arithmetic_error <= 1'b1;
      if (raw_frame_event) begin
        logic [CHILD_W-1:0] event_slot;
        event_slot = admission_state == ADMIT_IDLE ? binding_slot : selected_slot;
        event_pending <= 1'b1;
        event_status_reg <= commit_frame ? 3'd0 : 3'd4;
        event_slot_reg <= event_slot;
        event_packet_id_reg <= header.packet_id;
        event_cumulative_reg <= window_watermarks[event_slot*32 +: 32];
        event_binding_reg <= binding_found && s_active
            && checked_addressed[process_bank];
        event_complete_reg <= window_complete[event_slot];
      end else if (event_pending && m_frame_event_ready) begin
        event_pending <= 1'b0;
      end
      if (s_axis_tvalid && s_axis_tready)
        rx_in_progress <= !s_axis_tlast;
      if (s_release) release_pending <= 1'b1;
      else if (release_pending && window_release_ready
          && admission_state == ADMIT_IDLE && !frame_valid)
        release_pending <= 1'b0;
      case (admission_state)
        ADMIT_IDLE: begin
          if (frame_valid && !event_pending && frame_accept && eligible) begin
            selected_slot <= binding_slot;
            if (window_s_ready) admission_state <= ADMIT_WAIT;
          end
        end
        ADMIT_WAIT: begin
          if (window_m_valid) begin
            admission_state <= window_reason == 0 ? ADMIT_READ : ADMIT_REJECT;
            if (window_reason == 0) begin
              fast_native_mode <= header.group_count == 8'd1
                  && format_mask inside {5'b00001, 5'b00010, 5'b00100, 5'b01000};
              fast_format <= selected_fast_format;
            end
          end
        end
        ADMIT_READ: begin
          if (commit_frame) admission_state <= ADMIT_IDLE;
        end
        ADMIT_REJECT: admission_state <= ADMIT_IDLE;
        default: admission_state <= ADMIT_IDLE;
      endcase
    end
  end

  prism_numbergroup_value_reader u_reader (
      .clk(clk), .rst_n(rst_n),
      .s_header(header), .s_kulisch_bits(s_kulisch_bits),
      .s_valid(frame_valid && admission_state == ADMIT_READ
          && !fast_native_mode),
      .s_ready(reader_ready),
      .read_address(reader_read_address), .read_data(read_data),
      .m_global_index(global_index), .m_format(format_id),
      .m_group_index(group_index), .m_value_bytes(value_bytes),
      .m_byte_index(byte_index), .m_value_byte(value_byte),
      .m_element_last_byte(element_last_byte),
      .m_group_last_byte(group_last_byte),
      .m_packet_last_byte(packet_last_byte),
      .m_valid(value_valid), .m_ready(value_ready),
      .m_done_valid(reader_done), .m_done_ready(1'b1)
  );

  prism_numbergroup_native_tile_reader u_fast_reader (
      .clk(clk), .rst_n(rst_n),
      .s_first_element(header.first_element),
      .s_element_count(header.element_count),
      .s_format(selected_fast_format),
      .s_start_valid(frame_valid && (start_fast_native
          || (admission_state == ADMIT_READ && fast_native_mode))), .s_start_ready(),
      .m_read_word_address(fast_read_address),
      .s_read_word(read_word), .s_read_next_word(read_next_word),
      .m_tile_first_element(fast_tile_first),
      .m_tile_count(fast_tile_count),
      .m_tile_bits(fast_tile_bits), .m_tile_keep(fast_tile_keep),
      .m_tile_valid(fast_tile_valid), .m_tile_ready(fast_tile_ready),
      .m_done_valid(fast_done), .m_done_ready(1'b1)
  );

  always_comb begin
    base_meta = '0;
    base_meta.key = header.key;
    base_meta.contributor_id = 16'(selected_slot);
    base_meta.operation_slot = 16'd0;
    base_meta.group_slot = 16'd0;
    base_meta.expected_contributors = 16'(s_child_count);
    base_meta.total_element_count = s_total_elements;
  end

  prism_numbergroup_native_tile_builder u_builder (
      .clk(clk), .rst_n(rst_n),
      .s_base_meta(base_meta), .s_global_index(global_index),
      .s_format(format_id), .s_byte_index(byte_index),
      .s_value_byte(value_byte),
      .s_element_last_byte(element_last_byte),
      .s_packet_last_byte(packet_last_byte),
      .s_valid(value_valid), .s_ready(value_ready),
      .m_meta(tile_meta), .m_element_bits(scalar_tile_bits),
      .m_element_keep(scalar_tile_keep),
      .m_valid(scalar_tile_valid), .m_ready(scalar_tile_ready)
  );

endmodule
