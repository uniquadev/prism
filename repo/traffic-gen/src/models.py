from dataclasses import dataclass
from typing import Optional

from traffic_types import CollectiveOp, PayloadDataType, PacketType, ReduceOperation

# Reduction key: flow_id + chunk_id (flow_id is uint16)
#
# Ethernet header: 14 bytes
#
# Mini-Sharp header (current implementation, breaking change): 19 bytes
#
# Base chunk header:
#  - chunk_id (uint32)
#  - p_size   (uint32)
#
# Collective header (after base chunk header):
#  - flow_id   (uint16)    -- identifies the collective flow across contributors
#  - collective_op (uint8) -- gather/reduce
#  - op_flags  (uint8)     -- operation-specific flags (for REDUCE contains reduce operator)
#  - data_type (uint8)
#  - collective_flags (uint8)
#  - reserved  (uint8)
#  - expected_contributions (uint16)
#  - contribution_index    (uint16)

@dataclass
class PacketRecord:
    index: int
    packet_type: PacketType
    timestamp: float
    src_mac: str
    dst_mac: str
    ether_type: int
    op_flags: Optional[ReduceOperation] = None
    flow_id: Optional[int] = None
    chunk_id: Optional[int] = None
    collective_op: Optional[CollectiveOp] = None
    data_type: Optional[PayloadDataType] = None
    expected_contributions: Optional[int] = None
    contribution_index: Optional[int] = None
    payload_len: int = 0
