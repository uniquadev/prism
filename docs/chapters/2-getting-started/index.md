# 2. Getting started

PRISM contains the canonical software library in `repo/prism-ccl` and the RTL
and verification environment in `repo/prism-hdl`.

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
reports under `build/prism-hdl/results/` with:

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

<div class="grid cards" markdown>

-   :material-chip: **RTL datapath**

    Start with `repo/prism-hdl/rtl.f` for the compile order, then follow
    `src/core/prism_collective_core.sv` through the complete pipeline.

-   :material-code-json: **Protocol and CCL**

    Read `repo/prism-ccl/src/prism_ccl/protocol/` for the canonical wire ABI,
    models, numeric formats, validation, and serialization.

-   :material-test-tube: **Verification**

    Open `repo/prism-hdl/verification/suites/__init__.py` for suite composition,
    then inspect `verification/tests/` for the corresponding test scenarios.

</div>
