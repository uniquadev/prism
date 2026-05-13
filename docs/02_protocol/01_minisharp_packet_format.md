# Mini-Sharp packet format (updated)

Ethernet header: 14 bytes.

Mini-Sharp header (current implementation, breaking change): 19 bytes consisting of:

- `chunk_id` (4 bytes)
- `p_size` (4 bytes)
- `flow_id` (2 bytes)
- `collective_op` (1 byte)
- `op_flags` (1 byte)  # meaning depends on `collective_op` (for REDUCE, contains reduce operator)
- `data_type` (1 byte)
- `collective_flags` (1 byte)
- `reserved` (1 byte)
- `expected_contributions` (2 bytes)
- `contribution_index` (2 bytes)

Offset summary (relative to Ethernet header):

- `CHUNK_ID_OFFSET = 0`
- `P_SIZE_OFFSET = 4`
- `FLOW_ID_OFFSET = 8`
- `COLLECTIVE_OP_OFFSET = 10`
- `OP_FLAGS_OFFSET = 11`
- `DTYPE_OFFSET = 12`
- `FLAGS_OFFSET = 13`
- `RESERVED_OFFSET = 14`
- `EXPECTED_OFFSET = 15`
- `CONTRIB_OFFSET = 17`

Current verified frame length: 14 (Ethernet) + 19 (Mini-Sharp) + payload size.
