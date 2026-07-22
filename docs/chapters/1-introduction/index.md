# PRISM

PRISM (**Precision-aware Reduction In-Switch Module**) is an open-source RTL research prototype for “in-network collective” (INC) operations on FPGA-based packet-processing datapaths. The project studies how reduction-oriented collective operations, such as `REDUCE_SUM`[^mpi-reduce] aggregation, can be partially offloaded from the host accelerator (CPU/GPU) communication stack into the network data plane itself. In this sense, PRISM is inspired by the same broad direction as Mellanox/NVIDIA SHARP[^sharp], which demonstrated that collective reduction processing can be moved into network switching hardware to reduce communication overhead and improve collective latency.

!!! abstract "Objective"

    PRISM is **not** an attempt to clone SHARP or reproduce a commercial
    InfiniBand/Ethernet switch ASIC. The first prototype studies a narrower
    question: how a backpressurable FPGA datapath can configure and execute
    streaming collective accumulation while making its numerical policy
    explicit.

The datapath exposes a 512-bit AXI-Stream interface. **OpenNIC is the reference
platform for the first prototype**: it provides the FPGA shell in which PRISM is
synthesized and the integration with the NIC, host drivers, and software.

From a numerical perspective, PRISM focuses on reproducible floating-point reductions. Conventional FP32 reductions are sensitive to operand ordering because floating-point addition is not associative; different reduction trees or scheduling orders may produce different bit-level results. PRISM therefore compares the baseline `FP32_ARRIVAL` profile against a Kulisch-style[^kulisch] long-accumulator approach, with the goal of studying the area, latency, throughput, and reproducibility trade-offs of exact or near-exact accumulation in a streaming network datapath.

The current RTL is a two-port `SINGLE` collective node, not a conventional
Layer-2 switch. It implements per-port ingress/egress buffering, frame-level
arbitration, backpressure, CONTROL processing, reduction, bounded result
routing, and result replication. It deliberately omits transparent Ethernet
forwarding, VOQs, a general crossbar, shared packet memory, VLAN/ACL/QoS
processing, and a multi-switch tree datapath.

The latest source code is available from the [PRISM GitHub repository](https://github.com/uniquadev/prism).

## Citation

If you use PRISM in your project, please cite the repository and/or the thesis:

```bibtex
--8<-- "docs/assets/references.bib"
```

## Reading guide

<div class="grid cards" markdown>

-   :material-map-marker-path: **First pass**

    Start with [1.1 Reproducibility](chapters/1-introduction/reproducibility.md), then
    read the [2. Getting Started](chapters/2-getting-started/index.md) overview.

-   :material-chip: **Hardware view**

    Move through [3.1 Protocol](chapters/3-architecture/1.protocol.md) and
    [3.2 Pipeline](chapters/3-architecture/2.pipeline.md).

-   :material-chart-line: **Thesis evidence**

    Track open experiments in [4. Results](chapters/4-results/index.md) and keep the
    writing plan visible in [5. Future Works](chapters/5-future-works/index.md).

</div>


[^mpi-reduce]: MPI Forum, *MPI 4.1 Standard*, `MPI_Reduce`. The standard notes that implementations may change reduction order using associativity/commutativity and that this can change results for floating-point addition. https://www.mpi-forum.org/docs/mpi-4.1/mpi41-report/node130.htm
[^sharp]: Mellanox SHARP: Scalable Hierarchical Aggregation and Reduction Protocol.
[^kulisch]: Kulisch, Ulrich W. "Computer Arithmetic and Validity: Theory, Implementation, and Applications." Walter de Gruyter, 2002.
