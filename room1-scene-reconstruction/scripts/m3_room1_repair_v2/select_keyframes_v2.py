#!/usr/bin/env python3
"""Deterministically select quality keyframes from a uniformly sampled pool."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile_rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(len(values), dtype=np.float64)
    return ranks / max(1, len(values) - 1)


def load_metrics(paths: list[Path]) -> list[dict[str, float | int | str]]:
    records: list[dict[str, float | int | str]] = []
    previous_small: np.ndarray | None = None
    for index, path in enumerate(paths):
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise RuntimeError(f"cannot read {path}")
        small = cv2.resize(gray, (90, 160), interpolation=cv2.INTER_AREA)
        sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())
        brightness = float(small.mean())
        dark_fraction = float(np.mean(small <= 8))
        bright_fraction = float(np.mean(small >= 247))
        exposure_penalty = abs(brightness - 127.5) / 127.5 + dark_fraction + bright_fraction
        if previous_small is None:
            temporal_difference = 1.0
            correlation = 0.0
        else:
            temporal_difference = float(np.mean(cv2.absdiff(small, previous_small)) / 255.0)
            a = small.astype(np.float32).reshape(-1)
            b = previous_small.astype(np.float32).reshape(-1)
            a -= a.mean()
            b -= b.mean()
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            correlation = float(np.dot(a, b) / denom) if denom > 1e-8 else 1.0
        previous_small = small
        records.append(
            {
                "candidate_index": index + 1,
                "name": path.name,
                "sharpness": sharpness,
                "brightness": brightness,
                "dark_fraction": dark_fraction,
                "bright_fraction": bright_fraction,
                "exposure_penalty": exposure_penalty,
                "temporal_difference": temporal_difference,
                "previous_frame_correlation": correlation,
            }
        )
    return records


def select(records: list[dict[str, float | int | str]], target: int, max_gap: int) -> set[int]:
    sharpness = np.asarray([r["sharpness"] for r in records], dtype=np.float64)
    exposure = -np.asarray([r["exposure_penalty"] for r in records], dtype=np.float64)
    novelty = np.asarray([r["temporal_difference"] for r in records], dtype=np.float64)
    score = 0.55 * percentile_rank(sharpness) + 0.25 * percentile_rank(exposure) + 0.20 * percentile_rank(novelty)
    for index, value in enumerate(score):
        records[index]["quality_score"] = float(value)

    selected: set[int] = {0, len(records) - 1}
    for start in range(0, len(records), max_gap):
        stop = min(len(records), start + max_gap)
        best = max(range(start, stop), key=lambda idx: (score[idx], -idx))
        selected.add(best)
    ranked = sorted(range(len(records)), key=lambda idx: (-score[idx], idx))
    for index in ranked:
        if len(selected) >= target:
            break
        selected.add(index)
    while True:
        ordered = sorted(selected)
        violation = next(((a, b) for a, b in zip(ordered, ordered[1:]) if b - a > max_gap), None)
        if violation is None:
            break
        first, second = violation
        stop = min(second, first + max_gap + 1)
        best = max(range(first + 1, stop), key=lambda idx: (score[idx], -idx))
        selected.add(best)
    return selected


def render_sheet(paths: list[Path], selected: set[int], destination: Path) -> None:
    thumb_w, thumb_h, cols = 120, 213, 20
    rows = math.ceil(len(paths) / cols)
    sheet = np.full((rows * (thumb_h + 24), cols * thumb_w, 3), 24, dtype=np.uint8)
    for index, path in enumerate(paths):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"cannot read {path}")
        thumb = cv2.resize(image, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        color = (40, 210, 40) if index in selected else (40, 40, 220)
        cv2.rectangle(thumb, (0, 0), (thumb_w - 1, thumb_h - 1), color, 3)
        row, col = divmod(index, cols)
        y, x = row * (thumb_h + 24), col * thumb_w
        sheet[y : y + thumb_h, x : x + thumb_w] = thumb
        cv2.putText(sheet, f"{index + 1:03d}", (x + 4, y + thumb_h + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if not cv2.imwrite(str(destination), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90]):
        raise RuntimeError(f"cannot write {destination}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=6.0)
    parser.add_argument("--target", type=int, default=240)
    parser.add_argument("--max-gap-frames", type=int, default=3)
    args = parser.parse_args()

    paths = sorted(args.candidate_dir.glob("frame_*.jpg"))
    if len(paths) != 279:
        raise SystemExit(f"expected 279 candidates, found {len(paths)}")
    if args.output_dir.exists():
        raise SystemExit(f"refusing existing output directory: {args.output_dir}")
    if not (220 <= args.target <= 260):
        raise SystemExit("target must be within 220..260")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    image_dir = args.output_dir / "images"
    image_dir.mkdir()

    records = load_metrics(paths)
    selected = select(records, args.target, args.max_gap_frames)
    for index, (record, source) in enumerate(zip(records, paths)):
        is_selected = index in selected
        record["selected"] = is_selected
        record["timestamp_seconds"] = index / args.fps
        if is_selected:
            destination = image_dir / source.name
            try:
                os.link(source, destination)
            except OSError:
                shutil.copy2(source, destination)

    selected_indices = sorted(selected)
    gaps = [b - a for a, b in zip(selected_indices, selected_indices[1:])]
    max_gap_frames = max(gaps, default=0)
    if max_gap_frames > args.max_gap_frames:
        raise RuntimeError(f"selection gap {max_gap_frames} exceeds {args.max_gap_frames}")

    csv_path = args.output_dir / "keyframe_quality.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    sheet_path = args.output_dir / "keyframe_review.jpg"
    render_sheet(paths, selected, sheet_path)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "candidate_dir": str(args.candidate_dir),
        "candidate_count": len(paths),
        "candidate_fps": args.fps,
        "selected_count": len(selected),
        "selection_policy": "coverage floor plus deterministic sharpness/exposure/temporal-novelty ranking",
        "score_weights": {"sharpness": 0.55, "exposure": 0.25, "temporal_novelty": 0.20},
        "max_selected_gap_candidate_frames": max_gap_frames,
        "max_selected_gap_seconds": max_gap_frames / args.fps,
        "selected_names": [paths[index].name for index in selected_indices],
        "quality_csv_sha256": sha256(csv_path),
        "review_sheet_sha256": sha256(sheet_path),
    }
    manifest_path = args.output_dir / "keyframe_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum_path = args.output_dir / "checksums.sha256"
    with checksum_path.open("w", encoding="ascii") as handle:
        for path in sorted(p for p in args.output_dir.rglob("*") if p.is_file() and p != checksum_path):
            handle.write(f"{sha256(path)}  {path.relative_to(args.output_dir).as_posix()}\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
