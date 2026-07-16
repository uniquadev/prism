# 3.2 Pipeline


Functional stages may be combined or subdivided after timing analysis; the
table does not freeze a one-cycle latency per row. The next
[Parameters](4.parameters.md) section will define widths, depths, lane counts,
cut-through lead, and timer implementation.

The RTL and reference model must preserve these invariants:

- the 322 MHz ingress consumes every physical packet through `TLAST`, including
  packets selected for drop;
- no packet drains from ingress staging without a successful full-packet
  reservation or an explicit drop decision;
- ownership is resolved before opcode semantics mutate local state;
- every beat follows the packet context created by its first beat;
- a packet-level crossbar grant remains locked through the accepted `TLAST`, and
  TX never bubbles after asserting a packet's first `TVALID`;
- every ingress has independent staging and local packet storage;
- every logical queue preserves packet boundaries;
- local DATA and RES become ACK-eligible only after complete error-free storage;
- duplicates are ACKed when safe but never accumulated or replicated twice;
- deterministic FP32 seeds from Contributor 0 and folds in ascending local
  Contributor ID;
- replay state is released only by valid hop-local feedback, abort, or release;
- arithmetic completion, output acknowledgment, and operation completion remain
  distinct states;
- CONTROL state changes are atomic with respect to complete transactions.