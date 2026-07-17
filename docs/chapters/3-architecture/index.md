# 3. Architecture
> What are the major components, and where should I read next?

<figure markdown="span">
  ![PRISM Switch Architecture Overview](../../assets/images/architecture/overview.png){ loading=lazy }
<figcaption>
<strong>PRISM microarchitecture overview.</strong>
<i>N</i> denotes the number of ingress ports, while <i>K</i> denotes the number of internal packet-injection sources.
</figcaption>
</figure>

Network switches implement the routing, arbitration, and switching functions of
switched-media networks. Switches also implement buffer management mechanisms and,
in the case of lossless networks, the associated flow control.

PRISM extends this conventional switch datapath with support for
**in-network collective reduction**. Ordinary Ethernet frames follow the
transparent Layer-2 forwarding path, whereas locally addressed PRISM packets
may be consumed by the control, aggregation, result-delivery, or progress paths
defined by the protocol.


## Next pages

<div class="grid cards" markdown>

-   :material-map-marker-path: **Introduction**

    Move through [3.1 Protocol](1.protocol.md),
    [3.2 Pipeline](2.pipeline.md) pages.

-   :material-chip: **Modules view**

    Start with [3.5 Interfaces](4-interfaces/index.md), then read the
    [top-level contracts](4-interfaces/top/prism_switch_top.md) before moving
    down through main units and components.

</div>

## Design and implementation status

The documentation uses present tense for normative protocol rules and selected
architecture contracts. That tense does **not** by itself mean that matching RTL
exists.

The [Protocol](1.protocol.md) owns wire meaning and interoperability. The
[Pipeline](2.pipeline.md) and [Interfaces](4-interfaces/index.md) own selected
architecture. [Parameters](4.parameters.md) owns compiled capacities and
feature selection. Measured implementation and verification evidence belongs
only under [Results](../4-results/index.md).
