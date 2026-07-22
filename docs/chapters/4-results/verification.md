# 4.1 Verification evidence

The suite registry is `repo/prism-hdl/verification/suites/__init__.py`.

| Suite | Evidence produced |
|---|---|
| `quality` | RTL lint plus Python format, lint, and type checks |
| `ccl-coverage` | combined CCL unit/integration branch coverage with a 75% regression gate |
| `ccl-unit` | CCL protocol, arithmetic, resource, transport, PCAP, and documentation consistency tests |
| `verification-unit` | Python tests for the RTL/CCL adapter and capture structure |
| `parameters` | full-top elaboration across port, FIFO, context, lane, and Kulisch configurations |
| `rtl-control` | TLV event streaming plus fragmented-control replay, conflict, capacity, timeout, and reset paths |
| `rtl-arbitration` | tile fairness plus CONTROL/RES whole-frame atomicity under stalls |
| `rtl-formats` | FP32 and all typed/Kulisch conversion, selection, saturation, special-value, and finalization boundaries |
| `rtl-backpressure` | skid stability plus elastic/frame FIFO full, simultaneous I/O, error, overflow-drain, and recovery behavior |
| `rtl-pipeline` | FP32_ARRIVAL, FP32_ORDERED, Kulisch saturation, duplicate contribution, and concurrent-range behavior |
| `rtl-throughput` | arithmetic microbenchmark: three-cycle fill and sustained 16-lane FP32 tile per cycle, equivalent to 128 Gbit/s at 250 MHz |
| `wireshark` | tshark execution of the CCL-owned Lua dissector and descriptive fields |
| `ccl-integration` | public communicator lifecycle and warning propagation |
| `rtl-integration` | full two-port CONTROL, REDUCE/ALLREDUCE, routing, packetization, captures, and two-rank result-throughput measurement |

Use `make test` for the complete composition or `make test SUITE=<name>` for a
focused run. `DOCKER=1` selects the reproducible container path without changing
the suite implementation.

The integration capture directory contains `port0_rx.pcap`, `port0_tx.pcap`,
`port1_rx.pcap`, `port1_tx.pcap`, and `all_ports.pcapng`. The aggregate capture
preserves interface identity and deterministic temporal order. These files are
generated from DUT monitor observations, not from expected packet bytes.

No functional simulation result on this page should be interpreted as FPGA
resource utilization, physical timing closure, or a multi-switch tree result.

## Current throughput evidence

The full two-rank FP32_ORDERED scenario reduces 1472 elements into four
full-size result chunks without artificial output stalls. At the 250 MHz target
clock it observes:

- 23 consecutive full 16-lane result tiles at one tile per cycle;
- 128 Gbit/s internal numeric-result rate during that steady burst;
- 109.19 Gbit/s of PRISM result payload at the AXI egress;
- 348 ns from the first accepted contribution beat to the first accepted
  result beat;
- 656 ns from an accepted SESSION_OPEN request to the first response beat.

The 109.19 Gbit/s AXI payload result demonstrates sufficient headroom for a
100 Gbit/s port. The externally useful numeric payload on a physical link is
lower than its nominal line rate once Ethernet framing, inter-packet gap, and
physical-link overhead are included. Vivado timing closure at 250 MHz remains
separate evidence that is not established by Verilator.
