# 3.4 RTL modules

This section documents the stable production boundaries in the current RTL.
It is intentionally not a page for every leaf primitive: small converters,
FIFOs, arbiters, table implementations, and verification harnesses remain
implementation details.

The interfaces shared by these modules are defined in
[Current shared contracts](common-contracts.md).

## Integration and composition

- [`prism_open_nic_250mhz`](top/prism_open_nic_250mhz.md): adapts PRISM to the OpenNIC 250 MHz plugin interface.
- [`prism_collective_core`](core/prism_collective_core.md): composes the reusable control plane and collective datapath.

## Ingress and control

- [`prism_ingress_port`](ingress/prism_ingress_port.md): buffers, parses, looks up, and validates one external ingress stream.
- [`prism_control_reassembler`](control/prism_control_reassembler.md): reconstructs a complete CONTROL message from bounded fragments.
- [`prism_control_executor`](control/prism_control_executor.md): dispatches typed control requests and owns the state-table access boundary.

## Collective datapath

- [`prism_data_depacketizer`](collective/prism_data_depacketizer.md): removes DATA framing and emits lane-aligned arithmetic tiles.
- [`prism_input_conversion_stage`](conversion/prism_input_conversion_stage.md): converts wire elements into the selected arithmetic representation.
- [`prism_range_scheduler`](collective/prism_range_scheduler.md): collects contributor tiles and publishes completed reduced ranges.
- [`prism_result_chunk_store`](collective/prism_result_chunk_store.md): assembles reduced elements into immutable reference-counted result chunks.
- [`prism_result_router`](collective/prism_result_router.md): expands a completed chunk into per-destination packet jobs.
- [`prism_result_packetizer`](egress/prism_result_packetizer.md): serializes one stored chunk as an Ethernet RES frame.
