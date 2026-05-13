#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from cocotb_tools.runner import get_runner
except ModuleNotFoundError:
    from cocotb.runner import get_runner


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    print("[main.py] Running:")
    print("  " + " ".join(str(x) for x in cmd))

    subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=True,
    )


def traffic_gen_command(traffic_gen_root: Path) -> list[str]:
    """
    Prefer uv locally because traffic-gen has its own pyproject.toml and uv.lock.

    Inside Docker we set MINISHARP_USE_SYSTEM_TRAFFIC_GEN=1, so this uses the
    already-installed system Python packages and avoids mounted .venv/libpython
    problems.
    """
    traffic_gen_main = traffic_gen_root / "main.py"

    if not traffic_gen_main.exists():
        raise SystemExit(f"Missing traffic-gen entrypoint: {traffic_gen_main}")

    use_system_python = os.environ.get("MINISHARP_USE_SYSTEM_TRAFFIC_GEN", "0") == "1"

    if use_system_python:
        return [
            sys.executable,
            str(traffic_gen_main),
        ]

    if shutil.which("uv") is not None:
        return [
            "uv",
            "run",
            "--project",
            str(traffic_gen_root),
            "python",
            str(traffic_gen_main),
        ]

    return [
        sys.executable,
        str(traffic_gen_main),
    ]


def generate_passthrough_input_pcap(repo_root: Path) -> Path:
    """
    Generate the passthrough smoke-test input PCAP by calling repo/traffic-gen.

    Expected traffic:
      8 reduction packets
      expected_contributions = 4

    Expected output after RTL reduction:
      chunk 0: 1 + 2 + 3 + 4 = 10 = 0x0a
      chunk 1: 5 + 6 + 7 + 8 = 26 = 0x1a
    """
    rtl_root = repo_root / "rtl"
    traffic_gen_root = repo_root / "traffic-gen"

    traces_dir = rtl_root / Path(os.environ.get("MINISHARP_TRACES_DIR", "verification/traces"))
    traces_dir.mkdir(parents=True, exist_ok=True)

    pcap_path = traces_dir / "passthrough_in.pcap"
    manifest_path = traces_dir / "passthrough_in.csv"

    cmd = traffic_gen_command(traffic_gen_root)

    cmd += [
        "pcap-generate",
        "--output",
        str(pcap_path),
        "--manifest",
        str(manifest_path),

        "--reduction-packets",
        "8",
        "--normal-packets",
        "0",

        "--expected-contributions",
        "4",
        "--chunk-id-start",
        "0",
        "--flow-id-start",
        "0",

        "--reduce-operation",
        "SUM",
        "--collective-op",
        "REDUCE",
        "--dtype",
        "INT8",

        "--reduction-payload-size",
        "64",

        "--vary-sources",
        "--source-hosts",
        "4",

        "--no-shuffle",
        "--inter-packet-gap",
        "1e-6",
        "--seed",
        "1",
    ]

    run_cmd(cmd, cwd=rtl_root)

    print(f"[main.py] Generated input PCAP through traffic-gen: {pcap_path}")
    return pcap_path


def sv_sources(rtl_root: Path) -> list[str]:
    """
    Source order matters:
      package first,
      components,
      DUT,
      vendor PCAP modules,
      simulation top.
    """
    ordered = [
        rtl_root / "src" / "mini_sharp_pkg.sv",
        rtl_root / "src" / "components" / "eth_parser.sv",
        rtl_root / "src" / "components" / "minisharp_parser.sv",

        rtl_root / "src" / "math" / "uint8_to_fp32.sv",
        rtl_root / "src" / "math" / "fp32_to_uint8_sat.sv",
        rtl_root / "src" / "math" / "fp32_adder.sv",
        rtl_root / "src" / "math" / "fp32_alu.sv",

        rtl_root / "src" / "components" / "reduction_input_converter.sv",
        rtl_root / "src" / "components" / "reduction_output_converter.sv",
        rtl_root / "src" / "components" / "reduction_op_decoder.sv",
        rtl_root / "src" / "components" / "collective_engine.sv",

        rtl_root / "src" / "top" / "mini_sharp_switch_core.sv",
        rtl_root / "vendor" / "pcap_parse.sv",
        rtl_root / "vendor" / "pcap_dumper.sv",
        rtl_root / "src" / "tb" / "tb_mini_sharp_switch_core.sv",
    ]

    missing = [path for path in ordered if not path.exists()]
    if missing:
        for path in missing:
            print(f"[main.py] Missing source: {path}")
        raise SystemExit("Missing SystemVerilog source files.")

    return [str(path) for path in ordered]


