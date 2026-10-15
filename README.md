# PRISM

This repository contains the source code, documentation, and experiments developed
for a bachelor thesis at Sapienza University of Rome.

**Thesis title:** Development of primitive hardware for network computing

**Student:** Lorenzo Cipolletti  
**Supervisor:** Salvatore Pontarelli  
**Co-supervisor:** Daniele De Sensi  
**University:** Sapienza University of Rome

## Repository layout

```text
docs/              MkDocs source: chapters, assets, and the site home page.
repo/prism-hdl/    SystemVerilog RTL, the Alveo U280 board build, and the Cocotb/Verilator verification.
repo/prism-ccl/    Protocol library, collective API, host tools, PCAP tools, and Wireshark dissector.
experiments/       Independently locked Python experiments.
experiments/run/   Launcher and shared build/provenance utilities.
```

## Getting started

Run `make help` from the repository root to list the public commands. Docker is
the recommended verification path because it supplies Python, Verilator,
Cocotb, and tshark:

```bash
make test DOCKER=1
```

Useful variants are:

```bash
make env DOCKER=1
make build DOCKER=1
make test SUITE=rtl-formats DOCKER=1
make test XML=1 DOCKER=1
```

`XML=1` keeps the test reports under `build/cache/rtl-simulation/results/`.
Remove `DOCKER=1` to use tools installed locally. The
[getting-started guide](docs/chapters/2-getting-started/index.md) also covers
Windows without Make.

## Alveo U280

```bash
make u280
```

builds the bitstream for one 100G port of an Alveo U280 with Vivado 2022.1.
Simulating the board, loading the bitstream and running a reduction from a
host are described in [2.3 Alveo U280](docs/chapters/2-getting-started/u280.md).

## Experiments

Run these commands from the repository root:

```bash
make experiments
make experiment EXP=01-experiment-single-reduce ARGS="all --seed 7"
make experiment EXP=01-experiment-single-reduce DOCKER=1 ARGS="collect --collective allreduce"
make experiment EXP=01-experiment-single-reduce ARGS="plot --input build/experiments/01-experiment-single-reduce/RUN"
```

Local execution requires **uv**; it provisions Python and the project's locked
dependencies. The Docker Make path requires Make and Docker, **not host Python
or uv**. It uses the same project lockfile in a separate container environment.
Without Make, PowerShell can use uv:

```powershell
uv run --python 3.13 experiments/run/launch.py list
uv run --python 3.13 experiments/run/launch.py run 01-experiment-single-reduce -- all --seed 7
```

## Documentation

You can preview the documentation locally with:

```bash
make docs-serve
```

## License

PRISM is released under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE).
