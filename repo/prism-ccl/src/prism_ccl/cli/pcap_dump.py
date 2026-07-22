"""Print one JSON object per PRISM packet in a PCAP or PCAPNG capture."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ..analysis.pcap import (
    capture_summary,
    iter_prism_packets,
    load_operation_contexts,
    packet_record,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--format", choices=("text", "json", "summary"), default="text")
    parser.add_argument("--context", help="JSON operation-context file for numeric decoding")
    parser.add_argument("--port", type=int)
    parser.add_argument("--direction", choices=("rx", "tx"))
    parser.add_argument("--clock-hz", type=int, default=250_000_000)
    args = parser.parse_args()
    inferred = re.search(r"port(\d+)_(rx|tx)", Path(args.capture).name)
    port = args.port if args.port is not None else (int(inferred.group(1)) if inferred else None)
    direction = args.direction or (inferred.group(2) if inferred else None)
    contexts = load_operation_contexts(args.context) if args.context else {}
    packets = list(iter_prism_packets(args.capture, strict=args.strict))
    first_timestamp = packets[0].capture.timestamp_ns if packets else None
    records = [
        packet_record(
            packet,
            port=port,
            direction=direction,
            first_timestamp_ns=first_timestamp,
            clock_hz=args.clock_hz,
            contexts=contexts,
        )
        for packet in packets
    ]
    if args.format == "summary":
        print(json.dumps(capture_summary(records), sort_keys=True))
    elif args.format == "json":
        for record in records:
            print(json.dumps(record, sort_keys=True))
    else:
        for record in records:
            location = (
                "" if record["port"] is None else f" port={record['port']}/{record['direction']}"
            )
            identity = record["header"]
            print(
                f"{record['timestamp_ns']}ns cycle={record['cycle']}{location} "
                f"{record['source']} -> {record['destination']} {record['opcode']} "
                f"payload={record['payload_length']} header={identity}"
            )
            if record["decode_note"]:
                print(f"  note: {record['decode_note']}")
            elif record["decoded_values"] is not None:
                print(f"  values: {record['decoded_values']}")


if __name__ == "__main__":
    main()
