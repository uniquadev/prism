initial begin
  if ((NUM_CMAC_PORT < 1) || (NUM_CMAC_PORT > 2)) begin
    $fatal("PRISM supports one or two OpenNIC CMAC ports");
  end
end

localparam C_NUM_USER_BLOCK = 1;
assign mod_rst_done[15:C_NUM_USER_BLOCK] = {(16-C_NUM_USER_BLOCK){1'b1}};

prism_open_nic_250mhz #(
  .NUM_QDMA (NUM_QDMA),
  .NUM_INTF (NUM_CMAC_PORT)
) prism_open_nic_250mhz_inst (
  .s_axil_awvalid                   (axil_prism_awvalid),
  .s_axil_awaddr                    (axil_prism_awaddr),
  .s_axil_awready                   (axil_prism_awready),
  .s_axil_wvalid                    (axil_prism_wvalid),
  .s_axil_wdata                     (axil_prism_wdata),
  .s_axil_wready                    (axil_prism_wready),
  .s_axil_bvalid                    (axil_prism_bvalid),
  .s_axil_bresp                     (axil_prism_bresp),
  .s_axil_bready                    (axil_prism_bready),
  .s_axil_arvalid                   (axil_prism_arvalid),
  .s_axil_araddr                    (axil_prism_araddr),
  .s_axil_arready                   (axil_prism_arready),
  .s_axil_rvalid                    (axil_prism_rvalid),
  .s_axil_rdata                     (axil_prism_rdata),
  .s_axil_rresp                     (axil_prism_rresp),
  .s_axil_rready                    (axil_prism_rready),

  .s_axis_qdma_h2c_tvalid           (s_axis_qdma_h2c_tvalid),
  .s_axis_qdma_h2c_tdata            (s_axis_qdma_h2c_tdata),
  .s_axis_qdma_h2c_tkeep            (s_axis_qdma_h2c_tkeep),
  .s_axis_qdma_h2c_tlast            (s_axis_qdma_h2c_tlast),
  .s_axis_qdma_h2c_tuser_size       (s_axis_qdma_h2c_tuser_size),
  .s_axis_qdma_h2c_tuser_src        (s_axis_qdma_h2c_tuser_src),
  .s_axis_qdma_h2c_tuser_dst        (s_axis_qdma_h2c_tuser_dst),
  .s_axis_qdma_h2c_tready           (s_axis_qdma_h2c_tready),
  .m_axis_qdma_c2h_tvalid           (m_axis_qdma_c2h_tvalid),
  .m_axis_qdma_c2h_tdata            (m_axis_qdma_c2h_tdata),
  .m_axis_qdma_c2h_tkeep            (m_axis_qdma_c2h_tkeep),
  .m_axis_qdma_c2h_tlast            (m_axis_qdma_c2h_tlast),
  .m_axis_qdma_c2h_tuser_size       (m_axis_qdma_c2h_tuser_size),
  .m_axis_qdma_c2h_tuser_src        (m_axis_qdma_c2h_tuser_src),
  .m_axis_qdma_c2h_tuser_dst        (m_axis_qdma_c2h_tuser_dst),
  .m_axis_qdma_c2h_tready           (m_axis_qdma_c2h_tready),

  .m_axis_adap_tx_250mhz_tvalid     (m_axis_adap_tx_250mhz_tvalid),
  .m_axis_adap_tx_250mhz_tdata      (m_axis_adap_tx_250mhz_tdata),
  .m_axis_adap_tx_250mhz_tkeep      (m_axis_adap_tx_250mhz_tkeep),
  .m_axis_adap_tx_250mhz_tlast      (m_axis_adap_tx_250mhz_tlast),
  .m_axis_adap_tx_250mhz_tuser_size (m_axis_adap_tx_250mhz_tuser_size),
  .m_axis_adap_tx_250mhz_tuser_src  (m_axis_adap_tx_250mhz_tuser_src),
  .m_axis_adap_tx_250mhz_tuser_dst  (m_axis_adap_tx_250mhz_tuser_dst),
  .m_axis_adap_tx_250mhz_tready     (m_axis_adap_tx_250mhz_tready),
  .s_axis_adap_rx_250mhz_tvalid     (s_axis_adap_rx_250mhz_tvalid),
  .s_axis_adap_rx_250mhz_tdata      (s_axis_adap_rx_250mhz_tdata),
  .s_axis_adap_rx_250mhz_tkeep      (s_axis_adap_rx_250mhz_tkeep),
  .s_axis_adap_rx_250mhz_tlast      (s_axis_adap_rx_250mhz_tlast),
  .s_axis_adap_rx_250mhz_tuser_size (s_axis_adap_rx_250mhz_tuser_size),
  .s_axis_adap_rx_250mhz_tuser_src  (s_axis_adap_rx_250mhz_tuser_src),
  .s_axis_adap_rx_250mhz_tuser_dst  (s_axis_adap_rx_250mhz_tuser_dst),
  .s_axis_adap_rx_250mhz_tready     (s_axis_adap_rx_250mhz_tready),
  .mod_rstn                         (mod_rstn[0]),
  .mod_rst_done                     (mod_rst_done[0]),
`ifdef __au55n__
  .ref_clk_100mhz                   (ref_clk_100mhz),
`elsif __au55c__
  .ref_clk_100mhz                   (ref_clk_100mhz),
`elsif __au50__
  .ref_clk_100mhz                   (ref_clk_100mhz),
`elsif __au280__
  .ref_clk_100mhz                   (ref_clk_100mhz),
`endif
  .axil_aclk                        (axil_aclk),
  .axis_aclk                        (axis_aclk)
);
