# `prism_switch_top`

**Module class:** `TOP LEVEL`  

`prism_switch_top` is the OpenNIC `box_322mhz` integration boundary. It adapts
the shell's non-backpressurable receive ports into buffered internal streams,
synchronizes configuration traffic, and keeps every shell-specific signal out
of [`prism_switch_core`](prism_switch_core.md).

## Contracts

- **Datapath clock/reset — input, 322.265625 MHz + 1 bit:** `axis_aclk` drives
  all packet logic. `axis_rst_n` is active low; deassertion is synchronized
  before reaching the core.

- **OpenNIC RX ports — input, 2 × 579 forward bits:** each port provides
  `tdata[511:0]`, `tkeep[63:0]`, `tvalid`, `tlast`, and `tuser_err`. The shell
  supplies no usable RX `tready`, so the wrapper must accept every presented
  beat and convert overflow into a counted whole-packet drop.

- **OpenNIC TX ports — output, 2 × 579 forward bits + 2 ready bits:** each port
  drives the same 512/64 packet signals and receives one `tready`. After the
  first accepted beat, `tvalid` remains asserted through `tlast`; stalled beats
  remain stable.

- **Core RX streams — output, 2 × `prism_axis`:** two independently buffered
  512-bit ready/valid packet streams. The adapter may backpressure the core but
  never the physical RX producer.

- **Core TX streams — input, 2 × `prism_axis`:** shell-independent output
  streams from the core. The wrapper passes backpressure from the corresponding
  OpenNIC TX port without changing packet data.

- **Configuration clock/reset — input, 125 MHz + 1 bit:** the OpenNIC register
  clock and active-low reset form a separate domain from the datapath.

- **AXI4-Lite slave — input/output, 32-bit address and 32-bit data:** shell
  register requests are serialized into the 72-bit internal configuration
  request and returned as the 40-bit response. `WSTRB[3:0]` maps directly to
  four byte enables; there is no implicit 64-bit access. The CDC bridge completes or
  fails one transaction exactly once.

- **Health status — output, 64 bits:** sticky reset, RX overflow, malformed
  shell beat, configuration CDC, and fatal-core indicators. Individual event
  counts remain readable through the configuration interface.

## Contract behavior

- RX `tkeep` must be all ones before the final beat and contiguous from bit zero
  on the final beat. A violation marks the packet bad and drains it through
  `tlast`.
- The wrapper must provide at least 48 beats of staging per physical ingress,
  twice the v1 24-beat maximum frame size.
- Before a physical first beat can arrive, the wrapper keeps one 24-beat staging
  reservation armed per ingress and prepares the next reservation as capacity
  returns. If no reservation is armed, it drains and counts the entire arriving
  packet rather than performing an untracked partial write.
- No packet, context, or counter crosses clock domains as an unqualified bundle;
  configuration requests use an acknowledged CDC channel.
- A 64-bit counter or state value occupies two explicitly addressed 32-bit
  words. The eventual register map must define a snapshot/latch operation for
  values that require an atomic read; ordinary low/high word accesses are not
  silently made atomic.

## Related modules and concepts

The wrapper contains the first [`prism_packet_fifo`](../components/stream/prism_packet_fifo.md)
stage and instantiates [`prism_switch_core`](prism_switch_core.md). The shell
signal semantics follow the
[AMD OpenNIC 322 MHz interface](https://github.com/Xilinx/open-nic-shell#shell-interface).
