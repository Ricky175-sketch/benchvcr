"""Console interface for the offline demo and cassette validation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .cassette import validate_cassette
from .demo import run_demo
from .errors import BenchVCRError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchvcr",
        description="Record, strictly replay, and fault-inject text protocols.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run the hardware-free demo")
    demo.add_argument(
        "--output-dir",
        type=Path,
        default=Path("demo-output"),
        help="artifact directory",
    )
    demo.add_argument("--seed", type=int, default=42, help="deterministic fault seed")
    cassette = subparsers.add_parser("cassette", help="inspect cassettes")
    cassette_commands = cassette.add_subparsers(dest="cassette_command", required=True)
    validate = cassette_commands.add_parser("validate", help="validate JSONL v1")
    validate.add_argument("path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo":
            run_demo(args.output_dir, seed=args.seed)
            return 0
        if args.command == "cassette" and args.cassette_command == "validate":
            cassette = validate_cassette(args.path)
            print(f"OK {args.path} ({len(cassette.exchanges)} exchanges)")
            return 0
        raise AssertionError("unhandled CLI command")
    except (BenchVCRError, OSError) as exc:
        print(f"benchvcr: error: {exc}", file=sys.stderr)
        return 2
