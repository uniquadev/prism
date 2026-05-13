#!/bin/bash
uv run main.py pcap-generate \
  --output traces/mix_reduce_sum_fp32.pcap \
  --manifest traces/mix_reduce_sum_fp32.csv \
  --reduction-packets 8 \
  --normal-packets 2 \
  --expected-contributions 4 \
  --no-shuffle \
  --reduce-operation SUM \
  --collective-op REDUCE \
  --dtype FP32 \
  --vary-sources \
  --source-hosts 4 \
  --seed 42
