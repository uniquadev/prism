# `prism_switch_top`

**Module class:** `TOP LEVEL`  

`prism_switch_top` is the OpenNIC `box_250mhz` integration boundary. It adapts
the shell's packet streams and metadata into the internal PRISM stream,
synchronizes configuration traffic, and keeps every shell-specific signal out
of [`prism_switch_core`](prism_switch_core.md).

## Contracts

- **Datapath clock/reset — input, 250 MHz + 1 bit:** `axis_aclk` drives
  all packet logic. `axis_rst_n` is active low; deassertion is synchronized
  before reaching the core.

- **OpenNIC RX ports — input/output, 2 × 250 MHz AXI4-Stream:** each port
  provides `tdata[511:0]`, `tkeep[63:0]`, `tvalid`, `tlast`, 16-bit
  `tuser_size`, `tuser_src`, and `tuser_dst`, plus shell-defined `tuser_user`.
  The wrapper supplies usable `tready` and validates size/keep consistency.

- **OpenNIC TX ports — output/input, 2 × 250 MHz AXI4-Stream:** each port drives
  the same packet signals and exact `tuser_size`, supplies source/destination
  metadata, and receives one `tready`. Stalled beats remain stable.

- **Core RX streams — output, 2 × `prism_axis`:** two independent 512-bit
  ready/valid packet streams. Backpressure propagates through the wrapper to
  the shell packet adapter.

- **Core TX streams — input, 2 × `prism_axis`:** shell-independent output
  streams from the core. The wrapper passes backpressure from the corresponding
  OpenNIC TX port without changing packet data.

- **Configuration clock/reset — input, 125 MHz + 1 bit:** the OpenNIC register
  clock and active-low reset form a separate domain from the datapath.

- **AXI4-Lite slave — input/output, 32-bit address and 32-bit data:** OpenNIC's
  box register interface has no `WSTRB`, so each accepted write becomes one
  full-word internal request with all four byte enables asserted. Responses use
  the 40-bit normalized return path; there is no implicit 64-bit access.

- **Health status — output, 64 bits:** sticky reset, malformed shell metadata,
  configuration-path, and fatal-core indicators. Individual event counts
  remain readable through the configuration interface.

## Contract behavior

- RX `tkeep` must be all ones before the final beat and contiguous from bit zero
  on the final beat. A violation marks the packet bad and drains it through
  `tlast`.
- RX `tuser_size` remains stable for the packet and agrees with the final
  `tkeep`; malformed metadata selects a whole-packet drop.
- No packet, context, or counter crosses clock domains as an unqualified bundle;
  configuration requests use an acknowledged CDC channel.
- A 64-bit counter or state value occupies two explicitly addressed 32-bit
  words. The eventual register map must define a snapshot/latch operation for
  values that require an atomic read; ordinary low/high word accesses are not
  silently made atomic.

## Related modules and concepts

The wrapper adapts the shell streams and instantiates
[`prism_switch_core`](prism_switch_core.md). The signal semantics follow the
[AMD OpenNIC 250 MHz interface](https://github.com/Xilinx/open-nic-shell#shell-interface).
