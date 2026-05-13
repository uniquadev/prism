`timescale 1ns / 1ps

package mini_sharp_pkg;

  parameter int ETH_HDR_BYTES             = 14;
  parameter int ETH_DST_OFFSET            = 0;
  parameter int ETH_SRC_OFFSET            = 6;
  parameter int ETH_ETYPE_OFFSET          = 12;

  parameter int MINISHARP_OFFSET          = ETH_HDR_BYTES;

  // Mini-Sharp byte order policy:
  //   - Ethernet header fields keep standard Ethernet/network byte order.
  //   - All Mini-Sharp custom multi-byte header fields are little-endian.
  //   - All Mini-Sharp multi-byte payload elements are little-endian.

  parameter int CHUNK_ID_OFFSET           = MINISHARP_OFFSET + 0;
  parameter int P_SIZE_OFFSET             = MINISHARP_OFFSET + 4;
  // Revised header layout (breaking change):
  // chunk_id (4) | p_size (4) | flow_id (2) | collective_op (1) | op_flags (1)
  // data_type (1) | collective_flags (1) | reserved (1) | expected (2) | contribution_index (2)
  parameter int FLOW_ID_OFFSET            = MINISHARP_OFFSET + 8;
  parameter int COLLECTIVE_OP_OFFSET      = MINISHARP_OFFSET + 10;
  parameter int OP_FLAGS_OFFSET           = MINISHARP_OFFSET + 11;
  parameter int DATA_TYPE_OFFSET          = MINISHARP_OFFSET + 12;
  parameter int COLLECTIVE_FLAGS_OFFSET   = MINISHARP_OFFSET + 13;
  parameter int RESERVED_OFFSET           = MINISHARP_OFFSET + 14;
  parameter int EXPECTED_CONTRIB_OFFSET   = MINISHARP_OFFSET + 15;
  parameter int CONTRIBUTION_INDEX_OFFSET = MINISHARP_OFFSET + 17;

  parameter int MINISHARP_HDR_BYTES       = 19;
  parameter int MINISHARP_PAYLOAD_OFFSET  = ETH_HDR_BYTES + MINISHARP_HDR_BYTES;

  parameter logic [15:0] ETHERTYPE_REDUCTION = 16'h88B5;

  typedef enum logic [7:0] {
    REDUCE_OP_SUM = 8'd0,
    REDUCE_OP_MIN = 8'd1,
    REDUCE_OP_MAX = 8'd2,
    REDUCE_OP_AVG = 8'd3
  } reduce_operation_e;

  typedef enum logic [7:0] {
    COLLECTIVE_GATHER = 8'd0,
    COLLECTIVE_REDUCE = 8'd1
  } collective_op_e;

  typedef enum logic [7:0] {
    DTYPE_FP32 = 8'd0,
    DTYPE_BF16 = 8'd1,
    DTYPE_FP16 = 8'd2,
    DTYPE_INT8 = 8'd3
  } payload_dtype_e;

  // Operazioni primitive della ALU FP32.
  //
  // Questa enum è volutamente separata da reduce_operation_e:
  // reduce_operation_e descrive la semantica della collective,
  // fp32_alu_op_e descrive solo cosa deve fare il blocco aritmetico FP32.
  typedef enum logic [3:0] {
    FP32_ALU_PASS = 4'd0,
    FP32_ALU_ADD  = 4'd1,
    FP32_ALU_MIN  = 4'd2,
    FP32_ALU_MAX  = 4'd3
  } fp32_alu_op_e;

  function automatic logic [7:0] saturate_u8;
    input logic [31:0] value;
    begin
      if (value > 32'd255) begin
        saturate_u8 = 8'hff;
      end else begin
        saturate_u8 = value[7:0];
      end
    end
  endfunction

endpackage
