# 2. Getting Started

This page is the entry point for reproducing the documentation build and, once
the RTL tree lands in the repository, the first hardware simulation flow.

## Documentation preview

Set up a local Python environment and install the pinned documentation stack:

```powershell
$env:NO_MKDOCS_2_WARNING="1"
uvx --with-requirements requirements-docs.txt mkdocs serve
```

MkDocs serves the site at `http://127.0.0.1:8000/` and reloads pages
as Markdown files change.

## Strict build

Use a strict build before publishing or sharing results:

```powershell
$env:NO_MKDOCS_2_WARNING="1"
uvx --with-requirements requirements-docs.txt mkdocs build --strict
```

Strict mode turns broken links, missing navigation targets, and configuration
warnings into failures.

## Hardware workflow scaffold

The expected thesis workflow is:

1. Build the RTL and verification dependencies.
2. Generate or load packet traces.
3. Run the first packet-processing test.
4. Inspect waveform and trace artifacts.
5. Record observed throughput, latency, and failure modes in
   [4. Results](../4-results/index.md).

!!! note "Implementation status"

    The repository currently documents the thesis structure. As RTL,
    traffic-generation, and verification files are added, this page should
    become the reproducible command log for the first successful simulation.
