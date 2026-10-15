# 2. Getting started

PRISM contains the canonical software library in `repo/prism-ccl` and the RTL
and verification environment in `repo/prism-hdl`. Building the bitstream and
running it on an Alveo U280 is described in [2.3 Alveo U280](u280.md).

## Run an experiment

From the repository root:

```bash
make experiments
make experiment EXP=01-experiment-single-reduce ARGS="all --seed 7"
make experiment EXP=01-experiment-single-reduce DOCKER=1 ARGS="collect --collective allreduce"
make experiment EXP=01-experiment-single-reduce ARGS="plot --input build/experiments/01-experiment-single-reduce/RUN"
```

Local runs use uv to provide Python and locked dependencies. With `DOCKER=1`,
Make invokes Docker directly: host Python and uv are not required. `collect`
writes a fresh run under git-ignored `build/experiments/`; `plot` reads saved
measurements without starting simulation. The starter measures CCL packet
traffic; `02-experiment-numbergroup-single` takes the RTL measurements.

Without Make, use `uv run --python 3.13 experiments/run/launch.py
run 01-experiment-single-reduce -- all`. The
[CCL and experiments guide](ccl-experiments.md) explains the topology, vectors,
policies, local library imports and device/build boundary.

## Run the tests

From the repository root, the recommended command is:

```bash
make test DOCKER=1
```

It builds the test image and runs the complete suite with the same runner used
locally. Run a smaller suite while developing with:

```bash
make test SUITE=rtl-integration DOCKER=1
```

Use `make env DOCKER=1` to print the environment and `make build DOCKER=1` to
check RTL elaboration without running tests. Remove `DOCKER=1` only when Python,
Verilator, Cocotb, and tshark are installed locally.

XML test reports are temporary and deleted by default. Preserve JUnit-compatible
reports under `build/cache/rtl-simulation/results/` with:

```bash
make test XML=1 DOCKER=1
```

## Windows without Make

Docker Desktop and PowerShell are sufficient. This command builds the image and
runs the full suite in a container that is removed when the run finishes:

```powershell
docker build --target test -t prism-hdl:dev -f repo/prism-hdl/Dockerfile .; if ($LASTEXITCODE -eq 0) { docker run --rm --mount "type=bind,source=$($PWD.Path),target=/work" --workdir /work --env PRISM_BUILD_DIR=/tmp/prism-build --env COVERAGE_FILE=/tmp/.coverage prism-hdl:dev }
```

DUT-observed captures are written to
`repo/prism-hdl/verification/traces/<test-name>/`.

## Where to start reading

- RTL: `repo/prism-hdl/rtl.f` gives the compile order; follow
  `src/core/prism_collective_core.sv` through the pipeline.
- Protocol and CCL: read [CCL and experiments](ccl-experiments.md), then
  `repo/prism-ccl/src/prism_ccl/domain/`, `wire/` and `application/` for the
  numeric models, the wire ABI and packet execution.
- Verification: `repo/prism-hdl/verification/suites/` composes the suites from
  the tests in `verification/tests/`.
