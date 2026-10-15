# Joint software optimum for NumberGroups and compression

`joint_optimizer.py` sits next to the AUTO experiment of this directory. It
finds the minimum total RESULT-frame bytes for each ordered operation, choosing
numeric formats, contiguous group boundaries, group codecs and packet
boundaries together; it does not change the CCL or the RTL. The thesis plot
uses its optimized AUTO and all-format compression totals, with the fixed RAW
Kulisch and FP32 baselines of `exact_accumulator_study.py`. The bounded-AUTO
results of that study are in `results.json`. The Kulisch-only compression
ablation is in `joint_results.json` and in the tables below, but not in the
four-bar thesis figure.

## What "optimal" means

The objective is the sum of Ethernet RESULT-frame bytes: 56 bytes of header
per frame plus every 4-byte group descriptor, encoded payload, and zero
padding to a 4-byte group boundary. FCS, preamble and IFG are excluded, as in
`exact_accumulator_study.py`. A 1500-byte MTU leaves 1458 body bytes; aligned
groups can use at most 1456 of these. The optimum is in bytes, not in
execution time.

The input is the same exact sum of four locally emulated FP32 rank partials.
All output representations are lossless. The element order is fixed; groups
are contiguous, nonempty, and cannot cross packet boundaries. Operations
contain at most 4096 elements, as in the study. Optimization
is global within each such operation, not across separate operations.

Every interval is eligible for every format that represents all its values
exactly: INT8, FP16, BF16, FP32 and 320-bit Kulisch. The optimizer is allowed
to retain a native-representable value in Kulisch if that improves the complete
encoded stream. It does not force the narrowest format on each element.

Four separately optimized candidate sets isolate the effects:

| Key | Allowed formats | Allowed codecs |
|---|---|---|
| `numbergroups_only` | All five | RAW only |
| `kulisch_compressed` | Kulisch only | RAW, RANGE, INDEX, MASK |
| `numbergroups_kulisch_compressed` | All five | Native RAW; all four Kulisch codecs |
| `numbergroups_all_compressed` | All five | All four codecs for every format |

"Kulisch only" still uses NumberGroup descriptors and can partition into
multiple groups with different codecs. It disables native-format selection,
not the grouping mechanism required by the proposed compressed protocol.

The optimum is relative to these byte-level codecs and constraints. It is
not a claim of optimal compression among arbitrary codecs, dictionaries,
bit-level representations, element reorderings, or numerical approximations.
Finite values with canonical positive zero are evaluated; special states and
signed-zero semantics are not inferred from this dataset.

## Native-value compression

Native values are first encoded losslessly with the CCL numeric encoder.
Compression acts on those exact 1-, 2-, or 4-byte bit patterns in little-endian
byte order. Float sign and exponent bits stay in their native bit positions;
they are not reinterpreted as Kulisch magnitudes. INT8 retains two's complement.

| Codec | Native payload |
|---|---|
| RAW | Concatenated native words |
| RANGE | Per value: count byte, first byte position, then that contiguous range |
| INDEX | Per value: count byte, then position/content pairs for nonzero bytes |
| MASK | One shared byte-position bitmap, then selected bytes for every value |

Native RANGE/INDEX count bytes have no sign field; unused high bits are zero.
Native MASK uses `ceil(word_bytes / 8)` bitmap bytes: one byte for the native
formats here. It has no separate sign bitmap, since the sign is part of the
native word. Kulisch keeps the existing sign/magnitude codecs: MASK uses
five position-mask bytes plus `ceil(count / 8)` sign bytes. A native all-zero
group can therefore have a one-byte MASK payload regardless of its count;
the descriptor supplies the element count. RAW is always a fallback.

The group descriptor identifies numeric format and codec separately: as in
the compression proposal, its reserved second byte would carry the codec ID.
These payloads are a software proposal; the CCL and the RTL do not accept
compressed packets. Native compression needs the same protocol and parser
extension, with format-dependent decoding.

## Why the algorithm is exact

1. For every contiguous interval, enumerate every permitted lossless format
   and codec. Compute its complete aligned group size. Retain the minimum.
   A larger group representation for the same interval cannot improve any
   packet placement; grouping adjacent intervals together is considered
   separately as its own candidate interval.
2. Solve a shortest path on states `(i, r)`, where `i` is the number of output
   values already encoded and `r` is the current packet body occupancy in
   four-byte units. Each edge adds one interval/group. It either extends the
   current packet if it fits, or starts a new packet and pays another header.
   Starting a new packet is considered even when the group would still fit.
3. Prune only dominated source states: at the same `i`, a state with no more
   bytes paid and no more current packet space occupied can reproduce every
   continuation of the other state for no greater cost. There is no bounded
   lookahead, beam search, heuristic cutoff, or solver tolerance.
4. Trace back the minimum terminal state. Actually encode and decode every
   selected payload, verify native numerical exactness, and reconcile all
   payload/descriptor/padding/header bytes with the optimum.

