# 3.4.1 Datapath contracts

PRISM has one wire ABI and several internal transfer units. Ethernet fields and
packet headers are fixed by the protocol; beats, tiles, ranges, and accumulator
state are implementation contracts derived from the build profile.

## Transfer rule

Streams between blocks use decoupled `valid`/`ready`. A transfer occurs only on
`valid && ready`; while stalled, the producer holds payload and metadata stable.
State changes only after the owning transfer is accepted.

Inside the wide sections of the RESULT path (segment scheduling, tile encoding,
the merge trees, the slicer, final rounding) the stages advance every cycle and
have no stall input. Such a section ends in a queue, and its producer may send
an item only while the section and the queue together hold fewer items than the
queue stores. An accepted item therefore always finds room, and no `ready`
runs back through the section. Signals that steer a whole tile, such as the
decision to take the next one, are kept as one registered copy per 256 bits of
the tile.

## Data boundaries

| Boundary | Carries | Ownership rule |
|---|---|---|
| AXI frame | `tdata`, `tkeep`, `tlast`, `tuser` | Accepted `tlast` closes one frame; arbiters never interleave frames. |
| Parsed frame | fixed header, byte count, ingress identity, adapter errors | Parsing does not imply validity. CONTROL or DATA sees a frame only after closure and validation. |
| CONTROL request | one validated command and context | No table changes before full frame and command validation completes. |
| Native issue group | up to 64 INT8, 32 FP16/BF16 or 16 FP32 values | Format, contributor and global first position transfer with the values. |
| Arithmetic slice | sixteen element positions | Parallel slices accept disjoint positions of one native issue group. |
| Arithmetic lane | operation identity plus global element position | One position owns arithmetic state until completion: Kulisch for exact accumulation, FP32 for arrival accumulation. |
| Result snapshot | rounded native values and installed rank bindings | The result sender retains values through transmission to the selected recipients. |

The SINGLE control plane owns admission and lifecycle. The DATA receiver owns
interval coverage; exact slices or online FP32 banks own arithmetic
state; the result store and sender own completed values until transmission.
Egress timing cannot change an already committed arithmetic contribution.

## Width and identity

| Unit | Width or key | Purpose |
|---|---|---|
| Wire chunk | MTU-bounded NumberGroups | One DATA or RESULT packet; First Element names its global vector position. |
| AXI beat | `DATA_W`, 512 bits by default | Physical streaming width; `tkeep` marks valid bytes. |
| Native issue group | 512 bits in the current SINGLE reader | Up to four sixteen-lane slices, independent of NumberGroup boundaries. |
| Global range | operation key plus first element | Packet-format-independent accumulator identity. |
| Accumulator state | FP32 for rounded policies; 320-bit Kulisch for exact policies in the current SINGLE | Numerical policy is distinct from the partial-wire and RESULT formats. |

Format conversion can change group and packet boundaries; global element
position identifies accumulator state. The active SINGLE path supports FP32
arrival and fixed Kulisch as distinct policies.

## Safety invariants

- Full storage propagates backpressure; accepted work is never silently dropped.
- Duplicate contributors do not update a range twice.
- FP32 updates to the same global element serialize through read, addition and
  write-back. Disjoint lanes of a split tile can overlap; independent ranges
  can enter each cycle; bank arbitration defines
  admission order. A stalled request cannot update state.
- Exact payload length determines output `tkeep` and `tlast`.
- Reset clears tentative ownership and emits no partial frame.

These internal transfer rules remain separate from the wire packet layout.
