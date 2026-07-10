# PRISM host protocol library

This package provides the canonical PRISM Protocol 1.0 numeric assignments,
network-byte-order serializers/parsers, pure resource and reliability models,
and transport-neutral multi-switch Aggregation Manager helpers.

It deliberately contains no raw-socket or deployment-specific network I/O.

Run the tests with:

```powershell
uv run python -m unittest discover -s tests -v
```
