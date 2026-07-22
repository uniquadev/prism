# 3. Architecture

The current implementation is a parameterized collective node with two full-duplex 512-bit
AXI4-Stream ports in its default build. It consumes locally addressed PRISM
CONTROL and DATA frames, performs a configured reduction, and generates CONTROL
responses and RES frames. Unsupported or non-local traffic is drained; the RTL
does not provide transparent Layer-2 forwarding.

The ordered RTL inventory is `repo/prism-hdl/rtl.f`. The reusable root is
`prism_collective_core`; `prism_sim_top`, `prism_vivado_top`, and
`prism_open_nic_250mhz` adapt it to verification, standalone Vivado, and the
OpenNIC plugin boundary respectively.

## Next pages

<div class="grid cards" markdown>

-   :material-protocol: **Wire protocol**

    Read [3.1 Protocol](1.protocol.md) for packet layouts, registries, and
    configuration records shared by RTL and the CCL.

-   :material-transit-connection-variant: **Implemented pipeline**

    Follow [3.2 Pipeline](2.pipeline.md) from per-port ingress through control,
    reduction, result storage, and egress.

-   :material-tune-variant: **Configuration**

    Use [3.3 Parameters](4.parameters.md) to distinguish wire constants,
    elaboration parameters, runtime state, and derived values.

-   :material-view-module: **RTL modules**

    Consult [3.4 RTL module inventory](4-interfaces/index.md) for every package,
    synthesizable module, top-level adapter, and verification harness.

</div>

## Implementation boundary

The [Protocol](1.protocol.md) defines the shared wire ABI and explicitly
separates registry assignments from RTL support. [Pipeline](2.pipeline.md),
[Parameters](4.parameters.md), and the [module inventory](4-interfaces/index.md)
describe the implementation present in `repo/prism-hdl`. Verification claims
require a named suite under `repo/prism-hdl/verification` or
`repo/prism-ccl/tests`.
