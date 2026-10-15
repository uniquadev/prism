---
title: PRISM
---

# ![PRISM](assets/images/prism_logo.png){ .prism-logo .off-glb width="260" height="58" } {#prism .prism-title}

PRISM (**Precision-aware Reduction In-Switch Module**) is an open-source RTL research prototype for “in-network collective” (INC) operations on FPGA-based packet-processing datapaths. The project studies how reduction-oriented collective operations, such as `REDUCE_SUM`[^mpi-reduce] aggregation, can be partially offloaded from the host accelerator (CPU/GPU) communication stack into the network data plane itself with concern to reproducibility. In this sense, PRISM is inspired by the same broad direction as Mellanox/NVIDIA SHARP[^sharp], which demonstrated that collective reduction processing can be moved into network switching hardware to reduce communication overhead and improve collective latency.

!!! abstract "Objective"

    PRISM is **not** an attempt to clone SHARP or reproduce a commercial
    InfiniBand/Ethernet switch ASIC. It is an inspectable FPGA research vehicle
    for one question: **how can a switch-like datapath combine line-rate packet
    forwarding, streaming collective accumulation, and reproducible
    floating-point arithmetic?**

The datapath exposes a 512-bit AXI-Stream interface. The hardware target is the
AMD Alveo U280: the [board build](chapters/2-getting-started/u280.md) connects the
core to one 100G port through the CMAC subsystem and the packet adapter of the
OpenNIC shell, without a host interface. Hosts take part only over Ethernet.

From a numerical perspective, PRISM focuses on reproducible floating-point reductions. Conventional FP32 reductions are sensitive to operand ordering because floating-point addition is not associative; different reduction trees or scheduling orders may produce different bit-level results. PRISM therefore compares the baseline `FP32_ARRIVAL` profile against a Kulisch-style[^kulisch] long-accumulator approach, with the goal of studying the area, latency, throughput, and reproducibility trade-offs of exact or near-exact accumulation in a streaming network datapath.

The [target architecture](chapters/3-architecture/index.md) is a reusable,
port-parameterized collective core. It implements buffering, backpressure,
CONTROL, reduction, result routing, and replication; `prism_u280_top`
connects the same RTL to the 100G port of the board. Forwarding, VOQs,
a general crossbar, and multi-switch aggregation remain later integration work.

The latest source code is available from the [PRISM GitHub repository](https://github.com/uniquadev/prism).

## Citation

If you use PRISM in your project, please cite the repository and/or the thesis:

```bibtex
--8<-- "docs/assets/references.bib"
```

## Reading guide

[1.1 Reproducibility](chapters/1-introduction/reproducibility.md) gives the
motivation, [2. Getting Started](chapters/2-getting-started/index.md) runs the
tests, the experiments and the board, [3.1 Protocol](chapters/3-architecture/1.protocol.md)
and [3.2 Pipeline](chapters/3-architecture/2.pipeline.md) describe the hardware, and
[4. Results](chapters/4-results/index.md) holds the measurements.


[^mpi-reduce]: MPI Forum, *MPI 4.1 Standard*, `MPI_Reduce`. The standard notes that implementations may change reduction order using associativity/commutativity and that this can change results for floating-point addition. https://www.mpi-forum.org/docs/mpi-4.1/mpi41-report/node130.htm
[^sharp]: Mellanox SHARP: Scalable Hierarchical Aggregation and Reduction Protocol.
[^kulisch]: Kulisch, Ulrich W. "Computer Arithmetic and Validity: Theory, Implementation, and Applications." Walter de Gruyter, 2002.
