# Experiments

Each discovered project is a direct child named
`<order>-experiment-<lowercase-hyphenated-name>` and contains `experiment.py`,
`pyproject.toml`, `uv.lock`, and `README.md`. Discovery sorts by numeric order and
ignores incomplete/misnamed directories. Explicitly requesting an invalid
project returns an error explaining what is missing. Listing never imports or
executes experiment code.

```sh
uv run --python 3.13 experiments/run/launch.py list
uv run --python 3.13 experiments/run/launch.py run 01-experiment-single-reduce -- all
uv run --python 3.13 experiments/run/launch.py run 01-experiment-single-reduce --docker -- all
```

The NumberGroup RTL measurements are in `02-experiment-numbergroup-single`;
`03-experiment-single-port-latency` measures eight logical ranks on one physical
port. Each project README gives its command.

Each experiment keeps only `experiment.py` as its root entry point. Its workload,
RTL callback and plotting tools live under that project's `src/` directory.
A measurement belongs to one backend: model ticks, RTL cycles and hardware time
are not interchangeable, so the software template measures traffic only and
the RTL projects record Cocotb/Verilator as their backend in the manifest.

The launcher passes arguments after `--` unchanged to `experiment.py` and uses
`uv run --locked --no-dev --project ...` to resolve each project's local libraries.
Docker uses the same lockfile in a separate container environment, never the
host `.venv`. Native cocotb runs need a working simulator and C++ toolchain;
Windows users can use Docker or run the local command inside WSL.

Local environments and uv caches live under `build/cache/` and are separated by
platform, so Windows and WSL cannot overwrite each other's environment. uv
provides the Python runtime; a separate Python installation is not required.
Make is an optional shortcut. `make experiment ... DOCKER=1` invokes Docker
directly and requires neither host Python nor host uv.

Collected data belongs under `build/experiments/` by default. Keep raw samples,
the effective configuration and source/tool identities together. Plot-only
commands must work without simulation.

The shared `experiments/run` package supplies immutable RTL build
configuration, hashed build caches, source snapshots and provenance helpers.
It is infrastructure, not a PrismWorld backend and not a second protocol API.
