# Two-rank SINGLE SUM

This is a runnable template, not a performance claim. It uses the real
`PrismWorld` packet model, checks Reduce/AllReduce results and resource release,
and records serialized frame counts and bytes. SUM is currently the supported
operation. Inputs and outputs are FP32; policies can be selected explicitly.

From the PRISM root:

```sh
make experiment EXP=01-experiment-single-reduce ARGS="all --seed 7"
make experiment EXP=01-experiment-single-reduce DOCKER=1 ARGS="collect --collective allreduce"
make experiment EXP=01-experiment-single-reduce ARGS="plot --input build/experiments/01-experiment-single-reduce/RUN"
```

Or, without Make (uv provisions Python; add `--docker` to use Docker):

```sh
uv run --python 3.13 experiments/run/launch.py run 01-experiment-single-reduce -- all --seed 7
uv run --python 3.13 experiments/run/launch.py run 01-experiment-single-reduce --docker -- collect --samples 5
```

`collect` creates a fresh directory with `manifest.json` and `samples.json`.
`plot` reads that directory and writes SVG/PNG figures without collection.
`all` does both. Paths are relative to the PRISM root. Existing run directories
are never overwritten. `--root-rank` is valid only for Reduce. The template
pairs fixed Kulisch accumulation with lossless `AUTO` partials, and the rounded
policies with `FP32` partials. The bit-level library exposes both separately.

The manifest records the seed, operation, formats, MTU, source hashes, revision,
dirty checkout status and measurement boundary. Model ticks are **not RTL
cycles**, and frame byte counts exclude FCS, preamble and inter-packet gap.

## RTL measurements

This template measures software-model frame traffic only; it has no RTL cycle
metric and does not offer a `--backend` switch that cannot execute the same
measurement. Use
`02-experiment-numbergroup-single` for the current Cocotb SINGLE measurement;
its simulator cycles are not physical timing or model ticks. Internal congestion
still requires explicit RTL monitors, not inference from software ticks.

Copy this directory to `<order>-experiment-<name>`, change `[project].name` and
the workload under `src/single_reduce/`, then regenerate `uv.lock` with `uv lock
--project experiments/<directory>`. Local dependencies are declared in
`pyproject.toml`; do not copy the CCL or add `sys.path` hacks.
