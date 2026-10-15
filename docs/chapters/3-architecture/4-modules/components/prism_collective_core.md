# `prism_collective_core`

`prism_collective_core` is the production-independent composition boundary. It
classifies physical-port frames and connects the SINGLE control, reduction and
result paths without embedding an FPGA-shell interface.

## Contracts

- **Per-port ingress AXI streams:** accept complete Ethernet frames from the deployment adapter.
- **Per-port egress AXI streams:** publish complete CONTROL or RESULT frames and their logical byte lengths.
- **Local configuration:** receive the local MAC vector and the laboratory-extension enable bit.
- **Timebase:** expose `millisecond_tick` at the wrapper boundary; this SINGLE
  implementation does not yet use it for lease accounting.
- **Build parameters:** select one to eight 512-bit physical ports and the link MTU
  (see [3.3 Parameters](../../4.parameters.md)); the tests run one and two ports.

## Contract behavior

- Routes admitted CONTROL to the lifecycle engine, and DATA from
  all configured ports to the active SINGLE context.
- Keeps logical endpoint identity separate from physical ingress port, so
  multiple rank bindings can share one port when configured explicitly.
- Locks one egress frame through `tlast` while multiplexing control responses
  and results under backpressure.
- Does not forward arbitrary Ethernet traffic or implement an INTERNAL node.
- Leaves clock generation, reset synchronization, and shell bus adaptation to the integration wrapper.

## Related modules and concepts

- [`prism_u280_top`](prism_u280_top.md)
- [`prism_single_control_plane`](prism_single_control_plane.md)
- [`prism_single_data_receiver`](prism_single_data_receiver.md)
- [`prism_single_native_stream_egress`](prism_single_native_stream_egress.md)
- [Datapath contracts](../datapath-contracts.md)
