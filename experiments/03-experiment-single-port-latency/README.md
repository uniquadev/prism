# Eight ranks on one physical port: final-contribution latency

This experiment runs one `SINGLE` AllReduce at a time through the real RTL.
Eight logical ranks, each with a distinct MAC address, endpoint binding, and
input vector, share one full-duplex 512-bit AXI4-Stream port. Seven ranks send
their contribution before a fixed idle interval; the eighth completes the
collective. The baseline does not impose output stalls or reorder packets.

The primary interval starts at the **last accepted AXI beat** of the final
rank's DATA packet and ends at the **first accepted RESULT beat**. The CSV also
records first accepted final-DATA beat to first RESULT beat and the final-DATA
ingress duration. These are distinct from whole-collective response time.
The recorded nanoseconds multiply cycles by a *simulated* 4 ns period; they
are not FPGA timing-closure results.
The one-port RTL selects a narrower internal path than the two-port wide
configuration, so these latencies must not be extrapolated to other physical
port counts.

The default matrix measures 64 and 256 elements. Each fits one native DATA
packet. INT8, FP16, BF16, and FP32 use `KULISCH_FIXED` with Kulisch RESULT;
FP32 additionally uses `FP32_ARRIVAL` with FP32 RESULT.
No AUTO wire format is used. Ordinary inputs are distinct deterministic
integers; the sensitive FP32 case includes cancellation and a half-ULP term.
All eight results are checked against an arithmetic oracle, and the run checks
packet identities, result delivery, no premature RESULT, and context release.

Run from this directory in an environment with `uv` and Verilator:

```sh
uv run --offline python experiment.py --lengths 64 256
uv run --offline python experiment.py --lengths 64 --settle-cycles 256
uv run --offline python experiment.py --lengths 64 --output-stall-period 5
```

Each invocation prints its run directory under
`build/experiments/03-experiment-single-port-latency/`. A completed run has
`manifest.json`, `device.json` (RTL file hashes and build ID), `samples.json`,
and `samples.csv`. The third command is a separate backpressure check; do not
mix it into the baseline figure. To regenerate the vector figure, use the
first two completed runs:

```sh
uv run --offline python src/single_port_latency/plot_latency.py --run <baseline-run> --settle-check <256-cycle-run> --backpressure-check <stalled-run>
```

The plotter rejects incomplete runs, different RTL builds, invalid samples,
or latency that changes with preload wait. It produces PDF and SVG figures
and a provenance JSON under `results/figures/`, and copies the validated
runs' CSV, JSON, and RTL source hashes to `results/data/`. The optional
backpressure run must use the same RTL and seed and contain observed stalls.

The dashed red reference is [EPIC Appendix K.1](https://arxiv.org/html/2605.18683v2),
which reports approximately 230 ns for Mode-II, eight ranks, Intel Agilex,
in RTL simulation. It gives no payload size or element count for this latency
measurement, and describes the start as arrival of the final packet without
specifying the beat. Its FPGA platform and measurement boundary also differ
from this experiment. The 250 MHz clock and 244 ns
figure in Appendix K.2 refer to a separate VU13P implementation. The red
line is therefore context, not a controlled head-to-head result.
