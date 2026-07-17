# 3.5 Interfaces

This chapter defines the synthesizable boundaries between PRISM RTL modules.
Each module page explains the block's architectural role and lists its contracts
as ready/valid streams, lookup/update channels, or memory interfaces with
explicit bus widths. These contracts are the common hand-off for RTL, Cocotb
unit tests, and the traffic-generation library.

The first synthesis is a minimum two-port, collective and control path only, two-rank `SINGLE` node for the lab
FPGA: both ports are 100 Gbit/s full duplex at the 250 MHz datapath
clock.
Parameterized ports, tables, resources, accumulator backends, and result routes
allow later trees and arithmetic profiles without replacing module boundaries.

The key numeric abstraction is a global element range. Endpoint DATA, switch
partial DATA, and RES use different format-derived Chunk Indices, while
accumulator state remains independent of packetization. Read the
[chunking model](../1.protocol.md#chunking-model) before implementing collective
components.

Read [Protocol](../1.protocol.md) for normative packet semantics,
[Pipeline](../2.pipeline.md) for packet movement and state transitions,
[Parameters](../4.parameters.md) for configuration, and
[Shared contracts](common-contracts.md) for packed internal bus definitions.

## Ordered module hierarchy

!!! note "Architecture contracts, not implemented ports"

    The pages below define selected module responsibilities and intended stable
    boundaries. No matching PRISM module exists in `repo/rtl/src` yet. Protocol
    wire widths are normative; internal packed widths are provisional and must
    be derived from the eventual `prism_pkg.sv` types rather than copied as an
    independent ABI. See the canonical [status table](../index.md#design-and-implementation-status).

The order below moves from integration boundaries to state-owning units and
then to their reusable components. It also mirrors the intended RTL source-tree
organization.

### Shared interface reference

1. [Shared contracts and widths](common-contracts.md) — packet streams, packed
   descriptors, operation identities, arithmetic work, result replication, and
   reliability messages used by multiple modules.

### Top-level modules

1. [`prism_switch_top`](top/prism_switch_top.md) — OpenNIC shell integration,
   clock/reset boundaries, and two physical ports.
2. [`prism_switch_core`](top/prism_switch_core.md) — shell-independent PRISM
   core intended for synthesis and end-to-end Cocotb tests.

### Main units

1. [`prism_ingress_unit`](units/prism_ingress_unit.md) — per-port staging,
   parsing, admission, storage, and packet drain.
2. [`prism_forwarding_unit`](units/prism_forwarding_unit.md) — ownership and
   forwarding decisions.
3. [`prism_management_unit`](units/prism_management_unit.md) — Protocol 1.0
   CONTROL, capabilities, setup, and context ownership.
4. [`prism_collective_unit`](units/prism_collective_unit.md) — contribution
   acceptance, profile-defined accumulation, range completion, and output
   packetization.
5. [`prism_result_delivery_unit`](units/prism_result_delivery_unit.md) — REDUCE
   routing, ALLREDUCE replication, and received-result handling.
6. [`prism_reliability_unit`](units/prism_reliability_unit.md) — PROGRESS,
   acknowledgments, duplicate feedback, replay, and retry.
7. [`prism_egress_unit`](units/prism_egress_unit.md) — VOQs, packet scheduling,
   switching, and gap-free transmission.

### Stream components

1. [`prism_packet_fifo`](components/stream/prism_packet_fifo.md)
2. [`prism_packet_store`](components/stream/prism_packet_store.md)
3. [`prism_header_parser`](components/stream/prism_header_parser.md)
4. [`prism_packet_validator`](components/stream/prism_packet_validator.md)
5. [`prism_admission_controller`](components/stream/prism_admission_controller.md)
6. [`prism_voq_bank`](components/stream/prism_voq_bank.md)
7. [`prism_packet_arbiter`](components/stream/prism_packet_arbiter.md)
8. [`prism_stream_crossbar`](components/stream/prism_stream_crossbar.md)
9. [`prism_egress_buffer`](components/stream/prism_egress_buffer.md)
10. [`prism_packet_serializer`](components/stream/prism_packet_serializer.md)

### Collective and result components

1. [`prism_collective_context_table`](components/collective/prism_collective_context_table.md)
2. [`prism_contribution_tracker`](components/collective/prism_contribution_tracker.md)
3. [`prism_data_depacketizer`](components/collective/prism_data_depacketizer.md)
4. [`prism_accumulation_scheduler`](components/collective/prism_accumulation_scheduler.md)
5. [`prism_accumulator_store`](components/collective/prism_accumulator_store.md)
6. [`prism_output_range_tracker`](components/collective/prism_output_range_tracker.md)
7. [`prism_output_packetizer`](components/collective/prism_output_packetizer.md)
8. [`prism_result_replicator`](components/collective/prism_result_replicator.md)

### Reliability components

1. [`prism_progress_engine`](components/reliability/prism_progress_engine.md)
2. [`prism_replay_cache`](components/reliability/prism_replay_cache.md)
3. [`prism_retry_timer`](components/reliability/prism_retry_timer.md)

### Arithmetic components

1. [`prism_fp32_input_converter`](components/arithmetic/prism_fp32_input_converter.md)
2. [`prism_accumulator_backend_dispatcher`](components/arithmetic/prism_accumulator_backend_dispatcher.md)
3. [`prism_fp32_alu`](components/arithmetic/prism_fp32_alu.md)
4. [`prism_fp32_alu_array`](components/arithmetic/prism_fp32_alu_array.md)
5. [`prism_fp32_output_converter`](components/arithmetic/prism_fp32_output_converter.md)
