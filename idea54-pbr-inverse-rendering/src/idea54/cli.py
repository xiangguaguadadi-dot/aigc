from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .adapters.trellis2 import adapt_explicit_dump
from .errors import Idea54Error
from .experiment import make_synthetic_suite, run_paired, run_suite
from .renderer import renderer_available
from .report import generate_report
from .schema import validate_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idea54")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    validate = sub.add_parser("validate")
    validate.add_argument("bundle")
    synthetic = sub.add_parser("make-synthetic")
    synthetic.add_argument("--config", required=True)
    synthetic.add_argument("--output", required=True)
    paired = sub.add_parser("run-paired")
    paired.add_argument("--bundle", required=True)
    paired.add_argument("--config", required=True)
    paired.add_argument("--output", required=True)
    suite = sub.add_parser("run-suite")
    suite.add_argument("--bundles", required=True)
    suite.add_argument("--config", required=True)
    suite.add_argument("--output", required=True)
    report = sub.add_parser("report")
    report.add_argument("--runs", required=True)
    report.add_argument("--output", required=True)
    adapt = sub.add_parser("adapt-trellis")
    adapt.add_argument("--input", required=True)
    adapt.add_argument("--camera", required=True)
    adapt.add_argument("--observation", required=True)
    adapt.add_argument("--mask", required=True)
    adapt.add_argument("--upstream-commit", required=True)
    adapt.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            available, reason = renderer_available()
            print(json.dumps({"version": __version__, "cuda_renderer_available": available, "reason": reason}, indent=2))
            return 0 if available else 2
        if args.command == "validate":
            print(json.dumps(validate_bundle(args.bundle), indent=2))
        elif args.command == "make-synthetic":
            print("\n".join(str(path) for path in make_synthetic_suite(args.config, args.output)))
        elif args.command == "run-paired":
            print(json.dumps(run_paired(args.bundle, args.config, args.output), indent=2))
        elif args.command == "run-suite":
            print(json.dumps(run_suite(args.bundles, args.config, args.output), indent=2))
        elif args.command == "report":
            print(generate_report(args.runs, args.output))
        elif args.command == "adapt-trellis":
            print(adapt_explicit_dump(args.input, args.camera, args.observation, args.mask, args.output, args.upstream_commit))
        return 0
    except Idea54Error as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
