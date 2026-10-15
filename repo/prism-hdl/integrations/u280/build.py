#!/usr/bin/env python3
"""Build the PRISM bitstream for the Alveo U280: one 100G port, no host interface.

    python repo/prism-hdl/integrations/u280/build.py [--rs-fec off] [--out DIR]

The OpenNIC shell is checked out at its pinned commit under build/cache; the
implementation (build.tcl) writes its checkpoints, reports and, when the
routed design meets timing, prism_u280.bit to the output directory
(build/u280/rs-fec-on or rs-fec-off by default). RS-FEC of the link must match
the far end: the switch port or NIC the card is cabled to.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_support import (
    bounded_integer,
    build_environment,
    prepare_open_nic,
    repository_root,
    resolve_vivado,
    run_vivado,
    short_build_root,
    verify_vivado_version,
)

STAGES = ("synth", "place", "route", "bitstream")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--rs-fec", choices=("on", "off"), default="on")
    parser.add_argument("--out", type=Path, help="output directory")
    parser.add_argument("--stop", choices=STAGES, default="bitstream", help="last stage")
    parser.add_argument(
        "--incremental",
        type=Path,
        help="routed checkpoint of an earlier build to place and route incrementally from",
    )
    parser.add_argument("--threads", type=bounded_integer(1, 32), default=4)
    parser.add_argument("--vivado", help="Vivado executable or installation directory")
    parser.add_argument("--license-file", action="append", dest="license_files")
    # Vivado's IP generation exceeds the Windows path limit below a long
    # checkout path; the build runs on a drive mapped to the repository.
    parser.add_argument("--build-drive", default="O")
    return parser.parse_args(argv)


def tcl_arguments(
    arguments: argparse.Namespace, hdl_root: Path, shell_root: Path, out: Path
) -> list[str]:
    values = [
        str(hdl_root),
        str(shell_root),
        str(out),
        f"RS_FEC:{int(arguments.rs_fec == 'on')}",
        f"@stop:{arguments.stop}",
        f"@threads:{arguments.threads}",
    ]
    if arguments.incremental is not None:
        values.append(f"@incremental:{arguments.incremental.resolve()}")
    return values


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    script_directory = Path(__file__).resolve().parent
    root = repository_root(script_directory)
    shell_root = root / "build" / "cache" / "open-nic-shell"
    out = (arguments.out or root / "build" / "u280" / f"rs-fec-{arguments.rs_fec}").resolve()
    if arguments.incremental is not None and not arguments.incremental.is_file():
        raise SystemExit(f"ERROR: no checkpoint at {arguments.incremental}")
    vivado = resolve_vivado("au280", arguments.vivado)
    verify_vivado_version("au280", vivado)
    prepare_open_nic(shell_root)
    out.mkdir(parents=True, exist_ok=True)
    with short_build_root(root, arguments.build_drive) as short_root:

        def short(path: Path) -> Path:
            return short_root / path.relative_to(root) if path.is_relative_to(root) else path

        run_vivado(
            vivado,
            [
                "-mode",
                "batch",
                "-log",
                str(short(out / "vivado.log")),
                "-journal",
                str(short(out / "vivado.jou")),
                "-source",
                str(short(script_directory / "build.tcl")),
                "-tclargs",
                *tcl_arguments(
                    arguments, short(script_directory.parents[1]), short(shell_root), short(out)
                ),
            ],
            cwd=short(out),
            environment=build_environment(arguments.license_files),
        )
    bitstream = out / "prism_u280.bit"
    if arguments.stop == "bitstream":
        print(f"PRISM U280 bitstream: {bitstream}")
    else:
        print(f"PRISM U280 build stopped after {arguments.stop}: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
