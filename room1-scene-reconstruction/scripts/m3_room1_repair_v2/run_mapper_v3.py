#!/usr/bin/env python3
"""Run pycolmap 3.13 mapper on the already verified HLoc database."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pycolmap

BASE = Path("/root/scene_recon/outputs/room1/m3_repair_v2/base")
IMAGES = BASE / "images"
DATABASE = BASE / "sparse_fast_v2/database.db"
MODELS = BASE / "sparse_mapper_v3_models"
SELECTED_MODEL = BASE / "sparse_fast_v3"
SELECTED_LINK = BASE / "sparse"
REPORT = BASE / "hloc_fast_v2/validation_v3.json"
FPS = 6.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    for path in [MODELS, SELECTED_MODEL, SELECTED_LINK, REPORT]:
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"refusing existing output: {path}")
    if not DATABASE.is_file():
        raise RuntimeError(f"database missing: {DATABASE}")
    options = pycolmap.IncrementalPipelineOptions()
    options.multiple_models = False
    options.min_model_size = 10
    options.min_num_matches = 15
    options.random_seed = 0
    options.ba_refine_focal_length = True
    options.ba_refine_principal_point = False
    options.ba_refine_extra_params = True
    options.mapper.init_min_num_inliers = 50
    options.mapper.init_min_tri_angle = 4.0
    options.mapper.init_max_reg_trials = 5
    options.mapper.abs_pose_min_num_inliers = 20
    options.mapper.abs_pose_min_inlier_ratio = 0.15
    options.mapper.ba_local_num_images = 10
    options.mapper.filter_max_reproj_error = 2.0
    options.mapper.filter_min_tri_angle = 1.5
    options.mapper.max_reg_trials = 5
    options.mapper.random_seed = 0
    options.triangulation.ignore_two_view_tracks = False
    MODELS.mkdir(parents=True, exist_ok=False)
    models = pycolmap.incremental_mapping(
        database_path=str(DATABASE),
        image_path=str(IMAGES),
        output_path=str(MODELS),
        options=options,
    )
    if not models:
        raise RuntimeError("mapper returned no model")
    model = max(models.values(), key=lambda value: value.num_reg_images())
    SELECTED_MODEL.mkdir(parents=True, exist_ok=False)
    model.write(SELECTED_MODEL)
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
        "mapper_options": options.todict(),
    }
    payload["necessary_gate_pass"] = bool(
        payload["registered_ratio"] >= 0.90
        and payload["max_registered_candidate_gap_seconds"] <= 0.50
        and payload["mean_track_length"] >= 3.5
        and payload["mean_reprojection_error_px"] <= 1.5
    )
    REPORT.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    if not payload["necessary_gate_pass"]:
        raise RuntimeError(f"necessary camera gate failed; see {REPORT}")
    SELECTED_LINK.symlink_to(SELECTED_MODEL.name, target_is_directory=True)
    files = [REPORT, SELECTED_MODEL / "cameras.bin", SELECTED_MODEL / "images.bin", SELECTED_MODEL / "points3D.bin"]
    (BASE / "hloc_fast_v2/checksums_v3.sha256").write_text(
        "".join(f"{sha256(path)}  {path}\n" for path in files), encoding="ascii"
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
