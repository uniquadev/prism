import argparse
from collections import Counter

from scapy.all import Ether, rdpcap

from traffic_types import DEFAULT_NORMAL_ETYPE, DEFAULT_REDUCTION_ETYPE, parse_int_auto
from utils import require_scapy


class PCAPSummarizer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        require_scapy()

    def summarize(self) -> None:
        packets = rdpcap(self.args.input)
        ether_type_counts = Counter()
        reduction_count = 0
        normal_count = 0

        for pkt in packets:
            if Ether in pkt:
                etype = int(pkt[Ether].type)
                ether_type_counts[etype] += 1
                if etype == self.args.reduction_etype:
                    reduction_count += 1
                if etype == self.args.normal_etype:
                    normal_count += 1

        print("PCAP summary")
        print(f"  input:                   {self.args.input}")
        print(f"  packets total:           {len(packets)}")
        print(f"  reduction EtherType:     0x{self.args.reduction_etype:04x}")
        print(f"  normal EtherType:        0x{self.args.normal_etype:04x}")
        print(f"  reduction packets:       {reduction_count}")
        print(f"  normal packets:          {normal_count}")
        print("  EtherType histogram:")
        for etype, count in sorted(ether_type_counts.items()):
            print(f"    0x{etype:04x}: {count}")


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "pcap-summary",
        help="Print a short PCAP summary.",
    )

    parser.add_argument("--input", required=True, help="Input PCAP file path.")
    parser.add_argument(
        "--reduction-etype",
        type=parse_int_auto,
        default=DEFAULT_REDUCTION_ETYPE,
        help="EtherType used for Mini-Sharp reduction packets.",
    )
    parser.add_argument(
        "--normal-etype",
        type=parse_int_auto,
        default=DEFAULT_NORMAL_ETYPE,
        help="EtherType used for normal packets.",
    )
    parser.set_defaults(func=lambda args: PCAPSummarizer(args).summarize())
