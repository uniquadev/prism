**Mini-Sharp Parser**

- **Description**: Combinational extractor that decodes the Mini-Sharp header fields from a reconstructed Ethernet frame. It performs bounds checking against `MINISHARP_PAYLOAD_OFFSET` and exposes parsed fields for downstream logic.
- **Type**: Combinational (no registers)
- **Location**: repo/rtl/src/components/minisharp_parser.sv

- **Inputs**:
  - `frame` : packed bytes, width = `(MAX_PACKET_BYTES*8)` bits — full reconstructed frame.
  - `frame_len` : `uint16` — length of the reconstructed frame in bytes.

- **Outputs (names and widths)**:
  - `valid_minisharp` : `logic` — header present and frame long enough.
  - `chunk_id` : `uint32` — chunk index (little-endian assembled).
  - `p_size`   : `uint32` — payload size in bytes.
  - `flow_id`  : `uint16` — flow identifier (new, used as part of context key).
  - `operation_id` : `uint16` — zero-extended `op_flags` (compat shim for existing decoders).
  - `collective_op` : `uint8` — collective operation class (e.g., REDUCE).
  - `data_type` : `uint8` — payload element encoding (INT8/FP32/etc).
  - `collective_flags` : `uint8`.
  - `reserved` : `uint8`.
  - `expected_contributions` : `uint16` — number of contributors for this chunk.
  - `contribution_index` : `uint16` — contributor index within the group.
  - `is_reduce_sum_int8` : `logic` — convenience flag used by switch core.

- **Semantics & notes**:
  - The parser reads `flow_id` (2 bytes) and `op_flags` (1 byte). For backward compatibility with modules that expect a 16-bit `operation_id`, the parser left-pads `op_flags` with 8 zeros and exposes it as `operation_id`.
  - `MINISHARP_PAYLOAD_OFFSET` and other offsets are defined in `mini_sharp_pkg.sv`.
  - Caller (e.g., `mini_sharp_switch_core`) must check `valid_minisharp` before using other outputs.

- **Neighbors / Usage**:
  - Instantiated by `mini_sharp_switch_core` to extract header fields for routing and for feeding `collective_engine`.
