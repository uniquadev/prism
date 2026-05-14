# Traffic Generator

This directory contains the Mini-Sharp traffic generator tools for creating and summarizing Ethernet PCAP traces.

## Requirements

- Python 3.14 or later
- `scapy`

## Installation

From `repo/traffic-gen`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you already have a working Python environment, you can also run the CLI directly with:

```bash
python main.py <command> [options]
```

## Commands

### `pcap-generate`

Generate a PCAP file containing Mini-Sharp reduction packets and optional normal background packets.

Example:

```bash
python main.py pcap-generate --output traces/sample.pcap --reduction-packets 100 --normal-packets 20
```

Common options:

- `--output`: output PCAP file path
- `--manifest`: optional CSV manifest output path
- `--reduction-packets`: number of Mini-Sharp reduction packets
- `--normal-packets`: number of normal background packets
- `--collective-op`: collective operation type
- `--reduce-operation`: reduction operation type
- `--dtype`: payload data type
- `--reduction-payload-size`: reduction payload size in bytes
- `--shuffle / --no-shuffle`: enable or disable packet shuffling
- `--retimestamp-after-shuffle`: rewrite timestamps after shuffle

### `pcap-summary`

Print a short summary of an existing PCAP file.

Example:

```bash
python main.py pcap-summary --input traces/sample.pcap
```

Common options:

- `--input`: input PCAP file path
- `--reduction-etype`: EtherType used for Mini-Sharp reduction packets
- `--normal-etype`: EtherType used for normal packets

## Notes

- The CLI is implemented in `main.py` and `src/cli.py`.
- Packet generation logic is in `src/tools/pcap_generate.py`.
- The summary command is implemented in `src/tools/pcap_summary.py`.
