#!/usr/bin/env python3
"""Run PlanarGS/DUSt3R geometric-prior groups in isolated parallel processes."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime


def numeric_key(path: Path) -> int:
    digits = "".join(filter(str.isdigit, path.name))
    return int(digits) if digits else -1


def run_group(script: Path, repo: Path, source: Path, output: Path,
              checkpoint: Path, group_number: int, names: list[str]) -> int:
    group_dir = output / f"_group{group_number}"
    group_dir.mkdir(parents=True, exist_ok=False)
    log_path = output / f"group_{group_number:02d}.log"
    retry = 1
    while log_path.exists():
        log_path = output / f"group_{group_number:02d}_retry_{retry}.log"
        retry += 1
    command = [
        sys.executable, str(script), "--worker", "--repo", str(repo),
        "--source", str(source), "--output", str(group_dir),
        "--checkpoint", str(checkpoint), "--names", *names,
    ]
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    return proc.returncode


def worker(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(args.repo))
    os.chdir(args.repo)
    from geomprior.run_dust3r import DUSt3R

    DUSt3R(
        str(args.source / "images"), str(args.output), str(args.checkpoint),
        args.names, False,
    )


def parent(args: argparse.Namespace) -> None:
    images = sorted(
        (p for p in (args.source / "images").iterdir() if p.is_file()),
        key=numeric_key,
    )
    group_count = (len(images) + args.group_size - 1) // args.group_size
    groups: list[list[str]] = [[] for _ in range(group_count)]
    for index, path in enumerate(images):
        groups[index % group_count].append(path.name)

    args.output.mkdir(parents=True, exist_ok=args.resume)
    script = Path(__file__).resolve()
    print(f"images={len(images)} groups={group_count} workers={args.workers}", flush=True)
    pending: list[tuple[int, list[str]]] = []
    for number, names in enumerate(groups, 1):
        group_dir = args.output / f"_group{number}"
        complete = group_dir / "depth"
        if complete.is_dir() and len(list(complete.glob("*.npy"))) == len(names):
            print(f"group={number} status=skip_complete", flush=True)
            continue
        if group_dir.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = args.output / f"_group{number}_failed_{stamp}"
            group_dir.rename(backup)
            print(f"group={number} partial_backup={backup.name}", flush=True)
        pending.append((number, names))

    failures: list[int] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                run_group, script, args.repo, args.source, args.output,
                args.checkpoint, number, names,
            ): number
            for number, names in pending
        }
        for future in concurrent.futures.as_completed(futures):
            number = futures[future]
            rc = future.result()
            print(f"group={number} rc={rc}", flush=True)
            if rc:
                failures.append(number)
    if failures:
        raise SystemExit(f"failed groups: {failures}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--group-size", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--names", nargs="*")
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.worker:
        worker(parsed)
    else:
        parent(parsed)
