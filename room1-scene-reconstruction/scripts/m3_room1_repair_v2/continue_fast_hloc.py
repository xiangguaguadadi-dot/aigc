#!/usr/bin/env python3
"""Merge completed HLoc match shards and continue COLMAP without recomputation."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pycolmap

HLOC_REPO = Path("/root/scene_recon/repos/Hierarchical-Localization")
sys.path.insert(0, str(HLOC_REPO / "third_party"))
sys.path.insert(0, str(HLOC_REPO))
from hloc import reconstruction

WORKSPACE = Path("/root/scene_recon")
BASE = WORKSPACE / "outputs/room1/m3_repair_v2/base"
IMAGES = BASE / "images"
HLOC = BASE / "hloc_fast_v2"
SPARSE = BASE / "sparse_fast_v2"
SELECTED = BASE / "sparse"
FPS = 6.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def merge_matches() -> Path:
    destination = HLOC / "matches_merged_v2.h5"
    if destination.exists():
        raise RuntimeError(f"refusing existing merged matches: {destination}")
    pair_count = 0
    with h5py.File(destination, "w", libver="latest") as target:
        for index in range(3):
            shard = HLOC / f"matches_shard_{index:02d}.h5"
            with h5py.File(shard, "r", libver="latest") as source:
                for query in source.keys():
                    query_group = target.require_group(query)
                    for reference in source[query].keys():
                        if reference in query_group:
                            raise RuntimeError(f"duplicate pair {query}/{reference}")
                        source.copy(source[query][reference], query_group, name=reference)
                        pair_count += 1
    expected = sum(
        len((HLOC / f"pairs_shard_{index:02d}.txt").read_text(encoding="ascii").splitlines())
        for index in range(3)
    )
    if pair_count != expected:
        raise RuntimeError(f"merged {pair_count} pairs, expected {expected}")
    return destination


def validate(model: pycolmap.Reconstruction) -> dict:
    names = sorted(image.name for image in model.images.values())
    indices = sorted(int(Path(name).stem.split("_")[-1]) for name in names)
    gaps = [(b - a) / FPS for a, b in zip(indices, indices[1:])]
    observations = [
        sum(1 for point in image.points2D if point.has_point3D())
        for image in model.images.values()
    ]
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "input_count": 265,
        "registered_count": model.num_reg_images(),
        "registered_ratio": model.num_reg_images() / 265,
        "max_registered_candidate_gap_seconds": max(gaps, default=0.0),
        "points3D": model.num_points3D(),
        "observations": model.compute_num_observations(),
        "mean_track_length": model.compute_mean_track_length(),
        "mean_observations_per_registered_image": model.compute_mean_observations_per_reg_image(),
        "observations_per_image_min": min(observations, default=0),
        "observations_per_image_median": float(np.median(observations)) if observations else 0.0,
        "mean_reprojection_error_px": model.compute_mean_reprojection_error(),
        "camera_models": [
            {"model": camera.model.name, "params": camera.params.tolist()}
            for camera in model.cameras.values()
        ],
        "unregistered_names": sorted(set(path.name for path in IMAGES.glob("*.jpg")) - set(names)),
    }
    payload["necessary_gate_pass"] = bool(
        payload["registered_ratio"] >= 0.90
        and payload["max_registered_candidate_gap_seconds"] <= 0.50
        and payload["mean_track_length"] >= 3.5
        and payload["mean_reprojection_error_px"] <= 1.5
    )
    return payload


def main() -> None:
    if SPARSE.exists() or SELECTED.exists():
        raise RuntimeError("refusing existing sparse output")
    features = HLOC / "features.h5"
    pairs = HLOC / "pairs.txt"
    if not features.is_file() or not pairs.is_file():
        raise RuntimeError("completed features or pairs missing")
    matches = merge_matches()
    model = reconstruction.main(
        SPARSE,
        IMAGES,
        pairs,
        features,
        matches,
        camera_mode=pycolmap.CameraMode.SINGLE,
        verbose=False,
        image_options={"camera_model": "SIMPLE_RADIAL", "camera_params": "1050,360,640,0"},
        mapper_options={
            "init_min_num_inliers": 50,
            "init_min_tri_angle": 4.0,
            "init_max_reg_trials": 5,
            "abs_pose_min_num_inliers": 20,
            "abs_pose_min_inlier_ratio": 0.15,
            "ba_local_num_images": 10,
            "filter_max_reproj_error": 2.0,
            "filter_min_tri_angle": 1.5,
            "max_reg_trials": 5,
            "random_seed": 0,
        },
    )
    if model is None:
        raise RuntimeError("COLMAP returned no model")
    payload = validate(model)
    validation = HLOC / "validation_v2.json"
    validation.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if not payload["necessary_gate_pass"]:
        raise RuntimeError(f"necessary camera gate failed; see {validation}")
    SELECTED.symlink_to(SPARSE.name, target_is_directory=True)
    checked = [features, matches, validation, SPARSE / "cameras.bin", SPARSE / "images.bin", SPARSE / "points3D.bin"]
    (HLOC / "checksums_v2.sha256").write_text(
        "".join(f"{sha256(path)}  {path}\n" for path in checked), encoding="ascii"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
