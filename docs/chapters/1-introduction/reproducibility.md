# Floating-Point Reproducibility

Floating-point addition rounds after every operation and is not associative.
Different arrival orders may therefore produce different bits. PRISM compares
three strategies to measure the trade-off between hardware cost, throughput,
and reproducibility.

## Concepts and profiles

| Term | Meaning |
|---|---|
| Element | One vector value, such as `a[7]` |
| Lane | One parallel arithmetic position |
| Tile | Consecutive elements plus a valid mask and metadata |
| Range | The global positions covered by a tile |
| Accumulator bank | Independent range state and arithmetic path |

With sixteen lanes, tiles `[a0,...,a15]` and `[b0,...,b15]` are combined in
parallel: lane \(i\) handles position \(i\).

| Profile | Rule | Property |
|---|---|---|
| `FP32_ARRIVAL` | Apply each contribution on arrival | Streaming, but order-dependent |
| `FP32_ORDERED` | Apply ascending Contributor IDs | Reproducible, with a reorder buffer |
| `KULISCH_FP32` | Deposit exactly and round once | Streaming and order-independent when wide enough |

Here, **streaming** means that every contribution can be used immediately.
`FP32_ORDERED` can apply only the next Contributor ID and buffers early ones.
The two-rank prototype stores the pair; with more ranks, the current RTL waits
for the whole range and then folds it in order. This is correct but batch-like.

The Kulisch guarantee is node-local. Serializing a partial as FP32 rounds at
that hop; an exact multi-switch reduction needs a lossless partial format that
the protocol does not yet assign.

## Parallelism for 100 Gbit/s

For \(b_d\) bits per element, \(L_d\) lanes, clock \(f\), and initiation
interval \(II_d\):

\[
T_d=\frac{L_d b_d f}{II_d},
\qquad
L_{min}(d)=\left\lceil\frac{T_{goal}II_d}{b_d f}\right\rceil.
\]

At 250 MHz with \(II=1\) and a 100 Gbit/s target:

| Datatype | Minimum lanes | Lanes for 512 bits/cycle | Current 16-lane rate |
|---|---:|---:|---:|
| FP32 | 13 | 16 | 128 Gbit/s |
| FP16 | 25 | 32 | 64 Gbit/s |
| BF16 | 25 | 32 | 64 Gbit/s |
| INT8 | 50 | 64 | 32 Gbit/s |

Today `LANES=16` is both tile size and physical issue width. Narrow formats use
the same sixteen 32-bit containers, so their lane count does not grow
automatically. A cleaner design separates `TILE_ELEMENTS=16` from FP32 and
per-width Kulisch issue slices. One 512-bit beat contains one FP32 microtile,
two FP16/BF16 microtiles, or four INT8 microtiles.

For \(N\) contributors and \(L_d\) results per cycle, a binary reduction needs
\((N-1)L_d\) additions per cycle; online Kulisch needs \(NL_d\) deposits. Output
width can still dominate: 64 INT8 inputs converted to FP32 produce 2048 result
bits and cannot leave through one 512-bit port in one cycle.

## Kulisch accumulation

A finite value can be written as:

\[
x=(-1)^sM2^{e-(p-1)}.
\]

Kulisch aligns \(M\) in a fixed-point accumulator, adds without intermediate
rounding, and converts to floating point once at the end. NaNs, infinities, and
signed zeros are tracked separately.

The current RTL uses the same sixteen lanes for FP32 and Kulisch. Widths 64,
288, and 320 select numeric capacity, but the scheduler stores each lane in the
maximum physical width `WIDTH_2=320`; they are not three separate accumulator
memories.

Numeric state cost is approximately:

\[
S_{Kulisch}\approx B R_b L_K W_K,
\]

where \(B\) is bank count, \(R_b\) ranges per bank, \(L_K\) lanes, and \(W_K\)
bits per lane. Kulisch parallelism should therefore be configurable separately
from FP32 parallelism.

## Accumulator width

For a scalar sum of \(R\) values, including subnormals:

\[
W_{signed}=E_{max}-E_{min}+p+\lceil\log_2R\rceil+1.
\]

| Input | Required width |
|---|---:|
| INT8 | \(8+\lceil\log_2R\rceil\) |
| FP16 | \(41+\lceil\log_2R\rceil\) |
| BF16 | \(262+\lceil\log_2R\rceil\) |
| FP32 | \(278+\lceil\log_2R\rceil\) |

For \(R=256\), FP32 needs \(278+8=286\) bits per lane, so the 288-bit backend
is sufficient. If no compiled width is sufficient, PRISM selects the largest,
saturates, and propagates `ACCUMULATION_INEXACT`.

This formula applies to \(\sum_i x_i\). A dot product \(\sum_i a_i b_i\) needs
a wider accumulator and is outside the current scope.

SHARP and SwitchML motivate in-network reduction[^sharp-overview][^switchml],
while FPISA shows the cost of floating point in programmable datapaths[^fpisa].
PRISM uses an FPGA prototype to measure this trade-off without assuming Kulisch
is always preferable.

[^sharp-overview]: NVIDIA, *Scalable Hierarchical Aggregation and Reduction
    Protocol (SHARP)*. https://docs.nvidia.com/networking/display/sharpv300

[^switchml]: Sapio et al., *Scaling Distributed Machine Learning with In-Network
    Aggregation*, NSDI 2021.
    https://www.usenix.org/conference/nsdi21/presentation/sapio

[^fpisa]: Yuan et al., *Unlocking the Power of Inline Floating-Point Operations
    on Programmable Switches*, NSDI 2022.
    https://www.usenix.org/system/files/nsdi22-paper-yuan.pdf
