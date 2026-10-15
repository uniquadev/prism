"""Capture I/O is an outer adapter, never a domain dependency."""

from .pcap import inspect_frame, read_pcap, write_pcap

__all__ = ["inspect_frame", "read_pcap", "write_pcap"]
