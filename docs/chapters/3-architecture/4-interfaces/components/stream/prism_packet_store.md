# `prism_packet_store`

**Module class:** `COMPONENT / STREAM`  

`prism_packet_store` retains complete locally owned packets from one ingress
independently of their arrival order. A 16-bit local handle plus the descriptor's
8-bit ingress port decouples reception from later validation, CONTROL
reassembly, payload normalization, and release.

## Contracts

- **Slot allocation — input/output, 32-bit reservation request and response:**
  allocates maximum-frame beat capacity and returns a 15-bit reservation ID.
  The committed packet handle is zero-extended to 16 bits.

- **Write stream — input, one `prism_axis` + 16-bit reservation ID:** accepts
  packet beats in order and records the observed length and error qualifiers.

- **Commit descriptor — input, 384-bit payload + valid/ready:** atomically makes
  a closed packet visible under its handle. A descriptor with nonzero status
  aborts rather than commits.

- **Read command — input, 32-bit payload + valid/ready:** contains 16-bit packet
  handle and 16-bit starting beat. Multiple readers are arbitrated, not allowed
  to drive the same memory port concurrently.

- **Read stream — output, one `prism_axis`:** returns the stored packet from the
  requested beat through its stored `tlast`, preserving the original `tkeep`
  and error bit.

- **Release command — input, 16-bit handle + valid/ready:** decrements the
  packet's owner reference. Storage becomes free only when no reader, validator,
  arithmetic producer, or reassembly transaction retains it.

- **Store state — output, 64 bits:** 16-bit free beats, 16-bit free handles,
  16-bit committed packets, 8-bit reader occupancy, and 8 error flags.

## Contract behavior

- A handle is not reused until all references are released and every earlier
  read response for that handle has retired.
- Packet writes are sequential, but reads can select any committed handle. The
  implementation may use a beat RAM plus a handle-to-base/length descriptor
  RAM.
- Allocation failure is reported before the ingress drains into the store.
  Partial writes are aborted and never presented as committed packets.
- One ingress write and one consumer read can make progress concurrently. The
  two v1 instances provide two write and two read streams in aggregate without
  requiring a four-ported packet RAM.

## Related modules and concepts

[`prism_ingress_unit`](../../units/prism_ingress_unit.md) is the only writer.
[`prism_packet_validator`](prism_packet_validator.md),
[`prism_data_depacketizer`](../collective/prism_data_depacketizer.md), and
[`prism_management_unit`](../../units/prism_management_unit.md) are readers.
