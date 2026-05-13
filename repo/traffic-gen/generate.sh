#!/bin/bash
uv run main.py pcap-generate \
  --output traces/mix_reduce_sum.pcap \
  --manifest traces/mix_reduce_sum.csv \
  --reduction-packets 64 \
  --normal-packets 16 \
  --expected-contributions 4 \
  --no-shuffle \
  --reduce-operation SUM \
  --collective-op REDUCE \
  --dtype INT8 \
  --vary-sources \
  --source-hosts 8 \
  --retimestamp-after-shuffle \
  --seed 42
