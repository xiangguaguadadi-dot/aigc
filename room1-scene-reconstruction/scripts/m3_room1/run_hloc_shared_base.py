#!/usr/bin/env python3
import copy
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import h5py
import pycolmap
import torch

from hloc import extract_features, match_features, reconstruction


WORKSPACE = Path("/root/scene_recon")
BASE = WORKSPACE / "outputs/room1/m3/base"
IMAGES = BASE / "images"
HLOC = BASE / "hloc"
SPARSE = BASE / "sparse"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    subprocess.run(
        [str(WORKSPACE / "scripts/m3_room1/base_once_guard.py"), "verify"],
        check=True,
    )
    pairs_path = HLOC / "pairs.txt"
    image_paths = sorted(IMAGES.glob("frame_*.jpg"))
    if len(image_paths) != 93 or not pairs_path.is_file():
        raise SystemExit("shared frame or pair preparation is incomplete")
    guarded_outputs = [
        HLOC / "feats-superpoint-n4096-r1024.h5",
        HLOC / "matches-superglue-indoor.h5",
        SPARSE / "database.db",
        SPARSE / "cameras.bin",
    ]
    existing = [str(path) for path in guarded_outputs if path.exists()]
    if existing:
        raise SystemExit(f"refusing to rerun shared HLoc base; outputs exist: {existing}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")

    feature_conf = copy.deepcopy(extract_features.confs["superpoint_aachen"])
    matcher_conf = copy.deepcopy(match_features.confs["superglue"])
    matcher_conf["model"]["weights"] = "indoor"
    feature_path = extract_features.main(
        feature_conf,
        IMAGES,
        HLOC,
        as_half=True,
        overwrite=False,
    )
    matches_path = HLOC / "matches-superglue-indoor.h5"
    match_features.main(
        matcher_conf,
        pairs_path,
        feature_path,
        matches=matches_path,
        overwrite=False,
    )
    model = reconstruction.main(
        SPARSE,
        IMAGES,
        pairs_path,
        feature_path,
        matches_path,
        camera_mode=pycolmap.CameraMode.SINGLE,
        verbose=True,
        image_options={"camera_model": "SIMPLE_RADIAL"},
        mapper_options={
            "multiple_models": False,
            "min_num_matches": 15,
            "min_model_size": 10,
            "random_seed": 0,
        },
    )
    if model is None:
        raise SystemExit("PyCOLMAP returned no reconstruction")

    registered_names = sorted(image.name for image in model.images.values())
    all_names = sorted(path.name for path in image_paths)
    missing_references = [name for name in registered_names if not (IMAGES / name).is_file()]
    unregistered_names = sorted(set(all_names) - set(registered_names))
    camera_records = []
    for camera_id, camera in sorted(model.cameras.items()):
        camera_records.append(
            {
                "camera_id": int(camera_id),
                "model": camera.model.name,
                "width": int(camera.width),
                "height": int(camera.height),
                "params": [float(value) for value in camera.params],
            }
        )
    with h5py.File(feature_path, "r") as feature_file:
        feature_image_count = len(feature_file.keys())
        total_keypoints = sum(int(feature_file[name]["keypoints"].shape[0]) for name in feature_file.keys())
    with h5py.File(matches_path, "r") as match_file:
        matched_pair_count = len(match_file.keys())

    registered_ratio = len(registered_names) / len(all_names)
    validation = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_id": "room1_shared_base_v1",
        "device": torch.cuda.get_device_name(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "feature_config": feature_conf,
        "matcher_config": matcher_conf,
        "camera_mode": "SINGLE",
        "camera_model": "SIMPLE_RADIAL",
        "mapper_options": {
            "multiple_models": False,
            "min_num_matches": 15,
            "min_model_size": 10,
            "random_seed": 0,
        },
        "input_image_count": len(all_names),
        "feature_image_count": feature_image_count,
        "total_keypoints": total_keypoints,
        "matched_pair_count": matched_pair_count,
        "registered_image_count": len(registered_names),
        "registered_ratio": registered_ratio,
        "sparse_point_count": model.num_points3D(),
        "camera_count": model.num_cameras(),
        "cameras": camera_records,
        "missing_image_references": missing_references,
        "unregistered_images": unregistered_names,
        "features_sha256": sha256(feature_path),
        "matches_sha256": sha256(matches_path),
        "cameras_bin_sha256": sha256(SPARSE / "cameras.bin"),
        "images_bin_sha256": sha256(SPARSE / "images.bin"),
        "points3d_bin_sha256": sha256(SPARSE / "points3D.bin"),
    }
    validation_path = HLOC / "camera_reconstruction_validation.json"
    validation_path.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    if feature_image_count != len(all_names):
        raise SystemExit("feature file does not contain every shared frame")
    if matched_pair_count <= 0:
        raise SystemExit("match file is empty")
    if model.num_cameras() != 1:
        raise SystemExit(f"expected one shared camera, found {model.num_cameras()}")
    if model.num_points3D() <= 1000:
        raise SystemExit(f"insufficient sparse points: {model.num_points3D()}")
    if missing_references:
        raise SystemExit(f"registered image references are missing: {missing_references}")
    if registered_ratio < 0.80:
        raise SystemExit(f"registered ratio below 0.80: {registered_ratio:.6f}")
    print(json.dumps(validation, indent=2, sort_keys=True))
    print(f"validation_sha256={sha256(validation_path)}")


if __name__ == "__main__":
    main()
