# 5.2 Protocol

## Accumulator compression

**Current evidence.** The thesis evaluates adaptive compression in software:
native NumberGroups keep their existing representation, while each Kulisch group
can choose among `RAW`, `RANGE`, `INDEX`, and `MASK`.

**Protocol work.** Keep numerical format and transport encoding separate:

```text
NumberGroup.format   = KULISCH
NumberGroup.encoding = RAW | RANGE | INDEX | MASK
NumberGroup.count    = number of values
```

Define the encoding identifiers, supported combinations, capability negotiation,
and representation of special states. The current wire descriptor and RTL parser
must be updated together; the proposal above is not a claim of current RTL support.

**Hardware work.** Validate and decode incoming compressed groups, then select
encodings and generate compressed RESULT frames. Measure parser, buffering, and
packetizer costs as well as the net bandwidth saving, including descriptors and
padding. Multi-switch evaluation should also measure partial traffic.

The software study is in the repository's
`experiments/04-experiment-exact-accumulator-compression` directory.

## RoCE

RoCE integration would bring PRISM closer to datacenter transport practice.
It requires a transport mapping and compatible host integration, while retaining
the collective's operation identity and numerical policy. The current protocol
uses native Ethernet frames; RoCE remains an extension to develop.

Multi-switch routing and hop-by-hop reliability are covered under
[hardware integration](hardware.md#multi-switch).
