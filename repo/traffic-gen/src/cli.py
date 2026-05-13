import argparse
import sys

from tools.pcap_generate import add_parser as add_generate_parser
from tools.pcap_summary import add_parser as add_summary_parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mini-Sharp traffic generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(title="commands", dest="command", required=True)
    add_generate_parser(subparsers)
    add_summary_parser(subparsers)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "reduction_packets") and args.reduction_packets < 0:
        raise ValueError("--reduction-packets must be non-negative")
    if hasattr(args, "normal_packets") and args.normal_packets < 0:
        raise ValueError("--normal-packets must be non-negative")
    if hasattr(args, "expected_contributions") and args.expected_contributions <= 0:
        raise ValueError("--expected-contributions must be positive")
    if hasattr(args, "source_hosts") and args.source_hosts <= 0:
        raise ValueError("--source-hosts must be positive")
    if hasattr(args, "destination_hosts") and args.destination_hosts <= 0:
        raise ValueError("--destination-hosts must be positive")
    if hasattr(args, "inter_packet_gap") and args.inter_packet_gap < 0:
        raise ValueError("--inter-packet-gap must be non-negative")
    if hasattr(args, "reduction_payload_size") and args.reduction_payload_size < 0:
        raise ValueError("--reduction-payload-size must be non-negative")
    if hasattr(args, "normal_payload_size") and args.normal_payload_size < 0:
        raise ValueError("--normal-payload-size must be non-negative")
    if hasattr(args, "chunk_id_start") and args.chunk_id_start < 0:
        raise ValueError("--chunk-id-start must be non-negative")


def run() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        validate_args(args)
        args.func(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
