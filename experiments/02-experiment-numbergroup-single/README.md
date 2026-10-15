# NumberGroup SINGLE RTL

This experiment runs the same seeded Reduce or AllReduce through the compiled
two-port `prism_sim_top` with fixed Kulisch. FP32 input also
enables explicitly approximate FP32 arrival accumulation. Results are checked against the
corresponding independent mathematical oracle. It records the first accepted
STAGE beat, COMMIT ACK, DATA window and final accepted RESULT beat, plus frame
bytes; these are simulated AXI events, not routed timing.
The evaluation uses two ranks, one on each physical port. An optional
three-rank run shares port 0 between two endpoints. Collective ingress rates
are aggregate rates, not a per-port Ethernet line rate. Physical RAM is not
estimated from this experiment.

From the PRISM root:

```sh
uv run --python 3.13 experiments/run/launch.py run 02-experiment-numbergroup-single -- all --seed 7 --ranks 2 --elements 64
uv run --python 3.13 experiments/run/launch.py run 02-experiment-numbergroup-single -- all --seed 7 --ranks 3 --elements 64 --workload half_ulp
uv run --python 3.13 experiments/run/launch.py run 02-experiment-numbergroup-single -- all --seed 7 --ranks 2 --elements 4096 --input-format fp16
uv run --python 3.13 experiments/run/launch.py run 02-experiment-numbergroup-single -- all --seed 7 --ranks 2 --elements 4096 --input-format fp32 --output-format kulisch
uv run --python 3.13 experiments/run/launch.py run 02-experiment-numbergroup-single -- all --seed 7 --ranks 2 --elements 4096 --input-format fp32 --output-format auto
uv run --python 3.13 experiments/run/launch.py run 02-experiment-numbergroup-single -- summarize
```

`collect` writes `manifest.json`, `device.json`, `samples.json`, and Cocotb
results under a new `build/experiments/` run. Ordered and reordered runs have
separate directories. `plot --input RUN` redraws the traffic/cycle figure
without simulation. Repeat `collect` with other seeds for independent raw runs.

## Workloads and options

- The ordinary workload uses the same exactly representable integer values for
  INT8, FP16, BF16 and FP32 inputs. `--output-format` selects a native RESULT,
  exact 320-bit Kulisch, or lossless `AUTO`. Rounded FP32 policies run for
  FP32 input and FP32 or AUTO output.
- `half_ulp` forces an inexact FP32 addition at each position and requires
  FP32 input; with three ranks it exposes the FP32 rounding difference against
  exact accumulation.
- `sparse_exact` uses two FP32 ranks: the first sum is $1+2^{-24}$ and the
  remaining sums are small integers. It compares mixed AUTO RESULT groups with
  uniform Kulisch RESULT traffic from the same inputs and accumulator. Samples
  record the number of RESULT elements in each concrete wire format.
- `--output-stall-period 3` holds egress ready low every third simulator
  cycle; stalled beats are counted separately from unstalled performance.
- `--capture-pcaps` saves the accepted RX and TX frames of each DUT port under
  `captures/<policy>/`, with `all_ports.pcapng` ordered by simulator timestamp.
- `--reorder-probability 0.25 --reorder-seed 7` applies a seeded, bounded
  perturbation to each rank-to-PRISM stream. The default two-packet
  perturbation fits the receiver's two-packet window. This reorders original
  packets; it is not retransmission, and it is not a measured network
  distribution. Samples record the late packets and the maximum displacement.

This SINGLE run sends no switch-to-switch partials; the separate partial RTL
harness tests their encoding and merge. The per-run SVG compares policies at
one vector length; a length sweep needs several run directories. Samples keep
the raw cycle milestones apart from the 4 ns target-clock conversion. Numeric
RESULT rates count the bytes of the decoded NumberGroups; compare frame bytes
and elements/s as well when AUTO chooses different widths.

`summarize` regenerates separate ordered and reordered CSV indexes from the
completed runs; failed attempts are listed in `failed_runs.json`. Compare runs
only within one `build_id`, since RTL changes produce separate simulator builds.

## Thesis figures

`plot_thesis.py` draws the thesis figures from complete two-rank runs of one
RTL build, with source-matched comparison pairs, and writes their CSV and
per-run source hashes; `results/` holds those for the thesis build
`dfd75793798e565a0ae27fc66819eb589f629afe01f31b7415f4cad99d887758`. The raw
runs are not part of the repository. The figures cover RESULT frame
throughput and per-port DATA element rate, collective response time,
final-contribution latency, and RESULT frame bytes of mixed AUTO against
uniform Kulisch. The plotter rejects missing scenarios, mismatched source
snapshots, different inputs within a pair, and a wrong concrete-format mix.

The runs behind them:

- AllReduce with FP32 input at 64, 256, 1024 and 4096 elements.
- AUTO and Kulisch output for all four native input types at 4096 elements,
  plus one FP32-input, FP32-output control.
- For the NumberGroup figure, a two-rank `one_wide` Reduce with 726 FP16 or
  363 FP32 elements per rank, once with `--output-format auto` and once with
  `--output-format kulisch`: the largest single-group DATA packets at MTU 1500
  (1512 frame bytes per rank in either case). One sum needs Kulisch, the others
  keep their native type. BF16 has the byte width of FP16 and is omitted.
- For the final-contribution latency, `--preload-first-rank` sends and
  acknowledges rank 0 before rank 1's single DATA packet of 64 elements; waits
  of 64 and 128 cycles must agree.

All runs use seed 7, no output stalls and ordered DATA. To keep a sweep
source-matched while the RTL changes, pass the `device.json` of a completed run
as `--source-device`; the experiment checks every source hash against that
run's build snapshot before starting.

```sh
uv run --project experiments/02-experiment-numbergroup-single --group dev \
  python experiments/02-experiment-numbergroup-single/src/numbergroup_single/plot_thesis.py \
  --build-id dfd75793798e565a0ae27fc66819eb589f629afe01f31b7415f4cad99d887758 \
  --output <directory>
```

Frame-byte totals include Ethernet headers but exclude FCS, preamble and
inter-frame gap. RESULT frame rate counts the transmitted frame bytes over the
accepted output window, not numeric payload alone. The 4 ns conversion is a
simulated target-clock assumption, not an FPGA timing result.
