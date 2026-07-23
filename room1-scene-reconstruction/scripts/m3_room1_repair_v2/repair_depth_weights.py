#!/usr/bin/env python3
"""Replace PlanarGS's scale-dependent all-zero depth weights."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import statistics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geomprior", type=Path, required=True)
    parser.add_argument("--align-log", type=Path, required=True)
    args = parser.parse_args()

    current_group: str | None = None
    losses: dict[str, float] = {}
    for line in args.align_log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"Start aligning depth (\S+):", line)
        if match:
            current_group = match.group(1)
            continue
        match = re.match(r"loss\s*=\s*([0-9.eE+-]+)", line)
        if match and current_group:
            losses[current_group] = float(match.group(1))
            current_group = None
    if not losses:
        raise SystemExit("no group alignment losses found")

    weights_path = args.geomprior / "depth_weights.json"
    original_path = args.geomprior / "depth_weights.all_zero_original.json"
    if not original_path.exists():
        shutil.copy2(weights_path, original_path)
    weights = json.loads(weights_path.read_text(encoding="utf-8"))
    median_loss = statistics.median(losses.values())

    group_weights = {
        group: max(0.15, min(0.80, math.exp(-loss / median_loss)))
        for group, loss in losses.items()
    }
    assigned: set[str] = set()
    for group, group_weight in group_weights.items():
        depth_dir = args.geomprior / group / "depth"
        for path in depth_dir.glob("*.npy"):
            if path.stem in weights:
                weights[path.stem] = group_weight
                assigned.add(path.stem)
    missing = sorted(set(weights) - assigned)
    if missing:
        raise SystemExit(f"registered frames without a group weight: {missing[:10]}")
    if not all(float(value) > 0 for value in weights.values()):
        raise SystemExit("non-positive weights remain")

    weights_path.write_text(json.dumps(weights, indent=2) + "\n", encoding="utf-8")
    report = {
        "method": "exp(-group_alignment_loss / median_group_alignment_loss)",
        "reason": "COLMAP has arbitrary global scale; fixed absolute thresholds made all weights zero.",
        "registered_frame_count": len(weights),
        "median_group_alignment_loss": median_loss,
        "group_losses": losses,
        "group_weights": group_weights,
        "minimum_weight": min(weights.values()),
        "median_weight": statistics.median(weights.values()),
        "maximum_weight": max(weights.values()),
        "original_weights_backup": str(original_path),
    }
    report_path = args.geomprior / "depth_weight_repair_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
