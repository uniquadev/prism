import argparse
import csv
import random
import struct
from typing import List, Tuple

from scapy.all import Ether, Raw, wrpcap

from models import PacketRecord
from traffic_types import (
    CollectiveOp,
    DEFAULT_DST_MAC,
    DEFAULT_DST_MAC_PREFIX,
    DEFAULT_NORMAL_ETYPE,
    DEFAULT_REDUCTION_ETYPE,
    DEFAULT_SRC_MAC,
    DEFAULT_SRC_MAC_PREFIX,
    PayloadDataType,
    PacketType,
    ReduceOperation,
    enum_from_string,
    enum_name,
    mac_for_host,
    parse_int_auto,
)
from utils import check_output_path, require_scapy


class PCAPGenerator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        require_scapy()
        check_output_path(args.output, overwrite=args.overwrite)
        if args.manifest:
            check_output_path(args.manifest, overwrite=args.overwrite)

    def generate(self) -> None:
        packets, records = self._build_packets()
        wrpcap(self.args.output, packets)

        if self.args.manifest:
            self._write_manifest(self.args.manifest, records)

        self._print_summary(records)

    def _build_packets(self) -> Tuple[List[Ether], List[PacketRecord]]:
        packets = []
        records: List[PacketRecord] = []
        rng = random.Random(self.args.seed)
        packet_index = 0

        for i in range(self.args.reduction_packets):
            group_id = i // self.args.expected_contributions
            operation_id = self.args.reduce_operation
            chunk_id = self.args.chunk_id_start + group_id
            flow_id = self.args.flow_id_start + group_id
            op_flags = int(operation_id) & 0xFF
            contribution_index = i % self.args.expected_contributions
            src_mac = self._choose_src_mac(i)
            dst_mac = self._choose_dst_mac(i)

            payload = self._build_reduction_packet_payload(
                flow_id=flow_id,
                op_flags=op_flags,
                chunk_id=chunk_id,
                p_size=self.args.reduction_payload_size,
                collective_op=self.args.collective_op,
                collective_flags=self.args.collective_flags,
                dtype=self.args.dtype,
                expected_contributions=self.args.expected_contributions,
                contribution_index=contribution_index,
                payload_size=self.args.reduction_payload_size,
                value=self.args.value_start + i,
            )

            pkt = Ether(src=src_mac, dst=dst_mac, type=self.args.reduction_etype) / Raw(payload)
            pkt.time = self.args.start_time + packet_index * self.args.inter_packet_gap

            packets.append(pkt)
            records.append(
                PacketRecord(
                    index=packet_index,
                    packet_type=PacketType.REDUCTION,
                    timestamp=float(pkt.time),
                    src_mac=src_mac,
                    dst_mac=dst_mac,
                    ether_type=self.args.reduction_etype,
                    op_flags=operation_id,
                    flow_id=flow_id,
                    chunk_id=chunk_id,
                    collective_op=self.args.collective_op,
                    data_type=self.args.dtype,
                    expected_contributions=self.args.expected_contributions,
                    contribution_index=contribution_index,
                    payload_len=len(payload),
                )
            )
            packet_index += 1

        for i in range(self.args.normal_packets):
            global_index = self.args.reduction_packets + i
            src_mac = self._choose_src_mac(global_index)
            dst_mac = self._choose_dst_mac(global_index)

            payload = self._build_normal_packet_payload(
                packet_index=i,
                payload_size=self.args.normal_payload_size,
                value=self.args.value_start + global_index,
            )

            pkt = Ether(src=src_mac, dst=dst_mac, type=self.args.normal_etype) / Raw(payload)
            pkt.time = self.args.start_time + packet_index * self.args.inter_packet_gap

            packets.append(pkt)
            records.append(
                PacketRecord(
                    index=packet_index,
                    packet_type=PacketType.NORMAL,
                    timestamp=float(pkt.time),
                    src_mac=src_mac,
                    dst_mac=dst_mac,
                    ether_type=self.args.normal_etype,
                    payload_len=len(payload),
                )
            )
            packet_index += 1

        if self.args.shuffle:
            packets, records = self._shuffle_packets(packets, records, rng)

        return packets, records

    def _build_value_payload(self, dtype: PayloadDataType, payload_size: int, value: int) -> bytes:
        if payload_size < 0:
            raise ValueError("payload_size must be non-negative")

        payload = bytearray()
        if dtype == PayloadDataType.INT8:
            while len(payload) < payload_size:
                payload.append(value & 0xFF)
            return bytes(payload)

        while len(payload) + 4 <= payload_size:
            dtype_obj = getattr(self.args, "dtype", None)
            dtype_name = getattr(dtype_obj, "name", str(dtype_obj)).upper()
            if dtype_name == "FP32":
                payload.extend(struct.pack("<f", float(value)))
            else:
                payload.extend(struct.pack("<I", value & 0xFFFFFFFF))

        while len(payload) < payload_size:
            payload.append(value & 0xFF)

        return bytes(payload)

    def _build_normal_packet_payload(self, packet_index: int, payload_size: int, value: int) -> bytes:
        if packet_index < 0 or packet_index > 0xFFFFFFFF:
            raise ValueError("packet_index must fit in uint32")
        if payload_size < 0 or payload_size > 0xFFFFFFFF:
            raise ValueError("payload_size must fit in uint32")

        header = struct.pack("<II", packet_index, payload_size)
        body = bytearray()
        while len(body) < payload_size:
            body.append((value + len(body)) & 0xFF)

        return header + bytes(body)

    def _encode_base_chunk_header(self, chunk_id: int, p_size: int) -> bytes:
        if chunk_id < 0 or chunk_id > 0xFFFFFFFF:
            raise ValueError("chunk_id must fit in uint32")
        if p_size < 0 or p_size > 0xFFFFFFFF:
            raise ValueError("p_size must fit in uint32")

        return struct.pack("<II", chunk_id, p_size)

    def _encode_collective_chunk_header(
        self,
        flow_id: int,
        op_flags: int,
        collective_op: CollectiveOp,
        dtype: PayloadDataType,
        expected_contributions: int,
        contribution_index: int,
        collective_flags: int = 0,
    ) -> bytes:
        if flow_id < 0 or flow_id > 0xFFFF:
            raise ValueError("flow_id must fit in uint16")
        if op_flags < 0 or op_flags > 0xFF:
            raise ValueError("op_flags must fit in uint8")
        if collective_flags < 0 or collective_flags > 0xFF:
            raise ValueError("collective_flags must fit in uint8")
        if expected_contributions < 0 or expected_contributions > 0xFFFF:
            raise ValueError("expected_contributions must fit in uint16")
        if contribution_index < 0 or contribution_index > 0xFFFF:
            raise ValueError("contribution_index must fit in uint16")

        reserved = 0
        # New layout: flow_id (H), collective_op (B), op_flags (B), dtype (B), collective_flags (B), reserved (B), expected (H), contribution (H)
        # Mini-Sharp custom header fields are little-endian.
        return struct.pack(
            "<HBBBBBHH",
            int(flow_id),
            int(collective_op),
            int(op_flags),
            int(dtype),
            collective_flags,
            reserved,
            expected_contributions,
            contribution_index,
        )

    def _build_reduction_packet_payload(
        self,
        flow_id: int,
        op_flags: int,
        chunk_id: int,
        p_size: int,
        collective_op: CollectiveOp,
        collective_flags: int,
        dtype: PayloadDataType,
        expected_contributions: int,
        contribution_index: int,
        payload_size: int,
        value: int,
    ) -> bytes:
        base_chunk = self._encode_base_chunk_header(chunk_id=chunk_id, p_size=p_size)
        collective = self._encode_collective_chunk_header(
            flow_id=flow_id,
            op_flags=op_flags,
            collective_op=collective_op,
            dtype=dtype,
            expected_contributions=expected_contributions,
            contribution_index=contribution_index,
            collective_flags=collective_flags,
        )
        payload = self._build_value_payload(dtype=dtype, payload_size=payload_size, value=value)
        return base_chunk + collective + payload

    def _choose_src_mac(self, index: int) -> str:
        if self.args.vary_sources:
            return mac_for_host(self.args.src_mac_prefix, 1 + (index % self.args.source_hosts))
        return self.args.src_mac

    def _choose_dst_mac(self, index: int) -> str:
        if self.args.vary_destinations:
            return mac_for_host(self.args.dst_mac_prefix, 1 + (index % self.args.destination_hosts))
        return self.args.dst_mac

    def _shuffle_packets(self, packets: List[Ether], records: List[PacketRecord], rng: random.Random):
        combined = list(zip(packets, records))
        rng.shuffle(combined)

        packets = []
        records = []

        for new_index, (pkt, rec) in enumerate(combined):
            if self.args.retimestamp_after_shuffle:
                pkt.time = self.args.start_time + new_index * self.args.inter_packet_gap
                rec.timestamp = float(pkt.time)
            rec.index = new_index
            packets.append(pkt)
            records.append(rec)

        return packets, records

    def _write_manifest(self, path: str, records: List[PacketRecord]) -> None:
        writer_fields = [
            "index",
            "packet_type",
            "timestamp",
            "src_mac",
            "dst_mac",
            "ether_type",
            "op_flags",
            "flow_id",
            "chunk_id",
            "collective_op",
            "dtype",
            "expected_contributions",
            "contribution_index",
            "payload_len",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=writer_fields)
            writer.writeheader()
            for r in records:
                writer.writerow(
                    {
                        "index": r.index,
                        "packet_type": enum_name(r.packet_type),
                        "timestamp": f"{r.timestamp:.9f}",
                        "src_mac": r.src_mac,
                        "dst_mac": r.dst_mac,
                        "ether_type": f"0x{r.ether_type:04x}",
                        "op_flags": enum_name(r.op_flags),
                        "flow_id": r.flow_id,
                        "chunk_id": r.chunk_id,
                        "collective_op": enum_name(r.collective_op),
                        "dtype": enum_name(r.data_type),
                        "expected_contributions": r.expected_contributions,
                        "contribution_index": r.contribution_index,
                        "payload_len": r.payload_len,
                    }
                )

    def _print_summary(self, records: List[PacketRecord]) -> None:
        normal_count = sum(1 for r in records if r.packet_type == PacketType.NORMAL)
        reduction_count = sum(1 for r in records if r.packet_type == PacketType.REDUCTION)

        print("PCAP generation complete")
        print(f"  output:                  {self.args.output}")
        print(f"  manifest:                {self.args.manifest if self.args.manifest else '-'}")
        print(f"  packets total:           {len(records)}")
        print(f"  reduction packets:       {reduction_count}")
        print(f"  normal packets:          {normal_count}")
        print(f"  reduction EtherType:     0x{self.args.reduction_etype:04x}")
        print(f"  normal EtherType:        0x{self.args.normal_etype:04x}")
        print(f"  shuffle enabled:         {self.args.shuffle}")
        print(f"  retimestamp shuffle:     {self.args.retimestamp_after_shuffle}")
        print(f"  operation id:            {self.args.reduce_operation.name}")
        print(f"  collective operation:    {self.args.collective_op.name}")
        print(f"  dtype:                   {self.args.dtype.name}")
        print(f"  seed:                    {self.args.seed}")


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "pcap-generate",
        help="Generate Ethernet PCAP with Mini-Sharp reduction traffic.",
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Output PCAP file path.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Optional CSV manifest output path.",
    )
    parser.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        default=True,
        help="Overwrite output files if they already exist. Enabled by default.",
    )
    parser.add_argument(
        "--no-overwrite",
        dest="overwrite",
        action="store_false",
        help="Do not overwrite output files if they already exist.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Random seed for deterministic generation.",
    )
    parser.add_argument(
        "--start-time",
        type=float,
        default=0.0,
        help="Timestamp of first generated packet in seconds.",
    )
    parser.add_argument(
        "--inter-packet-gap",
        type=float,
        default=1e-6,
        help="Gap between generated packet timestamps in seconds.",
    )
    parser.add_argument(
        "--shuffle",
        dest="shuffle",
        action="store_true",
        default=True,
        help="Shuffle generated packets. Enabled by default.",
    )
    parser.add_argument(
        "--no-shuffle",
        dest="shuffle",
        action="store_false",
        help="Disable packet shuffling.",
    )
    parser.add_argument(
        "--retimestamp-after-shuffle",
        action="store_true",
        help="Rewrite timestamps after shuffling so packet times remain monotonic.",
    )
    parser.add_argument(
        "--src-mac",
        default=DEFAULT_SRC_MAC,
        help="Default source MAC address.",
    )
    parser.add_argument(
        "--dst-mac",
        default=DEFAULT_DST_MAC,
        help="Default destination MAC address.",
    )
    parser.add_argument(
        "--vary-sources",
        action="store_true",
        help="Generate multiple source MAC addresses.",
    )
    parser.add_argument(
        "--vary-destinations",
        action="store_true",
        help="Generate multiple destination MAC addresses.",
    )
    parser.add_argument(
        "--source-hosts",
        type=int,
        default=4,
        help="Number of source hosts when --vary-sources is enabled.",
    )
    parser.add_argument(
        "--destination-hosts",
        type=int,
        default=4,
        help="Number of destination hosts when --vary-destinations is enabled.",
    )
    parser.add_argument(
        "--src-mac-prefix",
        default=DEFAULT_SRC_MAC_PREFIX,
        help="Five-octet source MAC prefix used with --vary-sources.",
    )
    parser.add_argument(
        "--dst-mac-prefix",
        default=DEFAULT_DST_MAC_PREFIX,
        help="Five-octet destination MAC prefix used with --vary-destinations.",
    )
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
        help="EtherType used for normal background packets.",
    )
    parser.add_argument(
        "--reduction-packets",
        type=int,
        default=100,
        help="Number of Mini-Sharp reduction packets.",
    )
    parser.add_argument(
        "--normal-packets",
        type=int,
        default=0,
        help="Number of normal background packets.",
    )
    parser.add_argument(
        "--chunk-id-start",
        type=int,
        default=0,
        help="Starting chunk ID.",
    )
    parser.add_argument(
        "--flow-id-start",
        type=int,
        default=0,
        help="Starting flow ID (uint16).",
    )
    parser.add_argument(
        "--expected-contributions",
        type=int,
        default=4,
        help="Expected contributions per reduction group.",
    )
    parser.add_argument(
        "--collective-flags",
        type=parse_int_auto,
        default=0,
        help="Collective flags byte.",
    )
    parser.add_argument(
        "--collective-op",
        type=lambda x: enum_from_string(CollectiveOp, x),
        default=CollectiveOp.REDUCE,
        choices=list(CollectiveOp),
        help="Collective operation.",
    )
    parser.add_argument(
        "--reduce-operation",
        type=lambda x: enum_from_string(ReduceOperation, x),
        default=ReduceOperation.SUM,
        choices=list(ReduceOperation),
        help="Reduction operation / operation_id.",
    )
    parser.add_argument(
        "--dtype",
        type=lambda x: enum_from_string(PayloadDataType, x),
        default=PayloadDataType.INT8,
        choices=list(PayloadDataType),
        help="Payload data type.",
    )
    parser.add_argument(
        "--reduction-payload-size",
        type=int,
        default=64,
        help="Reduction payload buffer size in bytes.",
    )
    parser.add_argument(
        "--normal-payload-size",
        type=int,
        default=64,
        help="Normal background payload size in bytes.",
    )
    parser.add_argument(
        "--value-start",
        type=int,
        default=1,
        help="Starting deterministic value encoded in payloads.",
    )
    parser.set_defaults(func=lambda args: PCAPGenerator(args).generate())
