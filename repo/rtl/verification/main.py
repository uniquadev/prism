
#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Lorenzo Cipolletti

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


def run_cmd(cmd, cwd=None):
    print("[runner] Running:")
    print("  " + " ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd is not None else None, check=True)


def traffic_gen_command(traffic_gen_root):
    traffic_gen_main = traffic_gen_root / "main.py"

    if not traffic_gen_main.exists():
        raise SystemExit(f"Missing traffic-gen entrypoint: {traffic_gen_main}")

    use_system_python = os.environ.get("MINISHARP_USE_SYSTEM_TRAFFIC_GEN", "0") == "1"

    if use_system_python:
        return [sys.executable, str(traffic_gen_main)]

    if shutil.which("uv") is not None:
        return [
            "uv",
            "run",
            "--project",
            str(traffic_gen_root),
            "python",
            str(traffic_gen_main),
        ]

    return [sys.executable, str(traffic_gen_main)]


def traces_dir_from_env(rtl_root):
    return rtl_root / Path(os.environ.get("MINISHARP_TRACES_DIR", "verification/traces"))


def build_dir_from_env():
    return Path(os.environ.get("MINISHARP_BUILD_DIR", "/tmp/mini-sharp-rtl/sim_build"))


def remove_old_output(traces_dir):
    output_pcap = traces_dir / "passthrough_out.pcap"
    if output_pcap.exists():
        output_pcap.unlink()


def prepare_build_dir_links(build_dir, traces_dir):
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
        print(f"[runner] Linked {link_path} -> {traces_dir}")
    except OSError:
        shutil.copytree(traces_dir, link_path)
        print(f"[runner] Symlink failed; copied traces to {link_path}")


def generate_reduction_test_pcap(repo_root, traces_dir, dtype):
    rtl_root = repo_root / "rtl"
    traffic_gen_root = repo_root / "traffic-gen"

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
        dtype,

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
    print(f"[runner] Generated {dtype} input PCAP: {pcap_path}")
    return pcap_path


def install_custom_input_pcap(input_pcap, traces_dir):
    if not input_pcap.exists():
        raise SystemExit(f"Input PCAP not found: {input_pcap}")

    traces_dir.mkdir(parents=True, exist_ok=True)

    dst = traces_dir / "passthrough_in.pcap"
    shutil.copy2(input_pcap, dst)

    manifest = traces_dir / "passthrough_in.csv"
    if manifest.exists():
        manifest.unlink()

    print(f"[runner] Installed custom input PCAP: {input_pcap} -> {dst}")
    return dst


def sv_sources(rtl_root):
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
            print(f"[runner] Missing source: {path}")
        raise SystemExit("Missing SystemVerilog source files.")

    return [str(path) for path in ordered]


def build_sim(rtl_root, build_dir, waves, always, clean_build):
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

    if waves:
        build_args.extend(["--trace", "--trace-structs"])

    runner.build(
        sources=sv_sources(rtl_root),
        hdl_toplevel="tb_mini_sharp_switch_core",
        build_dir=str(build_dir),
        build_args=build_args,
        always=always,
        clean=clean_build,
    )

    return runner


def configure_pythonpath(rtl_root):
    verification_dir = rtl_root / "verification"

    if str(verification_dir) not in sys.path:
        sys.path.insert(0, str(verification_dir))

    os.environ["PYTHONPATH"] = (
        str(verification_dir)
        + os.pathsep
        + os.environ.get("PYTHONPATH", "")
    )


def run_cocotb_entrypoint(runner, build_dir, test_module):
    runner.test(
        hdl_toplevel="tb_mini_sharp_switch_core",
        test_module=test_module,
        test_dir=str(build_dir),
    )


def run_regression_suite(args):
    verification_root = Path(__file__).parent
    rtl_root = verification_root.parent
    repo_root = rtl_root.parent

    os.chdir(rtl_root)

    traces_dir = traces_dir_from_env(rtl_root)
    build_dir = build_dir_from_env()

    prepare_build_dir_links(build_dir, traces_dir)

    runner = build_sim(
        rtl_root=rtl_root,
        build_dir=build_dir,
        waves=args.waves,
        always=args.always,
        clean_build=args.clean_build,
    )

    prepare_build_dir_links(build_dir, traces_dir)
    configure_pythonpath(rtl_root)

    # INT8 regression.
    remove_old_output(traces_dir)
    generate_reduction_test_pcap(repo_root, traces_dir, dtype="INT8")

    run_cocotb_entrypoint(
        runner=runner,
        build_dir=build_dir,
        test_module="tests.test_passthrough_pcap",
    )

    # FP32 regression.
    remove_old_output(traces_dir)
    generate_reduction_test_pcap(repo_root, traces_dir, dtype="FP32")

    run_cocotb_entrypoint(
        runner=runner,
        build_dir=build_dir,
        test_module="tests.test_reduce_sum_fp32_pcap",
    )

    print(f"[runner] Build dir:   {build_dir}")
    print(f"[runner] Last input:  {traces_dir / 'passthrough_in.pcap'}")
    print(f"[runner] Last output: {traces_dir / 'passthrough_out.pcap'}")


def run_custom_pcap(args):
    verification_root = Path(__file__).parent
    rtl_root = verification_root.parent

    os.chdir(rtl_root)

    if args.input_pcap is None:
        raise SystemExit("--input-pcap is required for --test run_pcap")

    input_pcap = Path(args.input_pcap).absolute()
    output_pcap = Path(args.output_pcap or "out.pcap").absolute()

    traces_dir = traces_dir_from_env(rtl_root)
    build_dir = build_dir_from_env()

    remove_old_output(traces_dir)
    install_custom_input_pcap(input_pcap, traces_dir)
    prepare_build_dir_links(build_dir, traces_dir)

    runner = build_sim(
        rtl_root=rtl_root,
        build_dir=build_dir,
        waves=args.waves,
        always=args.always,
        clean_build=args.clean_build,
    )

    prepare_build_dir_links(build_dir, traces_dir)
    configure_pythonpath(rtl_root)

    run_cocotb_entrypoint(
        runner=runner,
        build_dir=build_dir,
        test_module="tests.run_pcap_driver",
    )

    produced = traces_dir / "passthrough_out.pcap"

    if not produced.exists():
        raise SystemExit(f"Expected DUT output PCAP not found: {produced}")

    output_pcap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced, output_pcap)

    print(f"[runner] Build dir:       {build_dir}")
    print(f"[runner] Custom input:    {input_pcap}")
    print(f"[runner] Raw output PCAP: {produced}")
    print(f"[runner] Copied output:   {output_pcap}")


def build_parser():
    parser = argparse.ArgumentParser(description="Mini-Sharp RTL simulation runner")

    parser.add_argument(
        "--test",
        choices=["tests", "passthrough", "run_pcap"],
        default="tests",
        help="Flow to run.",
    )

    parser.add_argument("--input-pcap", help="Input PCAP for --test run_pcap.")
    parser.add_argument("--output-pcap", help="Output PCAP path for --test run_pcap.")
    parser.add_argument("--waves", action="store_true", help="Enable waveform tracing.")

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


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.test in ("tests", "passthrough"):
        run_regression_suite(args)
    elif args.test == "run_pcap":
        run_custom_pcap(args)
    else:
        raise SystemExit(f"Unsupported test: {args.test}")


if __name__ == "__main__":
    main()
