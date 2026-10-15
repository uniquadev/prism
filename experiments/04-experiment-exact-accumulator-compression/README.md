# Lossless superaccumulator compression study

The figure `results_by_domain.*` takes AUTO and AUTO + compression on all
formats from the global grouping, format, codec and packet optimizer described
in [JOINT_OPTIMIZER.md](JOINT_OPTIMIZER.md) (`joint_optimizer.py`,
`joint_results.json`), and uniform RAW Kulisch and fixed FP32 from
`results.json`. The study below, `exact_accumulator_study.py`, is the two-stage
baseline: the CCL's AUTO packetizer first, then compression of its groups.

## Two-stage baseline (`results.json`)

This is a reproducible *software estimate*, not a PRISM RTL or MPI measurement.
It constructs four FP32 rank partials per output using a local SpMV or model
projection kernel, reduces those partials exactly, and counts RESULT Ethernet
frame bytes under PRISM's 1500-byte MTU. Frame totals include the 14-byte
Ethernet header, 2-byte PRISM control word, 40-byte RESULT header, 4-byte
NumberGroup descriptors, and per-group four-byte padding. They exclude FCS,
preamble, and inter-frame gap. Vectors are split into operations of at most
4096 outputs.

The five compared methods are uniform 320-bit Kulisch, **uniform Kulisch plus
proposed adaptive compression**, the **current** CCL `AUTO` packetizer,
**AUTO plus proposed adaptive Kulisch compression**, and
fixed FP32 (lossy whenever the exact sum is not FP32-representable). The
proposed NumberGroup retains `format = KULISCH` and adds a separate encoding
selector in descriptor byte 1:

| Encoding | Proposed ID | Payload modeled for 320-bit finite values |
|---|---:|---|
| `RAW` | 0 | Existing 41-byte Kulisch value |
| `RANGE` | 1 | Sign/count byte, first occupied byte position, then contiguous bytes per value |
| `INDEX` | 2 | Sign/count byte, then position and content for each nonzero byte |
| `MASK` | 3 | Shared 40-bit position mask, packed signs, then selected bytes per value |

`RANGE` and `INDEX` start each value with the same metadata byte: bit 6
stores the sign (0 for nonnegative, 1 for negative), bits 5:0 store the
size, and bit 7 is zero. In `RANGE`, `rs` (*range size*) is the span length
in bytes, including internal zeros; in `INDEX`, `ps` (*positions size*)
is the number of nonzero byte positions. The next byte
is a position in both encodings.

The **current** protocol requires byte 1 to be zero; neither CCL nor RTL
accepts the proposed nonzero encoding IDs. This script models their payloads
and frame accounting only. It leaves native-format AUTO groups untouched and
selects the shortest padded encoding, including `RAW`, **separately for each
Kulisch NumberGroup**. The selector minimizes each group's encoded size, not
the entire vector's global packetization cost. Sign metadata, the 4-byte
group descriptor and padding are included; selected groups are then
repacketized. The 8-bit sub-blocks are a *wire encoding* choice, not a
required RTL lane width. Finite values are round-tripped through each
selected codec. Nonfinite states are outside this dataset and would require
`RAW` or a defined special-value rule in a future wire specification. Wider
Kulisch configurations also need an explicit position-index width. No
hardware parser, encoder, storage, throughput or timing cost is measured.

The additional uniform-compression baseline isolates the contribution of AUTO's
native-format selection. Every result remains Kulisch. The current CCL first
splits the homogeneous output at the MTU, giving one group of at most 35 raw
values per frame. The same adaptive selector then compresses each of these
groups and repacketizes them. Headers, descriptors and padding are counted in
both compressed methods. "Without NumberGroups" here means without
mixed-format AUTO grouping, not without the protocol's mandatory descriptor.
Compression retains the pre-compression group boundaries in both methods;
neither is a globally optimized compressed packetizer or a single group spanning
multiple Ethernet frames.

This comparison does not establish that AUTO is necessary for effective
compression. In the four evaluated vectors, uniform Kulisch plus compression
uses 5.97, 4.36, 5.31 and 4.82 bytes/value (cavity01, bcsstk16, QKV, MLP), versus
6.78, 3.04, 7.52 and 7.40 for AUTO plus compression. AUTO improves the compressed
result by 30.1% for bcsstk16. For the other three vectors, uniform compression
is smaller. All QKV and MLP uniform groups select MASK, whereas AUTO creates many
smaller Kulisch groups. Shared-mask amortization and group overhead therefore
matter alongside the choice of numeric format. The
[joint optimizer](JOINT_OPTIMIZER.md) evaluates the global optimum and
native-value compression; neither is implemented in the CCL or the RTL.

Sources (the script pins these versions and SHA-256 hashes):

- [SuiteSparse DRIVCAV/cavity01](https://sparse.tamu.edu/DRIVCAV/cavity01):
  official Matrix Market archive with both matrix and `cavity01_x.mtx` vector.
  The 317-row CFD SpMV uses both. SHA-256:
  `B1481371E07E7997910216F3C395BB7898F96243DF8F16A5A46174410B19F41D`.
- [SuiteSparse HB/bcsstk16](https://sparse.tamu.edu/HB/bcsstk16):
  structural matrix, from the pinned official SuiteSparse repository commit
  `e202a5bcef55f5a780c26830ebd6ff13af193baf`. The 4884-row symmetric
  SpMV uses a **synthetic**, explicitly fixed input `x[j] = 1`, not an
  application-provided RHS. SHA-256:
  `44FF2C8750B6134A6A22874B0DDE9F37463FAAD954A662E047B9E6ED0F21EDB5`.
- [EleutherAI Pythia-14m](https://huggingface.co/EleutherAI/pythia-14m):
  official `model.safetensors` from commit
  `cf967c0a9a04383db6f7b1108d86b2962634b4ac`. QKV and MLP matrices
  from layer 0 are multiplied by embedding row 42, with the 128-element inner
  dimension split across four ranks. This is a *kernel emulation*, not a
  full-model run or a captured distributed-training collective. SHA-256:
  `116A02532DB461F91386A5B20F942FF2C8D4DE7341E21B55CAAFC3D7B25F49A1`.

Run from the repository root (Python 3.11+; `matplotlib` is needed only for
the figure):

```powershell
python experiments/04-experiment-exact-accumulator-compression/exact_accumulator_study.py --download
uv run --no-project --with numpy==2.5.3 --with numba==0.68.0 python experiments/04-experiment-exact-accumulator-compression/joint_optimizer.py
uv run --no-project --with numpy==2.5.3 --with numba==0.68.0 python -m unittest discover -s experiments/04-experiment-exact-accumulator-compression -p 'test_*.py' -v
python experiments/04-experiment-exact-accumulator-compression/plot_results.py
```

`results.json` records exact frame totals, packet counts, source provenance,
format distributions and the number of Kulisch groups selected for each
encoding (`selected_encoding_groups` for AUTO and `uniform_selected_encoding_groups`
for uniform Kulisch), plus pre-compression `source_group_counts`.
`results_by_domain.pdf` is a vertical grouped
bar chart in **total RESULT-frame bytes divided by output-vector length N**,
not an average across repeated runs. This normalization makes differently
sized kernels comparable. Its four bars in each group come from
`results.json` (uniform Kulisch, fixed FP32) and `joint_results.json` (AUTO,
AUTO + adaptive compression); the compressed bar may mix encodings across
groups, and the constructed FP16 tie case is discussed in the thesis text. One
input and one small model do not establish a population-level claim about all
CFD, HPC or LLM workloads.
