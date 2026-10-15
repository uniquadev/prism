# 3.4 RTL modules

This chapter moves from integration boundaries to the state-owning blocks of
the collective node and its isolated RTL prototypes. Each page explains
responsibility, interfaces, state, and backpressure. A compact header appears
only when the module has a useful initiation interval, a clearly identifiable
registered pipeline, or architecturally significant memory.

`II` means initiation interval and is measured in clock cycles without
backpressure stalls. Pipeline depth counts the registered stages in the named
internal path; it is not an end to end latency for stateful modules. Memory
identifies RTL storage or an explicit memory interface; exact BRAM, LUTRAM, and
URAM utilization depends on parameters, target device, and synthesis results.

The key numeric abstraction is a global element range. DATA and RESULT can use
different NumberGroup and packet boundaries, while accumulation remains independent
of packetization. Read the [chunking model](../1.protocol.md#chunking-model)
before following the collective datapath.

## 3.4.1 Datapath contracts

[Datapath contracts](datapath-contracts.md) defines the transfer, ownership,
identity, and width rules shared by the components below.

## 3.4.2 Components

The pages below cover the modules that own state or define an interface;
small converters, FIFOs, arbiters and table internals are left to the source.

1. [`prism_u280_top`](components/prism_u280_top.md): places the core behind one 100G port of the Alveo U280.
2. [`prism_collective_core`](components/prism_collective_core.md): composes the reusable control and collective paths.
3. [`prism_single_control_plane`](components/prism_single_control_plane.md): validates in-band requests and owns the SINGLE lifecycle.
4. [`prism_single_data_receiver`](components/prism_single_data_receiver.md): validates NumberGroup DATA before issuing arithmetic work.
5. [`prism_single_native_stream_egress`](components/prism_single_native_stream_egress.md): sends native RESULT frames to the installed rank bindings.
6. [`prism_numbergroup_auto_partial_sender`](components/prism_numbergroup_auto_partial_sender.md): exports exact partial tiles as bounded DATA frames in a separate RTL harness.
