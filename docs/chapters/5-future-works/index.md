# 5. Future work

The current implementation intentionally stops at a two-port `SINGLE` node. The next work
items follow directly from gaps that can be observed in the implementation:

- implement and verify a multi-switch LEAF/INTERNAL/ROOT datapath, including
  switch-originated partial DATA;
- freeze a lossless partial format before claiming tree-wide Kulisch exactness;
- implement PROGRESS, acknowledgements, replay, retry, and bounded recovery in
  RTL if hop reliability is required;
- add focused unit tests for state-owning control tables, result storage,
  routing, packetization, and wrapper reset behavior;
- synthesize/place/route the selected OpenNIC profile and report utilization,
  critical paths, timing, latency, and sustained payload throughput;
- explore additional operators or collectives only after defining their
  arithmetic, state, and wire compatibility precisely.

Transparent Layer-2 forwarding, VOQs, a general crossbar, and shared packet
memory are not incomplete requirements of the current collective node. Adding them
would be a separate scope decision and architecture.
