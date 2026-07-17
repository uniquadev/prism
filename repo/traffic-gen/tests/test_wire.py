from __future__ import annotations

import struct
import unittest

from prism_protocol.constants import (
    CHUNK_PAYLOAD_BYTES,
    CONTROL_HEADER_BYTES,
    DATA_HEADER_BYTES,
    PROGRESS_HEADER_BYTES,
    RESULT_HEADER_BYTES,
    AccumulationPolicy,
    AccumulatorProfile,
    CollectiveSemantic,
    ControlCommand,
    ControlFlag,
    DataFlag,
    Opcode,
    PartialWireFormat,
    ProgressFlag,
    ProgressPeerKind,
    ProgressReason,
    ReductionOperator,
    Status,
    TlvFlag,
    TlvType,
    WireFormat,
    assert_unique_enum_values,
)
from prism_protocol.errors import ProtocolDecodeError
from prism_protocol.model import ArithmeticTuple, OperationDescriptor, ResultRangeRoute
from prism_protocol.wire import (
    ControlFrame,
    ControlHeader,
    ControlReassembler,
    ControlWord,
    DataHeader,
    OperationIdentity,
    ProgressHeader,
    ProtocolVersionRange,
    ResultHeader,
    Tlv,
    elements_in_chunk,
    expected_chunks,
    expected_payload_bytes,
    pack_tlvs,
    parse_tlvs,
    validate_payload_length,
    validate_tlv_schema,
)


class WireLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = OperationIdentity(
            job_id=0x0102030405060708,
            group_id=0x1112,
            group_generation=0x1314,
            operation_id=0x1516,
            operation_generation=0x1718191A,
        )

    def test_canonical_values_are_unique(self) -> None:
        assert_unique_enum_values()

    def test_fixed_header_sizes_and_payload(self) -> None:
        self.assertEqual(CONTROL_HEADER_BYTES, 24)
        self.assertEqual(DATA_HEADER_BYTES, 24)
        self.assertEqual(PROGRESS_HEADER_BYTES, 40)
        self.assertEqual(CHUNK_PAYLOAD_BYTES, 1474)

    def test_every_documented_packet_diagram_bit_sum(self) -> None:
        self.assertEqual(4 + 4 + 8, 16)  # control word
        self.assertEqual(64 + 64 + 16 + 8 + 8 + 16 + 16, 192)  # control
        self.assertEqual(64 + 16 + 16 + 16 + 32 + 16 + 24 + 8, 192)  # data/result
        self.assertEqual(
            64 + 16 + 16 + 16 + 32 + 16 + 8 + 8 + 24 + 16 + 24 + 16 + 8 + 8 + 32 + 16,
            320,
        )  # progress
        self.assertEqual(16 + 16 + 32, 64)  # TLV header
        self.assertEqual(RESULT_HEADER_BYTES, 24)

    def test_control_word_network_order(self) -> None:
        self.assertEqual(ControlWord(Opcode.COL_DATA).pack(), bytes((0x10, 0x02)))
        self.assertEqual(ControlWord.unpack(bytes((0x10, 0x03))).opcode, Opcode.COL_RES)
        with self.assertRaises(ProtocolDecodeError):
            ControlWord.unpack(bytes((0x01, 0x02)))

        version_range = ProtocolVersionRange(1, 0, 1, 0)
        self.assertEqual(version_range.pack(), bytes.fromhex("0100010000000000"))
        self.assertTrue(ProtocolVersionRange.unpack(version_range.pack()).supports(1, 0))
        with self.assertRaises(ProtocolDecodeError):
            ProtocolVersionRange.unpack(bytes.fromhex("0100010000000001"))

    def test_control_header_round_trip(self) -> None:
        header = ControlHeader(
            0x0102030405060708,
            0x1112131415161718,
            ControlCommand.OP_PREPARE,
            ControlFlag.REQUEST | ControlFlag.ACK_REQUIRED,
            Status.OK,
            1,
            3,
        )
        encoded = header.pack()
        self.assertEqual(len(encoded), 24)
        self.assertEqual(encoded[:8], bytes.fromhex("0102030405060708"))
        self.assertEqual(ControlHeader.unpack(encoded), header)

    def test_data_and_result_headers_round_trip(self) -> None:
        data = DataHeader(self.identity, 0x2021, 0x222324, DataFlag.ACK_REQUIRED)
        payload = bytes(range(16))
        encoded = data.pack(payload)
        self.assertEqual(len(encoded), 2 + 24 + len(payload))
        decoded, decoded_payload = DataHeader.unpack(encoded)
        self.assertEqual(decoded, data)
        self.assertEqual(decoded_payload, payload)

        result = ResultHeader(self.identity, 0x3031, 0x323334, DataFlag.RETRANSMIT)
        decoded_result, decoded_payload = ResultHeader.unpack(result.pack(payload))
        self.assertEqual(decoded_result, result)
        self.assertEqual(decoded_payload, payload)

        fp32_little_endian = struct.pack("<f", 1.0)
        self.assertEqual(fp32_little_endian, bytes.fromhex("0000803f"))
        _, preserved = DataHeader.unpack(data.pack(fp32_little_endian))
        self.assertEqual(preserved, fp32_little_endian)

    def test_progress_header_and_selective_ack_round_trip(self) -> None:
        header = ProgressHeader(
            self.identity,
            peer_id=7,
            peer_kind=ProgressPeerKind.RESULT_PATH,
            flags=ProgressFlag.SELECTIVE_ACK | ProgressFlag.RESULT_PATH,
            window_base=10,
            admitted_window_chunks=32,
            selective_ack_base=8,
            selective_ack_bits=9,
            status=Status.OK,
            reason=ProgressReason.ACCEPTED,
            retry_delay_us=250,
        )
        encoded = header.pack(b"\xff\x80")
        self.assertEqual(len(encoded), 2 + 40 + 2)
        decoded, bitmap = ProgressHeader.unpack(encoded)
        self.assertEqual(decoded, header)
        self.assertEqual(bitmap, b"\xff\x80")

        malformed = bytearray(encoded)
        malformed[41] = 1  # low byte of the final reserved 16-bit field
        with self.assertRaises(ProtocolDecodeError):
            ProgressHeader.unpack(bytes(malformed))

    def test_tlv_round_trip_alignment_and_unknown_policy(self) -> None:
        tlvs = (Tlv(TlvType.ERROR_DETAIL, b"abc"), Tlv.u64(TlvType.JOB_ID, 9))
        encoded = pack_tlvs(tlvs)
        self.assertEqual(len(encoded) % 8, 0)
        self.assertEqual(parse_tlvs(encoded), tlvs)

        unknown_optional = struct.pack("!HHI", 0x7FFE, 0, 0)
        self.assertEqual(parse_tlvs(unknown_optional), ())
        unknown_mandatory = struct.pack("!HHI", 0x7FFE, int(TlvFlag.MANDATORY), 0)
        with self.assertRaises(ProtocolDecodeError):
            parse_tlvs(unknown_mandatory)

        nonzero_padding = struct.pack("!HHI", int(TlvType.ERROR_DETAIL), 1, 1) + b"x" + b"\0" * 6 + b"\1"
        with self.assertRaises(ProtocolDecodeError):
            parse_tlvs(nonzero_padding)

    def test_command_schema_rejects_missing_and_duplicate_tlvs(self) -> None:
        with self.assertRaises(ProtocolDecodeError):
            validate_tlv_schema(ControlCommand.CAPS_RESPONSE, ())
        valid = (
            Tlv.u64(TlvType.DEVICE_BOOT_ID, 1),
            Tlv(TlvType.PROTOCOL_VERSION_RANGE, b"12345678"),
            Tlv(TlvType.CAPABILITIES, b""),
        )
        validate_tlv_schema(ControlCommand.CAPS_RESPONSE, valid)
        with self.assertRaises(ProtocolDecodeError):
            validate_tlv_schema(ControlCommand.CAPS_RESPONSE, (*valid, valid[0]))

    def test_fragment_reassembly_reverse_order_and_timeout(self) -> None:
        payload = pack_tlvs((Tlv.u64(TlvType.GROUP_HANDLE, 1),))
        first, second = payload[:5], payload[5:]
        reassembler = ControlReassembler(1024, 1.0)
        header1 = ControlHeader(1, 2, ControlCommand.GROUP_COMMIT, ControlFlag.REQUEST, fragment_index=1, fragment_count=2)
        header0 = ControlHeader(1, 2, ControlCommand.GROUP_COMMIT, ControlFlag.REQUEST, fragment_index=0, fragment_count=2)
        self.assertIsNone(reassembler.add(ControlFrame(header1, second), now=0.0))
        result = reassembler.add(ControlFrame(header0, first), now=0.1)
        self.assertEqual(result[0].type, TlvType.GROUP_HANDLE)

        timeout_reassembler = ControlReassembler(1024, 1.0)
        timeout_reassembler.add(ControlFrame(header0, first), now=0.0)
        self.assertEqual(len(timeout_reassembler.expire(1.0)), 1)

        malformed = ControlReassembler(1024, 1.0)
        malformed.add(ControlFrame(header0, first), now=0.0)
        changed = ControlHeader(1, 2, ControlCommand.GROUP_STATUS, ControlFlag.REQUEST, fragment_index=1, fragment_count=2)
        with self.assertRaises(ProtocolDecodeError):
            malformed.add(ControlFrame(changed, second), now=0.1)

        conflicting = ControlReassembler(1024, 1.0)
        conflicting.add(ControlFrame(header0, first), now=0.0)
        with self.assertRaises(ProtocolDecodeError):
            conflicting.add(ControlFrame(header0, b"different"), now=0.1)

    def test_chunk_geometry_and_exact_payload_lengths(self) -> None:
        self.assertEqual(expected_chunks(1000, 368), 3)
        self.assertEqual(elements_in_chunk(1000, 368, 2), 264)
        self.assertEqual(expected_payload_bytes(1000, 368, 0, WireFormat.FP32), 1472)
        self.assertEqual(expected_payload_bytes(1000, 368, 2, WireFormat.FP32), 1056)
        self.assertEqual(expected_payload_bytes(1474, 1474, 0, WireFormat.INT8), 1474)
        with self.assertRaises(OverflowError):
            expected_payload_bytes(1474, 1474, 0, WireFormat.FP32)
        self.assertEqual(validate_payload_length(4, 1, 1, 0, WireFormat.FP32), 4)
        self.assertEqual(validate_payload_length(20, 1, 1, 0, WireFormat.FP32), 4)  # 16 bytes Ethernet padding
        with self.assertRaises(ProtocolDecodeError):
            validate_payload_length(5, 1, 1, 0, WireFormat.FP32)
    def test_partial_wire_values_and_arithmetic_tuple_encoding_are_locked(self) -> None:
        self.assertEqual(
            {member.name: int(member) for member in PartialWireFormat},
            {
                "INVALID": 0x00,
                "FP32": 0x04,
            },
        )
        arithmetic = ArithmeticTuple(
            WireFormat.FP32,
            AccumulatorProfile.FP32,
            AccumulationPolicy.CONTRIBUTOR_ORDERED,
            PartialWireFormat.FP32,
            WireFormat.FP32,
        )
        self.assertEqual(arithmetic.encode(), 0x0401020404000000)
        self.assertEqual(ArithmeticTuple.decode(arithmetic.encode()), arithmetic)
        with self.assertRaisesRegex(ValueError, "reserved bits"):
            ArithmeticTuple.decode(arithmetic.encode() | 1)

    def test_operation_descriptor_round_trip(self) -> None:
        descriptor = OperationDescriptor(
            CollectiveSemantic.REDUCE,
            ReductionOperator.SUM,
            WireFormat.FP32,
            AccumulatorProfile.FP32,
            AccumulationPolicy.CONTRIBUTOR_ORDERED,
            PartialWireFormat.FP32,
            WireFormat.FP32,
            element_count=1000,
            max_reduction_terms=4,
            requested_window_chunks=8,
            requested_replay_slots=16,
            timeout_ms=1000,
            retry_limit=3,
            result_delivery_role=True,
            result_range_routes=(ResultRangeRoute(0, 2, 7),),
        )
        encoded = descriptor.pack()
        self.assertEqual(len(encoded), 32)
        self.assertEqual(encoded[2:8], bytes((0x04, 0x01, 0x02, 0x04, 0x04, 0x01)))
        self.assertEqual(OperationDescriptor.unpack(encoded, descriptor.result_range_routes), descriptor)
        malformed = bytearray(encoded)
        malformed[31] = 1
        with self.assertRaises(ValueError):
            OperationDescriptor.unpack(bytes(malformed), descriptor.result_range_routes)

    def test_truncated_and_reserved_fields_are_rejected(self) -> None:
        with self.assertRaises(ProtocolDecodeError):
            DataHeader.unpack(b"\x10\x02" + b"\0" * 10)
        header = DataHeader(self.identity, 0, 0, DataFlag.ACK_REQUIRED)
        encoded = bytearray(header.pack(b""))
        encoded[25] |= 0x80
        with self.assertRaises(ProtocolDecodeError):
            DataHeader.unpack(bytes(encoded))


if __name__ == "__main__":
    unittest.main()
