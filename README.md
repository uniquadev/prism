# PRISM

This repository contains the source code, documentation, and experiments developed
for a bachelor thesis at Sapienza University of Rome.

**Thesis title:** Development of primitive hardware for network computing

**Student:** Lorenzo Cipolletti  
**Supervisor:** Salvatore Pontarelli  
**Co-supervisor:** Daniele De Sensi  
**University:** Sapienza University of Rome

## Repository layout

```text
docs/              MkDocs source: chapters, assets, drafts, and the site home page.
repo/prism-hdl/    SystemVerilog RTL and Cocotb/Verilator verification environment.
repo/prism-ccl/    Canonical protocol, collective API, PCAP tools, and Wireshark dissector.
```

## Getting started

Run the complete verification environment from the repository root. Docker is
the recommended path because it supplies Python, Verilator, Cocotb, and tshark:

```bash
make test DOCKER=1
```

Useful variants are:

```bash
make env DOCKER=1
make build DOCKER=1
make test SUITE=rtl-formats DOCKER=1
make test XML=1 DOCKER=1
```

XML test reports are disabled by default. `XML=1` retains them under
`build/prism-hdl/results/`. Remove `DOCKER=1` to use tools installed locally.

Windows users with Docker Desktop do not need GNU Make. In PowerShell, this
copy-paste command builds the image and runs all tests in a temporary container:

```powershell
docker build --target test -t prism-hdl:dev -f repo/prism-hdl/Dockerfile .; if ($LASTEXITCODE -eq 0) { docker run --rm --mount "type=bind,source=$($PWD.Path),target=/work" --workdir /work --env PRISM_BUILD_DIR=/tmp/prism-build --env COVERAGE_FILE=/tmp/.coverage prism-hdl:dev }
```

## Documentation

The thesis documentation is built with MkDocs and Material for MkDocs.

```powershell
$env:NO_MKDOCS_2_WARNING="1"
uvx --with-requirements requirements-docs.txt mkdocs serve
```

Run a strict production build before publishing:

```powershell
$env:NO_MKDOCS_2_WARNING="1"
uvx --with-requirements requirements-docs.txt mkdocs build --strict
```

`uvx mkdocs serve` is not enough for this project because `uvx` isolates the
`mkdocs` package from the Material theme and plugins listed in
`requirements-docs.txt`.
