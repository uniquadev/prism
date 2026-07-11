# PRISM

PRISM (**Precision-aware Reduction In-Switch Module**) is an open-source RTL research prototype for “in-network collective” (INC) operations on FPGA-based packet-processing datapaths. The project studies how reduction-oriented collective operations, such as `REDUCE_SUM`[^mpi-reduce] aggregation, can be partially offloaded from the host accelerator (CPU/GPU) communication stack into the network data plane itself. In this sense, PRISM is inspired by the same broad direction as Mellanox/NVIDIA SHARP[^sharp], which demonstrated that collective reduction processing can be moved into network switching hardware to reduce communication overhead and improve collective latency.

!!! abstract "Objective"

    PRISM is **not** an attempt to clone SHARP, nor does it aim to reproduce the full functionality of a commercial InfiniBand or Ethernet switch ASIC. Instead, it is a compact and inspectable hardware research vehicle for studying the microarchitecture of INC primitives under FPGA constraints. The core question is narrower and more experimental: **how can a switch-like RTL datapath support line-rate packet forwarding and streaming collective accumulation while also improving floating-point reproducibility?**

The datapath exposes a 512-bit AXI-Stream interface. **OpenNIC is the reference
platform for the first prototype**: it provides the FPGA shell in which PRISM is
synthesized and the integration with the NIC, host drivers, and software.

From a numerical perspective, PRISM focuses on reproducible floating-point reductions. Conventional FP32 reductions are sensitive to operand ordering because floating-point addition is not associative; different reduction trees or scheduling orders may produce different bit-level results. PRISM therefore compares a baseline FP32 accumulation path against a Kulisch-style[^kulisch] long-accumulator approach, with the goal of studying the area, latency, throughput, and reproducibility trade-offs of exact or near-exact accumulation in a streaming network datapath.

From a switching perspective, PRISM implements a **switch-inspired data-plane skeleton** rather than a complete production switch. It includes mechanisms commonly found in high-performance packet switches, such as per-output arbitration, VOQ-style buffering, shared-memory packet storage, backpressure propagation, and packet-level scheduling. However, advanced features such as VLAN processing, ACLs, multicast replication engines, QoS hierarchies, credit-based congestion control, ECN/PFC, telemetry, fault isolation, and production-grade buffer management are intentionally outside the initial scope.

The latest source code is available from the [PRISM GitHub repository](https://github.com/uniquadev/prism).

## Citation

If you use PRISM in your project, please cite the repository and/or the thesis:

```bibtex
--8<-- "docs/assets/references.bib"
```

## Reading guide

<div class="grid cards" markdown>

-   :material-map-marker-path: **First pass**

    Start with [1.2 Reproducibility](chapters/1-introduction/reproducibility.md), then
    read the [2. Getting Started](chapters/2-getting-started/index.md) overview.

-   :material-chip: **Hardware view**

    Move through [3.1 Protocol](chapters/3-architecture/protocol.md),
    [3.2 Pipeline](chapters/3-architecture/pipeline.md) pages.

-   :material-chart-line: **Thesis evidence**

    Track open experiments in [4. Results](chapters/4-results/index.md) and keep the
    writing plan visible in [5. Future Works](chapters/5-future-works/index.md).

</div>


[^mpi-reduce]: MPI Forum, *MPI 4.1 Standard*, `MPI_Reduce`. The standard notes that implementations may change reduction order using associativity/commutativity and that this can change results for floating-point addition. https://www.mpi-forum.org/docs/mpi-4.1/mpi41-report/node130.htm
[^sharp]: Mellanox SHARP: Scalable Hierarchical Aggregation and Reduction Protocol.
[^kulisch]: Kulisch, Ulrich W. "Computer Arithmetic and Validity: Theory, Implementation, and Applications." Walter de Gruyter, 2002.
