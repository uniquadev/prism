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
repo/rtl/          SystemVerilog RTL and Cocotb/Verilator verification environment.
repo/traffic-gen/  Synthetic traffic and PCAP generation tools.
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
