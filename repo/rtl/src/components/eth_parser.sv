`timescale 1ns / 1ps

import mini_sharp_pkg::*;

module eth_parser #(
    parameter int MAX_PACKET_BYTES = 2048
) (
    input  logic [(MAX_PACKET_BYTES*8)-1:0] frame,
    input  logic [15:0]                     frame_len,

    output logic [47:0]                     dst_mac,
    output logic [47:0]                     src_mac,
    output logic [15:0]                     ethertype,
    output logic                            is_reduction_ethertype,
    output logic                            valid_eth_frame
);

  always_comb begin
    valid_eth_frame = frame_len >= ETH_HDR_BYTES;

    dst_mac = {
      frame[8*(ETH_DST_OFFSET + 0) +: 8],
      frame[8*(ETH_DST_OFFSET + 1) +: 8],
      frame[8*(ETH_DST_OFFSET + 2) +: 8],
      frame[8*(ETH_DST_OFFSET + 3) +: 8],
      frame[8*(ETH_DST_OFFSET + 4) +: 8],
      frame[8*(ETH_DST_OFFSET + 5) +: 8]
    };

    src_mac = {
      frame[8*(ETH_SRC_OFFSET + 0) +: 8],
      frame[8*(ETH_SRC_OFFSET + 1) +: 8],
      frame[8*(ETH_SRC_OFFSET + 2) +: 8],
      frame[8*(ETH_SRC_OFFSET + 3) +: 8],
      frame[8*(ETH_SRC_OFFSET + 4) +: 8],
      frame[8*(ETH_SRC_OFFSET + 5) +: 8]
    };

    ethertype = {
      frame[8*(ETH_ETYPE_OFFSET + 0) +: 8],
      frame[8*(ETH_ETYPE_OFFSET + 1) +: 8]
    };

    is_reduction_ethertype = valid_eth_frame && (ethertype == ETHERTYPE_REDUCTION);
  end

endmodule