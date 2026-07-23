#!/usr/bin/env python3
"""Fast, versioned HLoc/COLMAP reconstruction for room1 repair v2."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
import h5py
import numpy as np
import pycolmap
import torch

from hloc import extract_features, match_features, reconstruction


WORKSPACE = Path("/root/scene_recon")
BASE = WORKSPACE / "outputs/room1/m3_repair_v2/base"
INPUT_IMAGES = BASE / "keyframes_v3_strict/images"
IMAGES = BASE / "images"
HLOC = BASE / "hloc_fast_v1"
SPARSE_ATTEMPT = BASE / "sparse_fast_v1"
SELECTED_SPARSE = BASE / "sparse"
FPS = 6.0
FEATURE_WORKERS = 2
MATCH_WORKERS = 3
TEMPORAL_WINDOW = 12
APPEARANCE_TOP_K = 10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def descriptor(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"cannot read {path}")
    value = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    value -= value.mean()
    norm = float(np.linalg.norm(value))
    return value.reshape(-1) / norm if norm > 1e-6 else np.zeros(value.size, np.float32)


def prepare() -> tuple[list[Path], Path, list[Path]]:
    paths = sorted(INPUT_IMAGES.glob("frame_*.jpg"))
    if len(paths) != 265:
        raise RuntimeError(f"expected 265 strict keyframes, found {len(paths)}")
    for guarded in [IMAGES, HLOC, SPARSE_ATTEMPT, SELECTED_SPARSE]:
        if guarded.exists():
            raise RuntimeError(f"refusing existing output: {guarded}")
    IMAGES.mkdir()
    HLOC.mkdir()
    for source in paths:
        destination = IMAGES / source.name
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)

    desc = np.stack([descriptor(path) for path in paths])
    similarities = desc @ desc.T
    pairs: set[tuple[int, int]] = set()
    for first in range(len(paths)):
        for second in range(first + 1, min(len(paths), first + TEMPORAL_WINDOW + 1)):
            pairs.add((first, second))
        remote = [index for index in range(len(paths)) if abs(index - first) > TEMPORAL_WINDOW]
        remote.sort(key=lambda index: (-float(similarities[first, index]), index))
        for second in remote[:APPEARANCE_TOP_K]:
            pairs.add(tuple(sorted((first, second))))
    ordered = sorted(pairs)
    pairs_path = HLOC / "pairs.txt"
    pairs_path.write_text(
        "".join(f"{paths[a].name} {paths[b].name}\n" for a, b in ordered), encoding="ascii"
    )
    pair_lines = pairs_path.read_text(encoding="ascii").splitlines()
    pair_shards: list[Path] = []
    for worker in range(MATCH_WORKERS):
        shard = HLOC / f"pairs_shard_{worker:02d}.txt"
        shard.write_text("\n".join(pair_lines[worker::MATCH_WORKERS]) + "\n", encoding="ascii")
        pair_shards.append(shard)
    image_names = [path.name for path in paths]
    for worker in range(FEATURE_WORKERS):
        (HLOC / f"images_shard_{worker:02d}.txt").write_text(
            "\n".join(image_names[worker::FEATURE_WORKERS]) + "\n", encoding="ascii"
        )
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "input_count": len(paths),
        "temporal_window": TEMPORAL_WINDOW,
        "appearance_top_k": APPEARANCE_TOP_K,
        "pair_count": len(ordered),
        "feature_workers": FEATURE_WORKERS,
        "match_workers": MATCH_WORKERS,
        "pairs_sha256": sha256(pairs_path),
    }
    (HLOC / "preparation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return paths, pairs_path, pair_shards


def feature_worker(index: int) -> None:
    conf = copy.deepcopy(extract_features.confs["superpoint_aachen"])
    extract_features.main(
        conf,
        IMAGES,
        image_list=HLOC / f"images_shard_{index:02d}.txt",
        feature_path=HLOC / f"features_shard_{index:02d}.h5",
        as_half=True,
        overwrite=False,
    )


def match_worker(index: int) -> None:
    conf = copy.deepcopy(match_features.confs["superglue"])
    conf["model"]["weights"] = "indoor"
    match_features.main(
        conf,
        HLOC / f"pairs_shard_{index:02d}.txt",
        HLOC / "features.h5",
        matches=HLOC / f"matches_shard_{index:02d}.h5",
        overwrite=False,
    )


def run_workers(mode: str, count: int) -> None:
    processes = [
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), f"--{mode}-worker", str(i)])
        for i in range(count)
    ]
    failures = [process.wait() for process in processes]
    if any(failures):
        raise RuntimeError(f"{mode} workers failed: {failures}")


def merge_h5(shards: list[Path], destination: Path, expected: int) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing existing merge destination: {destination}")
    seen: set[str] = set()
    with h5py.File(destination, "w", libver="latest") as target:
        for shard in shards:
            with h5py.File(shard, "r", libver="latest") as source:
                for name in source.keys():
                    if name in seen:
                        raise RuntimeError(f"duplicate H5 group {name}")
                    source.copy(name, target)
                    seen.add(name)
    if len(seen) != expected:
        raise RuntimeError(f"merged {len(seen)} H5 groups, expected {expected}")


def validate(model: pycolmap.Reconstruction, input_count: int, pairs_path: Path) -> dict:
    registered = model.num_reg_images()
    names = sorted(image.name for image in model.images.values())
    candidate_indices = [int(Path(name).stem.split("_")[-1]) for name in names]
    gaps = [(b - a) / FPS for a, b in zip(candidate_indices, candidate_indices[1:])]
    observations = []
    for image in model.images.values():
        observations.append(sum(1 for point in image.points2D if point.has_point3D()))
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "input_count": input_count,
        "registered_count": registered,
        "registered_ratio": registered / input_count,
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
        "pairs_sha256": sha256(pairs_path),
    }
    payload["necessary_gate_pass"] = bool(
        payload["registered_ratio"] >= 0.90
        and payload["max_registered_candidate_gap_seconds"] <= 0.50
        and payload["mean_track_length"] >= 3.5
        and payload["mean_reprojection_error_px"] <= 1.5
    )
    return payload


def main() -> None:
    paths, pairs_path, pair_shards = prepare()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    run_workers("feature", FEATURE_WORKERS)
    merge_h5(
        [HLOC / f"features_shard_{i:02d}.h5" for i in range(FEATURE_WORKERS)],
        HLOC / "features.h5",
        len(paths),
    )
    run_workers("match", MATCH_WORKERS)
    expected_matches = sum(len(path.read_text(encoding="ascii").splitlines()) for path in pair_shards)
    merge_h5(
        [HLOC / f"matches_shard_{i:02d}.h5" for i in range(MATCH_WORKERS)],
        HLOC / "matches.h5",
        expected_matches,
    )
    model = reconstruction.main(
        SPARSE_ATTEMPT,
        IMAGES,
        pairs_path,
        HLOC / "features.h5",
        HLOC / "matches.h5",
        camera_mode=pycolmap.CameraMode.SINGLE,
        verbose=False,
        image_options={
            "camera_model": "SIMPLE_RADIAL",
            "camera_params": "1050,360,640,0",
        },
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
    validation = validate(model, len(paths), pairs_path)
    validation_path = HLOC / "validation.json"
    validation_path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
    if not validation["necessary_gate_pass"]:
        raise RuntimeError(f"necessary camera gate failed; see {validation_path}")
    SELECTED_SPARSE.symlink_to(SPARSE_ATTEMPT.name, target_is_directory=True)
    checksums = [HLOC / "features.h5", HLOC / "matches.h5", validation_path]
    (HLOC / "checksums.sha256").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksums), encoding="ascii"
    )
    print(json.dumps(validation, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-worker", type=int)
    parser.add_argument("--match-worker", type=int)
    args = parser.parse_args()
    if args.feature_worker is not None:
        feature_worker(args.feature_worker)
    elif args.match_worker is not None:
        match_worker(args.match_worker)
    else:
        main()
