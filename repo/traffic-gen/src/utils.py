import os
import sys

from scapy.all import Raw, wrpcap, rdpcap
from scapy.layers.l2 import Ether


def require_scapy() -> None:
    if Ether is None or Raw is None or wrpcap is None or rdpcap is None:
        print(
            "ERROR: Scapy is required for PCAP generation and reading.\n\n"
            "Install it with:\n\n"
            "  pip install scapy\n",
            file=sys.stderr,
        )
        sys.exit(1)


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def check_output_path(path: str, overwrite: bool) -> None:
    ensure_parent_dir(path)

    if os.path.exists(path) and not overwrite:
        print(
            f"ERROR: output file already exists and overwrite is disabled: {path}\n"
            "Use --overwrite or remove the file.",
            file=sys.stderr,
        )
        sys.exit(1)
