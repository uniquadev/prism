# 2. Getting Started
TODO
## Current status

The current prototype validates an end-to-end reduction flow:

```text
traffic generator -> PCAP input -> RTL simulation -> PCAP output -> Cocotb checks
```

The verified RTL path currently supports `REDUCE/SUM/INT8` with FP32 intermediate
accumulation inside the collective engine.

## Quick start

```bash
cd repo/rtl
make tests
# or for a specific pcap
make run_pcap path/to/pcap
```

Generated PCAP files are written under:

```text
repo/rtl/verification/traces/
# or for specific pcap if no output path is specified
repo/rtl/out.pcap
```
