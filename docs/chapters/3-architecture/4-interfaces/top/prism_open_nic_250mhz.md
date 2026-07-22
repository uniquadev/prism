# `prism_open_nic_250mhz`

**Module class:** production integration boundary

`prism_open_nic_250mhz` adapts the reusable PRISM core to the OpenNIC 250 MHz
plugin interface. It keeps shell-specific clocks, resets, and flattened buses
outside the protocol core.

## Contracts

- **Network receive AXI streams:** accept one Ethernet stream per enabled OpenNIC interface.
- **Network transmit AXI streams:** return CONTROL and RES frames to the corresponding adapter interface.
- **AXI-Lite windows:** terminate the shell management windows through the current identity-register endpoint.
- **QDMA streams:** explicitly terminate host DMA paths because the current datapath uses the network interfaces.
- **Reset and clocks:** synchronize the module reset into the AXI and AXI-Lite domains and assert `mod_rst_done` only after both are released.

## Contract behavior

- Supports one or two network interfaces with 512-bit AXI streams.
- Derives one local MAC address per interface from `LOCAL_MAC_BASE`.
- Generates the millisecond tick consumed by control-plane leases.
- Preserves AXI backpressure between each adapter stream and the core.
- Does not implement collective behavior; that remains inside `prism_collective_core`.

## Related modules and concepts

- [`prism_collective_core`](../core/prism_collective_core.md)
- [Current shared contracts](../common-contracts.md)
- [Pipeline](../../2.pipeline.md)

