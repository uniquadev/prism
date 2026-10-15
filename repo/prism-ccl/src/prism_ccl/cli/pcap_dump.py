"""Inspect canonical PRISM Ethernet PCAP frames, one JSON record per frame."""

from __future__ import annotations

import argparse
import json

from ..analysis import inspect_frame, read_pcap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="classic Ethernet PCAP")
    parser.add_argument("--mtu", type=int, default=1500)
    parser.add_argument("--kulisch-bits", type=int, default=279)
    args = parser.parse_args()
    for timestamp_us, frame in read_pcap(args.capture):
        record = inspect_frame(frame, mtu=args.mtu, kulisch_bits=args.kulisch_bits)
        print(json.dumps({"simulated_timestamp_us": timestamp_us, **record}, sort_keys=True))


if __name__ == "__main__":
    main()
