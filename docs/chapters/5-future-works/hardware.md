# 5.1 Hardware

## Board testing

**Current evidence.** RTL simulation provides functional and numerical checks
and throughput/latency measurements for the tested SINGLE configurations. The
one-port [U280 board build](../2-getting-started/u280.md) meets timing at
250 MHz, its [resources](../4-results/resources.md) are measured after routing,
and a simulation of the whole board top runs reductions from the library driver.

**Implementation.** Bring the 100G link up against a switch or NIC and run the
reductions of `prism-single` on the card.

**Evaluation.** Measure throughput, response time, and power on the board, and
compare them with the RTL simulation.

## Multi-switch

**Current evidence.** The integrated datapath implements the `SINGLE` scenario with directly
attached ranks. Exact partial generation, merge, and the tile-wide `AUTO` partial
sender have separate RTL verification.

**Implementation.** Integrate those blocks for multi-switch scenarios and add:

- forwarding and routing of partial sums and results;
- hop-by-hop reliability;
- safe draining of in-flight traffic during cancellation;
- virtual output queues and a crossbar for a general forwarding fabric.

**Evaluation.** Verify the complete collective across switches, including
backpressure, completion, and cancellation. Measure partial traffic and
end-to-end performance for different tree configurations.

The [architecture documentation](../3-architecture/2.pipeline.md) identifies
the implemented path and the forwarding resources that remain to be added.
