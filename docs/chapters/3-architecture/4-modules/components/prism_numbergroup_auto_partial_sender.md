# `prism_numbergroup_auto_partial_sender`

`prism_numbergroup_auto_partial_sender` exports exact or already-rounded FP32
partial tiles as DATA.
It is verified in a dedicated RTL harness; SINGLE does not connect switches
into a reduction tree.

## Contracts

- **Input:** ordered exact or FP32 tiles with global first positions. The
  throughput configuration defaults to 128 lanes; separate diagnostic
  harnesses exercise 16 and 64 lanes.
- **Output:** MTU-bounded DATA frames containing consecutive, homogeneous
  NumberGroups. Each value uses a concrete format selected without rounding.

## Datapath

Parallel classifiers select INT8, FP16, BF16, FP32, or Kulisch per value.
FP32 input is classified after its arithmetic rounding; AUTO never restores
precision lost by that policy.
When descriptor and padding cost is lower, adjacent FP32-representable values
are sent as a single FP32 group. Equal adjacent groups also merge across
tile boundaries within a packet, unless the earlier group ends with padding.
A segment scheduler cuts each tile into segments of whole values that fit the
negotiated MTU. Kulisch values travel on the sixteen low lanes of a segment,
so a segment also ends before the first Kulisch value that lies sixteen or
more lanes after its start; the lanes above the sixteenth are native. A tile
of narrow values with a few Kulisch values is at most four segments. A
two-bank store writes and transmits 512-bit AXI beats under backpressure.
If an exact Kulisch value cannot fit the operation's configured wire width,
the sender finishes any frame already on AXI and emits a terminal DATA frame
with `ACCUMULATION_INEXACT`. It never truncates that value.

Measured in RTL simulation at 250 MHz on 4096 elements:

- the 128-lane configuration keeps the whole window from first input to last
  output above 100 Gbit/s for each uniform native format;
- the 16-lane diagnostic reaches 107.79 Gbit/s of payload on FP32 and is
  bounded to 32 and 64 Gbit/s on INT8 and FP16/BF16 input;
- fed by an eight-stripe exact-bank producer, the sender emits 126.33 Gbit/s
  of AXI frames for alternating FP32 and Kulisch values, and more than
  100 Gbit/s of payload for uniform INT8, FP16, BF16, FP32 and Kulisch.

These are interface rates in simulation, not an integrated multi-switch
result.

## Related modules and concepts

- [Protocol chunking](../../1.protocol.md#chunking-model)
- [Datapath contracts](../datapath-contracts.md)