def prepare_build_dir_links(build_dir: Path, traces_dir: Path) -> None:
    """
    The simulator runs from build_dir.

    The vendor PCAP modules use relative paths:
      traces/passthrough_in.pcap
      traces/passthrough_out.pcap

    Therefore build_dir/traces must resolve to rtl/traces.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)

    link_path = build_dir / "traces"

    if link_path.is_symlink():
        link_path.unlink()
    elif link_path.exists():
        if link_path.is_dir():
            shutil.rmtree(link_path)
        else:
            link_path.unlink()

    try:
        link_path.symlink_to(traces_dir, target_is_directory=True)
        print(f"[main.py] Linked {link_path} -> {traces_dir}")
    except OSError:
        # Fallback. This is less ideal because output PCAP may stay in build_dir,
        # but on Linux/Docker/WSL the symlink path should normally work.
        shutil.copytree(traces_dir, link_path)
        print(f"[main.py] Symlink failed; copied traces to {link_path}")


def run_passthrough(args: argparse.Namespace) -> None:
    verification_root = Path(__file__).resolve().parent
    rtl_root = verification_root.parent
    repo_root = rtl_root.parent

    os.chdir(rtl_root)

    traces_dir = rtl_root / Path(os.environ.get("MINISHARP_TRACES_DIR", "verification/traces"))
    traces_dir.mkdir(parents=True, exist_ok=True)

    output_pcap = traces_dir / "passthrough_out.pcap"

    if output_pcap.exists():
        try:
            output_pcap.unlink()
        except PermissionError as exc:
            raise SystemExit(
                "\n"
                f"ERROR: cannot remove existing output PCAP:\n"
                f"  {output_pcap}\n\n"
                "This usually means the file is open in Wireshark or locked by Windows/OneDrive.\n"
                "Close Wireshark and remove it with:\n\n"
                "  powershell.exe -NoProfile -Command "
                f"\"Remove-Item -LiteralPath '{output_pcap}' -Force\"\n\n"
                "Or remove the entire traces directory from WSL with:\n\n"
                "  powershell.exe -NoProfile -Command "
                "\"Remove-Item -LiteralPath '$(wslpath -w traces)' -Recurse -Force\"\n"
            ) from exc

    generate_passthrough_input_pcap(repo_root)

    build_dir = Path(
        os.environ.get("MINISHARP_BUILD_DIR", "/tmp/mini-sharp-rtl/sim_build")
    ).resolve()

    prepare_build_dir_links(build_dir, traces_dir)

    runner = get_runner("verilator")

    build_args = [
        "--timing",
        "-Wall",
        "-Wno-WIDTH",
        "-Wno-UNOPTFLAT",
        "-Wno-CASEINCOMPLETE",
        "-Wno-DECLFILENAME",
        "-Wno-UNUSEDPARAM",
        "-Wno-UNUSEDSIGNAL",
        "-Wno-BLKSEQ",
        "-Wno-REALCVT",
        "-Wno-UNSIGNED",
        "-Wno-VARHIDDEN",
        "-Wno-IMPORTSTAR",
        "-Wno-WIDTHCONCAT",
        "-Wno-TIMESCALEMOD",
        "-Wno-EOFNEWLINE",
    ]

    if args.waves:
        build_args.extend(["--trace", "--trace-structs"])

    runner.build(
        sources=sv_sources(rtl_root),
        hdl_toplevel="tb_mini_sharp_switch_core",
        build_dir=str(build_dir),
        build_args=build_args,
        always=args.always,
        clean=args.clean_build,
    )

    # Recreate link after build in case build directory was cleaned/recreated.
    prepare_build_dir_links(build_dir, traces_dir)

    # Ensure the verification package is importable by cocotb (tests live in
    # rtl/verification/tests). Add verification directory to Python
    # search path and PYTHONPATH so cocotb can import `tests`.
    verification_dir = rtl_root / "verification"
    if str(verification_dir) not in sys.path:
        sys.path.insert(0, str(verification_dir))

    os.environ["PYTHONPATH"] = (
        str(verification_dir)
        + os.pathsep
        + os.environ.get("PYTHONPATH", "")
    )

    runner.test(
        hdl_toplevel="tb_mini_sharp_switch_core",
        test_module="tests.test_passthrough_pcap",
        test_dir=str(build_dir),
    )

    print(f"[main.py] Build dir:   {build_dir}")
    print(f"[main.py] Input PCAP:  {traces_dir / 'passthrough_in.pcap'}")
    print(f"[main.py] Output PCAP: {traces_dir / 'passthrough_out.pcap'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mini-Sharp RTL simulation runner")

    parser.add_argument(
        "--test",
        choices=["passthrough"],
        default="passthrough",
        help="Test to run.",
    )

    parser.add_argument(
        "--waves",
        action="store_true",
        help="Enable Verilator waveform tracing.",
    )

    parser.add_argument(
        "--always",
        action="store_true",
        default=True,
        help="Always rebuild the simulation.",
    )

    parser.add_argument(
        "--no-always",
        dest="always",
        action="store_false",
        help="Do not force rebuild.",
    )

    parser.add_argument(
        "--clean-build",
        action="store_true",
        help="Clean build directory before building.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.test == "passthrough":
        run_passthrough(args)
    else:
        raise SystemExit(f"Unsupported test: {args.test}")


if __name__ == "__main__":
    main()
