# Mini-Sharp

This repository contains the source code, documentation, and experiments developed
for a bachelor thesis at Sapienza University of Rome.

**Thesis title:** Development of primitive hardware for network computing

**Student:** Lorenzo Cipolletti  
**Supervisor:** Salvatore Pontarelli  
**Co-supervisor:** Daniele De Sensi  
**University:** Sapienza University of Rome

## Repository layout

```text
docs/              Design notes, protocol description, architecture, verification plan, and results.
repo/rtl/          SystemVerilog RTL and Cocotb/Verilator verification environment.
repo/sim/          C++ simulation models and exploratory network-computing components.
repo/traffic-gen/  Synthetic traffic and PCAP generation tools.
```

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

## License

This project uses separate licenses for hardware design files, software tools,
and documentation. See `LICENSE` and `NOTICE` for details.

## Note
Expect comments to alternate between English and Italian, reflecting the habit of writing design notes in Italian while using English for code and technical terms.