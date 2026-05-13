`timescale 1ns / 1ps

module tb_mini_sharp_switch_core #(
    parameter int AXIS_WIDTH         = 512,
    parameter int MAX_PACKET_BYTES   = 2048,
    parameter int PAYLOAD_MAX_BYTES  = 1024,
    parameter int NUM_CONTEXTS       = 16,
    parameter int MAX_CONTRIBUTIONS  = 64,
    parameter int CLOCK_FREQ_HZ      = 322265625
) (
    input  logic clk,
    input  logic rst_n,
    input  logic eos,

    output logic pcapfinished
);

  logic [AXIS_WIDTH-1:0]     src_tdata;
  logic [(AXIS_WIDTH/8)-1:0] src_tstrb;
  logic [47:0]               src_tuser;
  logic                      src_tready;
  logic                      src_tvalid;
  logic                      src_tlast;
  logic [15:0]               src_pktcount;

  logic [AXIS_WIDTH-1:0]     sink_tdata;
  logic [(AXIS_WIDTH/8)-1:0] sink_tstrb;
  logic [47:0]               sink_tuser;
  logic                      sink_tready;
  logic                      sink_tvalid;
  logic                      sink_tlast;
  logic [11:0]               sink_pktcount;

  // ---------------------------------------------------------------------------
  // PCAP source
  // ---------------------------------------------------------------------------

  pcap_parse #(
      .pcap_filename ("traces/passthrough_in.pcap"),
      .use_custom_ifg("TRUE"),
      .default_ifg   (6),
      .play_in_loop  (0),
      .n_loops       (0),
      .CLOCK_FREQ_HZ (CLOCK_FREQ_HZ),
      .AXIS_WIDTH    (AXIS_WIDTH)
  ) u_pcap_parse (
      .pause       (~rst_n),
      .data        (src_tdata),
      .strb        (src_tstrb),
      .len         (src_tuser),
      .ready       (src_tready),
      .valid       (src_tvalid),
      .eop         (src_tlast),
      .clk         (clk),
      .pktcount    (src_pktcount),
      .pcapfinished(pcapfinished)
  );

  // ---------------------------------------------------------------------------
  // DUT
  // ---------------------------------------------------------------------------

  mini_sharp_switch_core #(
      .AXIS_WIDTH        (AXIS_WIDTH),
      .MAX_PACKET_BYTES  (MAX_PACKET_BYTES),
      .PAYLOAD_MAX_BYTES (PAYLOAD_MAX_BYTES),
      .NUM_CONTEXTS      (NUM_CONTEXTS),
      .MAX_CONTRIBUTIONS (MAX_CONTRIBUTIONS),
      .SWITCH_MAC        (48'h02_00_00_00_00_AA)
  ) u_mini_sharp_switch_core (
      .clk      (clk),
      .rst_n    (rst_n),

      .in_tdata  (src_tdata),
      .in_tstrb  (src_tstrb),
      .in_tuser  (src_tuser),
      .in_tready (src_tready),
      .in_tvalid (src_tvalid),
      .in_tlast  (src_tlast),

      .out_tdata  (sink_tdata),
      .out_tstrb  (sink_tstrb),
      .out_tuser  (sink_tuser),
      .out_tready (sink_tready),
      .out_tvalid (sink_tvalid),
      .out_tlast  (sink_tlast)
  );

  // ---------------------------------------------------------------------------
  // PCAP sink
  // ---------------------------------------------------------------------------

  pcap_dumper #(
      .pcap_filename ("traces/passthrough_out.pcap"),
      .c_max_pkt_size(2048),
      .c_caplen      (0),
      .c_ns_precision(1),
      .CLOCK_FREQ_HZ (CLOCK_FREQ_HZ),
      .AXIS_WIDTH    (AXIS_WIDTH)
  ) u_pcap_dumper (
      .clk     (clk),
      .rst_n   (rst_n),
      .tdata   (sink_tdata),
      .tstrb   (sink_tstrb),
      .tuser   (sink_tuser),
      .tready  (sink_tready),
      .tvalid  (sink_tvalid),
      .tlast   (sink_tlast),
      .eos     (eos),
      .pktcount(sink_pktcount)
  );

endmodule
