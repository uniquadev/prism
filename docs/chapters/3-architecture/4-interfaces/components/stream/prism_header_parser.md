# `prism_header_parser`

**Module class:** `COMPONENT / STREAM`  

`prism_header_parser` extracts the Ethernet header, PRISM control word, and the
first 24 bytes of the selected class header from the first 512-bit beat. This is
the complete DATA, RES, or CONTROL fixed header and the v1-relevant prefix of a
PROGRESS header. Ownership, operation support, and full payload length belong
to later modules.

## Contracts

- **First-beat input — input, 512-bit data + 64-bit byte mask + 8-bit ingress
  port:** sampled with a one-bit valid/ready handshake. `tkeep` identifies which
  of the required header bytes are present.

- **Parsed-header output — output, 352-bit payload + valid/ready:** returns the
  320-bit raw header image, ingress port, parse-status byte, and required-header
  byte count.

- **Parser error — output, 16 bits + valid/ready:** reports short Ethernet,
  short PRISM control, short operation header, illegal keep, and unsupported
  major-version observations without deciding whether to forward or drop.

## Contract behavior

- Ethernet and PRISM header integers are decoded from network byte order. DATA
  and RES numeric payload bytes remain untouched for the little-endian payload
  converter.
- Non-PRISM frames need only the 14-byte Ethernet header. A local DATA or RES
  frame requires 40 bytes through the operation header, all present in the v1
  first beat.
- The parser never reads beyond asserted `tkeep`, never infers missing bytes as
  zero, and clears fields not valid for the selected opcode.
- A registered implementation may add latency, but it accepts one first beat
  per cycle and returns results in ingress-local order.

## Related modules and concepts

The field layouts are fixed by [Common frame format](../../../1.protocol.md#common-frame-format)
and [Packet layouts](../../../1.protocol.md#packet-layouts).
[`prism_forwarding_unit`](../../units/prism_forwarding_unit.md) consumes the
parsed output.
