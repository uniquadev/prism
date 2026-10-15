# 3. Architecture

<figure id="fig-architecture-overview" class="architecture-figure" markdown="span">
  ![SINGLE-node frame routing and collective processing paths](../../assets/images/architecture/architecture-switch-en.svg){ loading=lazy }
  <figcaption>
  <strong>SINGLE-node architecture.</strong>
  Frame classification separates CONTROL and collective DATA processing.
  The dashed forwarding branch is a future extension.
  </figcaption>
</figure>

Network switches combine routing, arbitration, buffering, switching, and flow
control. PRISM's target architecture extends that datapath with in-network collective reduction:
ordinary frames follow the forwarding path, while locally addressed PRISM
frames enter control, aggregation, result, or progress handling.

The [architecture overview](#fig-architecture-overview) shows frame classification,
CONTROL processing, and the collective path. Transparent forwarding, VOQs, and a general
crossbar remain future extensions.

The current implementation is a collective node with `NUM_PORTS` full-duplex
512-bit AXI4-Stream ports: two by default, one in the U280 board build. It consumes locally addressed PRISM
CONTROL and DATA frames, performs a configured reduction, and generates CONTROL
responses and RES frames. Unsupported or non-local traffic is drained; the RTL
does not provide transparent Layer-2 forwarding.

The ordered RTL inventory is `repo/prism-hdl/rtl.f`. The reusable root is
`prism_collective_core`; `prism_sim_top` adapts it to verification and
`prism_u280_top` to the 100G port of the Alveo U280.

## Next pages

- [3.1 Protocol](1.protocol.md): packet layouts, registries and configuration
  records shared by the RTL and the CCL.
- [3.2 Pipeline](2.pipeline.md): the path from per-port ingress through
  control, reduction and result storage to egress.
- [3.3 Parameters](4.parameters.md): wire constants, elaboration parameters,
  runtime state and derived values.
- [3.4 RTL modules](4-modules/index.md): the state-owning modules and the
  board top.

The protocol defines the wire format and the target behaviour; the pipeline
page separates that target from what the RTL implements today.
