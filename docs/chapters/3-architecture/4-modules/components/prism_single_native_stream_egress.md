# `prism_single_native_stream_egress`

`prism_single_native_stream_egress` reads completed SINGLE state, retains
rounded native values and sends NumberGroup RESULT frames to the installed
rank bindings. Fixed Kulisch can select INT8, FP16, BF16 or
FP32 output; the rounded policies select FP32.

## Contracts

- **Arithmetic read port:** reads completed sixteen-lane ranges in vector order.
- **AXI output:** emits one complete frame at a time with its physical egress
  port and logical byte length.

## Contract behavior

- Retains at most 4096 rounded values (16 KiB at FP32 width) so native
  RESULT formats can be packetized at line rate.
- Packs the retained vector into packet-local NumberGroups at the configured
  MTU, without limiting narrower RESULT formats to shorter vectors.
- Reduce sends only to the explicitly installed destination; AllReduce sends
  to the installed result bindings.
- Completes after transmitting to the selected recipients; delivery
  confirmation is outside the SINGLE implementation.

## Related modules and concepts

- [Datapath contracts](../datapath-contracts.md)
