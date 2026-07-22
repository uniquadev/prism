#!/usr/bin/env python3
"""Parse verification commands and dispatch PRISM test suites."""

from __future__ import annotations

import argparse
import os

from suites import (
    ALL_SUITE_NAMES,
    SUITE_NAMES,
    build,
    clean,
    exclusive_run,
    lint,
    run_suite,
    show_environment,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", *SUITE_NAMES), default="all")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--lint-only", action="store_true")
    parser.add_argument("--environment", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument(
        "--xml-results",
        action="store_true",
        help="retain Cocotb JUnit XML under build/prism-hdl/results",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ["PRISM_XML_RESULTS"] = "1" if args.xml_results else "0"
    if args.environment:
        show_environment()
    else:
        with exclusive_run():
            if args.clean:
                clean()
            elif args.build_only:
                build()
            elif args.lint_only:
                lint()
            else:
                selected = ALL_SUITE_NAMES if args.suite == "all" else (args.suite,)
                print(f"[prism] suites={','.join(selected)}")
                for suite in selected:
                    run_suite(suite)


if __name__ == "__main__":
    main()
