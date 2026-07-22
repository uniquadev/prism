# `prism_collective_core`

**Module class:** reusable architecture root

`prism_collective_core` is the production-independent composition boundary. It
connects the ingress, control, reduction, storage, routing, and egress stages
without embedding an FPGA-shell interface.

## Contracts

- **Per-port ingress AXI streams:** accept complete Ethernet frames from the deployment adapter.
- **Per-port egress AXI streams:** publish complete CONTROL or RES frames and their logical byte lengths.
- **Local configuration:** receive the local MAC vector and the laboratory-extension enable bit.
- **Timebase:** consume a one-cycle `millisecond_tick` for lease and timeout accounting.
- **Build parameters:** size ports, queues, control tables, arithmetic lanes, result storage, and compiled Kulisch widths.

## Contract behavior

- Keeps packet metadata aligned with the corresponding ready/valid data stream.
- Arbitrates shared control lookup resources across ingress ports.
- Partitions adjacent element ranges across two independent arithmetic banks,
  then merges completed tiles before shared result conversion and storage.
- Applies backpressure through every pipeline boundary instead of dropping an accepted frame.
- Routes CONTROL responses and collective results to per-port packetizers.
- Leaves clock generation, reset synchronization, and shell bus adaptation to the integration wrapper.

## Related modules and concepts

- [`prism_open_nic_250mhz`](../top/prism_open_nic_250mhz.md)
- [`prism_ingress_port`](../ingress/prism_ingress_port.md)
- [`prism_control_executor`](../control/prism_control_executor.md)
- [`prism_range_scheduler`](../collective/prism_range_scheduler.md)
- [Current shared contracts](../common-contracts.md)
