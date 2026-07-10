# 1. Introduction

PRISM is a bachelor thesis project on primitive hardware for network
computing. The work explores how a switching datapath can support collective
operations close to the network, reducing host-side coordination and exposing a
small, inspectable hardware interface.

!!! abstract "Thesis"

    **Development of primitive hardware for network computing**  
    Lorenzo Cipolletti, Sapienza University of Rome  
    Supervisor: Salvatore Pontarelli  
    Co-supervisor: Daniele De Sensi

## Reading paths

<div class="grid cards" markdown>

-   :material-map-marker-path: **First pass**

    Start with [2. Getting Started](../2-getting-started/index.md), then
    read the [3. Architecture](../3-architecture/index.md) overview.

-   :material-chip: **Hardware view**

    Move through [3.1 Protocol](../3-architecture/protocol.md),
    [3.2 Pipeline](../3-architecture/pipeline.md), and
    [4.1 Verification Evidence](../4-results/verification.md) pages.

-   :material-chart-line: **Thesis evidence**

    Track open experiments in [4. Results](../4-results/index.md) and keep the
    writing plan visible in [5. Future Works](../5-future-works/index.md).

</div>

## System sketch

```mermaid
flowchart LR
  TG[Traffic generator] --> RX[Ingress parser]
  RX --> OP[Collective operation unit]
  OP --> BUF[Buffering and sequencing]
  BUF --> TX[Egress formatter]
  TX --> TB[Verification testbench]
```

The documentation is intentionally structured like a thesis notebook: each page
records the current model, the expected evidence, and the questions that still
need to be closed by implementation or experiments.

## Repository layout

```text
docs/              MkDocs source, chapters, assets, and draft pages.
repo/rtl/          SystemVerilog RTL and Cocotb/Verilator verification.
repo/traffic-gen/  Synthetic traffic and PCAP generation tools.
```