Every feasible ordered packet/group plan is a path in this graph. Edge costs
are exact and additive. Eliminating larger representations and dominated
states preserves at least one minimum-cost path. Thus the result is the global
minimum under the stated candidate set and constraints.

Group size is nondecreasing when an interval grows, and a format that becomes
invalid cannot become valid again for that interval. Interval enumeration can
therefore stop when no candidate fits. All nonempty groups cost at least 8
bytes, so no packet can contain more than 182 groups under this MTU: the
protocol's 255-group bound is automatically respected. The 4096-element
operation limit likewise implies the 65535-element packet/group count bounds.
Larger MTUs or operation limits require revisiting these arguments; the API
rejects body budgets above the current experiment's budget.

One selected plan is retained when minima tie. Group counts and codec choices
describe that plan; the optimizer does not additionally minimize their counts.

## Results

Total frame bytes, with each column optimized independently:

| Workload | NumberGroups, RAW only | Kulisch + compression | NumberGroups + Kulisch compression | NumberGroups + all-format compression |
|---|---:|---:|---:|---:|
| cavity01 | 5832 | 1788 | 1748 | 1748 |
| bcsstk16 | 15404 | 18804 | 13800 | 13776 |
| QKV | 12556 | 1852 | 1852 | 1852 |
| MLP | 16656 | 2280 | 2280 | 2280 |

Allowing all formats and codecs cannot worsen the minimum: its candidate set
contains the RAW-only, Kulisch-only and Kulisch-compression-only solutions.
The implementation checks these inequalities for every workload.

Native compression saves another 24 bytes in bcsstk16, from 13800 to
13776 (about 0.17%). The selected plan contains nine FP16/MASK groups. It does
not improve the minimum in the other three evaluated vectors. In QKV and MLP,
the optimal mixed-format solution can remain entirely Kulisch: respectively
seven MASK plus three RANGE groups, and four MASK plus two RANGE groups.

The optimal RAW grouping is in general not the optimal compressed grouping.
For a direct check, `raw_optimal_grouping_then_compression` freezes the formats
and boundaries of the RAW-optimal plan, picks the best codec in each group,
then repacks whole groups in order. The results are:

| Workload | Compress RAW-optimal groups afterward | Jointly optimize groups/formats/codecs |
|---|---:|---:|
| cavity01 | 2128 | 1748 |
| bcsstk16 | 13940 | 13776 |
| QKV | 2832 | 1852 |
| MLP | 3760 | 2280 |

Changing the grouping objective matters even with a globally optimal RAW
selector in place of the eight-value AUTO lookahead: optimizing the first
stage alone does not optimize the composition.

## Reproduce and validate

The source files must already be in the cache of `exact_accumulator_study.py`
(run it with `--download` first). The same pinned SHA-256 checks run before
any kernel computation; this command downloads nothing.

```powershell
uv run --no-project --with numpy==2.5.3 --with numba==0.68.0 python experiments/04-experiment-exact-accumulator-compression/joint_optimizer.py
uv run --no-project --with numpy==2.5.3 --with numba==0.68.0 python -m unittest discover -s experiments/04-experiment-exact-accumulator-compression -p 'test_*.py' -v
```

`joint_results.json` stores source hashes, constraints, all four minima,
byte-component totals, format/codec counts, and the complete chosen packet and
group plans. Operation-relative element offsets are paired with each
operation's global first element. `optimizer_seconds` is diagnostic host-side
wall time (including any JIT compilation in that call), not PRISM latency or
a benchmark of a hardware implementation.

Validation includes 396 exhaustive small-input/regime/budget comparisons using
an independent recursive oracle that enumerates formats, codecs, all group
boundaries and packet choices from actual encoded payloads. It does not share
the production cost formulas or Pareto pruning. Other tests cover native raw
bit-pattern round trips, malformed payloads, extreme signed Kulisch values,
interval-cost formulas versus actual encodings, a 4096-zero compressed group,
group splitting, keeping native-representable values in Kulisch, and the
monotonicity of candidate supersets. A RAW-optimal packet plan is also encoded
with the existing CCL serializer and its complete frame size checked.

An additional nonzero constructed case (32 copies of 0.5) checks a strict
native-compression improvement: 124 bytes RAW-only, 104 with Kulisch compression
available, and 96 with FP16/MASK available. It is a codec test, not a fifth
application benchmark and is not included in the table above.

The constructed thesis example with 726 sums equal to `1 + 2^-24` is also
stored in `joint_results.json`: two MASK groups (680 and 46 values) occupy
1676 frame bytes, against 31048 bytes for the uniform RAW baseline.

A dedicated FP32 test keeps a group of 32 copies of `0.5 + 2^-24` as
`format=FP32, encoding=MASK`, reconstructing the original `0x3f000001` words
bit for bit. The complete frame uses 128 bytes; no conversion to Kulisch is
required to apply compression.

Optimality follows from the graph construction and the dominance argument;
the exhaustive small cases check the implementation independently and do not
enumerate the workloads.
