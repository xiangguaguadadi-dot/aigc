#!/usr/bin/env python3
"""Retry one numerically degenerate DUSt3R group as smaller subgroups."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys


def numeric_key(path: Path) -> int:
    digits = "".join(filter(str.isdigit, path.name))
    return int(digits) if digits else -1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--group-size", type=int, default=30)
    parser.add_argument("--group-number", type=int, required=True)
    parser.add_argument("--chunks", type=int, default=2)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    os.chdir(args.repo)
    from geomprior.run_dust3r import DUSt3R

    images = sorted(
        (p for p in (args.source / "images").iterdir() if p.is_file()),
        key=numeric_key,
    )
    group_count = (len(images) + args.group_size - 1) // args.group_size
    groups: list[list[str]] = [[] for _ in range(group_count)]
    for index, path in enumerate(images):
        groups[index % group_count].append(path.name)
    names = groups[args.group_number - 1]

    output = args.source / "geomprior"
    old = output / f"_group{args.group_number}"
    if old.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        old.rename(output / f"_group{args.group_number}_failed_numerical_{stamp}")

    chunks = [names[index::args.chunks] for index in range(args.chunks)]
    for index, chunk in enumerate(chunks, 1):
        group_output = output / f"_group{args.group_number}_split{index}"
        group_output.mkdir(parents=True, exist_ok=False)
        print(f"split={index}/{args.chunks} images={len(chunk)}", flush=True)
        DUSt3R(
            str(args.source / "images"), str(group_output),
            str(args.checkpoint), chunk, False,
        )


if __name__ == "__main__":
    main()
