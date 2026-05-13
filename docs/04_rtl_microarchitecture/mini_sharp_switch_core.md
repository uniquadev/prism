**mini_sharp_switch_core**

- **Description**: Top-level switch core that consumes AXI4-Stream input beats, reconstructs full Ethernet frames, parses headers, and either forwards frames unchanged (bypass) or coordinates reduction processing by `collective_engine`. The module implements an explicit FSM with clear separation of Next-State Logic, State Register, and Output Logic.
- **Type**: Sequential (FSM)
- **Location**: repo/rtl/src/top/mini_sharp_switch_core.sv

- **Top-level I/O (high-level)**:
  - Inputs:
    - `clk`, `rst_n` : clock and active-low reset.
    - AXI4-Stream input: `in_tdata` (width = `AXIS_WIDTH`), `in_tstrb`, `in_tuser` (contains metadata like src MAC), `in_tvalid`, `in_tlast`, `in_tready` (handshake).
    - `engine_done_valid`, `engine_out_valid` (from `collective_engine`).
  - Outputs:
    - AXI4-Stream output: `out_tdata`, `out_tstrb`, `out_tuser`, `out_tvalid`, `out_tlast`, and `out_tready` (peer backpressure).

- **Internal instantiations / neighbors**:
  - `eth_parser` — used to quickly filter frames by EtherType.
  - `minisharp_parser` — extracts Mini-Sharp header fields (`flow_id`, `op_flags`, etc.).
  - `collective_engine` — invoked when a supported reduction packet is recognized.

- **FSM (conceptual)**:
  - `STATE_RX`       : accumulate AXI beats into an internal frame buffer until `in_tlast`.
  - `STATE_PROCESS`  : run parsers (`eth_parser` + `minisharp_parser`) and decide path.
  - `STATE_WAIT_ENGINE`: forward frame to `collective_engine` and wait for completion/emit.
  - `STATE_TX_PREPARE`: prepare outbound frame(s).
  - `STATE_TX_SEND`  : stream out prepared frames respecting `out_tready`/`out_tlast`.

- **Design notes**:
  - The module separates: combinational Next-State Logic (compute `next_state`), sequential State Register (`always_ff` updating `state <= next_state`), and Output Logic (combinational outputs derived from state and inputs). This pattern eases formal/sequential reasoning and helps timing closure.
  - A packet is forwarded to `collective_engine` when `eth_parser.is_reduction_ethertype` && `minisharp_parser.valid_minisharp` && reduction is supported for the parsed fields.
  - The switch cores rewrite source MAC when `collective_engine` emits a reduced frame; `flow_id` from the parsed header is passed through to the engine and written back into emitted frames to preserve traceability.
