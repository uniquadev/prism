from enum import IntEnum


DEFAULT_REDUCTION_ETYPE = 0x88B5
DEFAULT_NORMAL_ETYPE = 0x0800
DEFAULT_SRC_MAC = "02:00:00:00:00:01"
DEFAULT_DST_MAC = "02:00:00:00:00:02"
DEFAULT_SRC_MAC_PREFIX = "02:00:00:00:01"
DEFAULT_DST_MAC_PREFIX = "02:00:00:00:02"


class PacketType(IntEnum):
    NORMAL = 0
    REDUCTION = 1


class ReduceOperation(IntEnum):
    SUM = 0
    MIN = 1
    MAX = 2
    AVG = 3


class CollectiveOp(IntEnum):
    GATHER = 0
    REDUCE = 1


class PayloadDataType(IntEnum):
    FP32 = 0
    BF16 = 1
    FP16 = 2
    INT8 = 3


def parse_int_auto(value: str) -> int:
    return int(value, 0)


def enum_from_string(enum_cls, value: str):
    if isinstance(value, enum_cls):
        return value

    text = str(value).strip().upper()
    if text in enum_cls.__members__:
        return enum_cls[text]

    return enum_cls(int(value, 0))


def enum_name(value):
    if value is None:
        return None
    if isinstance(value, IntEnum):
        return value.name
    return str(value)


def mac_for_host(prefix_5_octets: str, host_id: int) -> str:
    if host_id < 0:
        raise ValueError("host_id must be non-negative")
    return f"{prefix_5_octets}:{host_id & 0xff:02x}"
