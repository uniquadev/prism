**Collective Engine**

- **Description**: Stateful reduction engine that maintains per-chunk contexts, accumulates contributions from multiple senders, and emits a single reduced packet when a context completes. Contexts are uniquely identified by `(flow_id, chunk_id)`.
- **Type**: Sequential (FSM)
- **Location**: repo/rtl/src/components/collective_engine.sv

- **Top-level I/O (names and widths)**:
  - Inputs:
    - `clk`, `rst_n` : clock and active-low reset.
    - `in_valid` : `logic` — indicates `in_frame`/metadata are valid.
    - `in_frame` : packed bits representing the full Ethernet frame (`(MAX_PACKET_BYTES*8)-1:0`).
    - `in_frame_len` : `uint16` — frame length in bytes.
    - `in_chunk_id` : `uint32` — chunk identifier.
    - `in_p_size` : `uint32` — payload size.
    - `in_operation_id` : `uint16` — zero-extended op flags (compatibility field).
    - `in_flow_id` : `uint16` — flow identifier (new field, used as context key).
    - `in_collective_op` : `uint8`.
    - `in_data_type` : `uint8`.
    - `in_collective_flags` : `uint8`.
    - `in_expected_contributions` : `uint16`.
    - `in_contribution_index` : `uint16`.
  - Outputs:
    - `done_valid` : `logic` — indicates context bookkeeping updated.
    - `out_valid` : `logic` — indicates `out_frame` contains a valid emitted reduced frame.
    - `out_frame` : packed bits (`(MAX_PACKET_BYTES*8)-1:0`) — the emitted Ethernet frame.
    - `out_frame_len` : `uint16` — length of `out_frame`.

- **Internal behavior / FSM**:
  - `STATE_IDLE`       : wait for `in_valid`. On acceptance, find or allocate a context keyed by `(in_flow_id, in_chunk_id)`.
  - `STATE_LANE_READ`  : read a single lane of the payload and prepare sample + accumulator for ALU.
  - `STATE_LANE_EXEC`  : apply the `fp32_alu` using decoded operation.
  - `STATE_LANE_WRITE` : store updated accumulator; when all lanes processed for the contribution/context, update the contributor count and set pending emit if complete.
  - `STATE_EMIT`       : finalize the reduced payload (apply finalization for AVG) and emit a single reduced Ethernet frame.

- **Design notes & invariants**:
  - Contexts are tracked in arrays: `ctx_valid[]`, `ctx_chunk_id[]`, `ctx_flow_id[]`, `ctx_operation_id[]`, contributor counters, and accumulators.
  - The engine writes the `flow_id` back into the emitted header to preserve traceability.
  - Next-state combinational logic is separated from the state register (flip-flops) and output logic, following the project's FSM style guidelines.

- **Neighbors / Connections**:
  - Input: driven from `mini_sharp_switch_core` when a supported reduction packet is identified.
  - Uses `reduction_input_converter`, `reduction_op_decoder`, `reduction_output_converter`, and `fp32_alu` math units.

