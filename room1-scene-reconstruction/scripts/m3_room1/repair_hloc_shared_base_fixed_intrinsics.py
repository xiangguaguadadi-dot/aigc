#!/usr/bin/env python3
import collections
import hashlib
import json
import shutil
import sqlite3
import struct
import subprocess
from datetime import datetime
from pathlib import Path

import pycolmap

from hloc.triangulation import estimation_and_geometric_verification


WORKSPACE = Path("/root/scene_recon")
BASE = WORKSPACE / "outputs/room1/m3/base"
IMAGES = BASE / "images"
HLOC = BASE / "hloc"
SPARSE = BASE / "sparse"
FAILED_SPARSE = HLOC / "failed_mapper_021_sparse"
PAIRS = HLOC / "pairs.txt"
FOCAL_EVALUATION = HLOC / "focal_grid_evaluation.json"
FAILED_VALIDATION = HLOC / "camera_reconstruction_validation_failed_021.json"
VALIDATION = HLOC / "camera_reconstruction_validation.json"
FOCAL_PIXELS = 1050.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    subprocess.run(
        [str(WORKSPACE / "scripts/m3_room1/base_once_guard.py"), "verify"], check=True
    )
    focal_record = json.loads(FOCAL_EVALUATION.read_text(encoding="ascii"))
    if float(focal_record["selected_focal_pixels"]) != FOCAL_PIXELS:
        raise SystemExit("focal-grid result does not match the fixed repair focal")
    if FAILED_SPARSE.exists():
        raise SystemExit(f"fixed-intrinsics repair was already attempted: {FAILED_SPARSE}")
    required = [
        SPARSE / "database.db",
        SPARSE / "cameras.bin",
        SPARSE / "images.bin",
        SPARSE / "points3D.bin",
        VALIDATION,
        PAIRS,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"initial failed mapper evidence is incomplete: {missing}")

    initial_validation = json.loads(VALIDATION.read_text(encoding="ascii"))
    if initial_validation.get("registered_image_count", 0) >= 10:
        raise SystemExit("initial mapper state is not the expected failed fragment")
    shutil.move(str(SPARSE), str(FAILED_SPARSE))
    shutil.move(str(VALIDATION), str(FAILED_VALIDATION))
    SPARSE.mkdir(parents=True, exist_ok=False)
    database_path = SPARSE / "database.db"
    shutil.copy2(FAILED_SPARSE / "database.db", database_path)

    connection = sqlite3.connect(database_path)
    before_camera = connection.execute(
        "SELECT camera_id, model, width, height, prior_focal_length, params FROM cameras"
    ).fetchone()
    connection.execute(
        "UPDATE cameras SET model=?, width=?, height=?, params=?, prior_focal_length=? WHERE camera_id=?",
        (0, 720, 1280, struct.pack("ddd", FOCAL_PIXELS, 360.0, 640.0), 1, before_camera[0]),
    )
    connection.execute("DELETE FROM two_view_geometries")
    connection.commit()
    connection.close()

    estimation_and_geometric_verification(database_path, PAIRS, verbose=True)
    connection = sqlite3.connect(database_path)
    geometry_rows = list(
        connection.execute("SELECT rows, config FROM two_view_geometries")
    )
    camera_row = connection.execute(
        "SELECT camera_id, model, width, height, prior_focal_length, params FROM cameras"
    ).fetchone()
    connection.close()
    camera_params = list(struct.unpack("ddd", camera_row[5]))

    options_dict = {
        "multiple_models": False,
        "max_num_models": 1,
        "min_model_size": 10,
        "init_image_id1": 17,
        "init_image_id2": 25,
        "init_num_trials": 200,
        "random_seed": 0,
        "ba_refine_focal_length": False,
        "ba_refine_principal_point": False,
        "ba_refine_extra_params": False,
        "mapper": {
            "init_min_num_inliers": 50,
            "init_min_tri_angle": 4.0,
            "abs_pose_min_num_inliers": 15,
            "abs_pose_min_inlier_ratio": 0.1,
            "abs_pose_refine_focal_length": False,
            "abs_pose_refine_extra_params": False,
            "ba_local_num_images": 10,
            "max_reg_trials": 5,
        },
        "triangulation": {"ignore_two_view_tracks": False},
    }
    options = pycolmap.IncrementalPipelineOptions(options_dict)
    models_path = SPARSE / "models"
    models_path.mkdir(parents=True, exist_ok=False)
    reconstructions = pycolmap.incremental_mapping(
        database_path,
        IMAGES,
        models_path,
        options=options,
    )
    if not reconstructions:
        raise SystemExit("fixed-intrinsics mapper produced no reconstruction")
    selected_index, model = max(
        reconstructions.items(), key=lambda item: item[1].num_reg_images()
    )
    model.write(SPARSE)

    all_names = sorted(path.name for path in IMAGES.glob("frame_*.jpg"))
    registered_names = sorted(image.name for image in model.images.values())
    unregistered_names = sorted(set(all_names) - set(registered_names))
    missing_references = [name for name in registered_names if not (IMAGES / name).is_file()]
    final_camera = next(iter(model.cameras.values()))
    registered_ratio = len(registered_names) / len(all_names)
    config_counts = collections.Counter(int(config) for _, config in geometry_rows)
    validation = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_id": "room1_shared_base_v1",
        "repair_scope": "same frames, pairs, features, matches, and base ID; fixed-intrinsics mapper repair",
        "initial_failure_log": str(WORKSPACE / "logs/m3_room1/021_hloc_colmap_shared_base.log"),
        "initial_failure_archive": str(FAILED_SPARSE),
        "initial_registered_image_count": initial_validation["registered_image_count"],
        "initial_sparse_point_count": initial_validation["sparse_point_count"],
        "focal_grid_evaluation": str(FOCAL_EVALUATION),
        "focal_grid_sha256": sha256(FOCAL_EVALUATION),
        "selected_focal_pixels": FOCAL_PIXELS,
        "principal_point_pixels": [360.0, 640.0],
        "database_camera_before": {
            "camera_id": before_camera[0],
            "model_id": before_camera[1],
            "width": before_camera[2],
            "height": before_camera[3],
            "prior_focal_length": before_camera[4],
            "params": list(struct.unpack("dddd", before_camera[5])),
        },
        "database_camera_after": {
            "camera_id": camera_row[0],
            "model_id": camera_row[1],
            "width": camera_row[2],
            "height": camera_row[3],
            "prior_focal_length": camera_row[4],
            "params": camera_params,
        },
        "geometry_pair_count": len(geometry_rows),
        "geometry_config_counts": dict(sorted(config_counts.items())),
        "geometry_pairs_at_least_15_inliers": sum(rows >= 15 for rows, _ in geometry_rows),
        "mapper_options": options_dict,
        "selected_model_index": int(selected_index),
        "input_image_count": len(all_names),
        "registered_image_count": len(registered_names),
        "registered_ratio": registered_ratio,
        "sparse_point_count": model.num_points3D(),
        "camera_count": model.num_cameras(),
        "final_camera": {
            "model": final_camera.model.name,
            "width": final_camera.width,
            "height": final_camera.height,
            "params": [float(value) for value in final_camera.params],
        },
        "missing_image_references": missing_references,
        "unregistered_images": unregistered_names,
        "database_sha256": sha256(database_path),
        "cameras_bin_sha256": sha256(SPARSE / "cameras.bin"),
        "images_bin_sha256": sha256(SPARSE / "images.bin"),
        "points3d_bin_sha256": sha256(SPARSE / "points3D.bin"),
    }
    VALIDATION.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(validation, indent=2, sort_keys=True))
    print(f"validation_sha256={sha256(VALIDATION)}")
    if model.num_cameras() != 1:
        raise SystemExit(f"expected one camera, found {model.num_cameras()}")
    if final_camera.model.name != "SIMPLE_PINHOLE":
        raise SystemExit(f"unexpected final camera model: {final_camera.model.name}")
    if abs(float(final_camera.params[0]) - FOCAL_PIXELS) > 1e-6:
        raise SystemExit(f"fixed focal drifted: {final_camera.params[0]}")
    if model.num_points3D() <= 1000:
        raise SystemExit(f"insufficient sparse points: {model.num_points3D()}")
    if missing_references:
        raise SystemExit(f"missing image references: {missing_references}")
    if registered_ratio < 0.80:
        raise SystemExit(f"registered ratio below 0.80: {registered_ratio:.6f}")


if __name__ == "__main__":
    main()
