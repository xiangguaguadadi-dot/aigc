#!/usr/bin/env python3
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import trimesh


ROOT = Path("/root/scene_recon")
M3 = ROOT / "outputs/room1/m3"
FULL = M3 / "full"
ASSET = M3 / "asset_ready"
VALIDATION = M3 / "review/validation"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hardlink_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing existing backup: {destination}")
    os.link(source, destination)


def normalized_export(source: Path, destination: Path) -> dict:
    loaded = trimesh.load(source, force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.vertices) <= 0 or len(loaded.faces) <= 0:
        raise AssertionError(f"invalid source GLB: {source}")
    source_vertices = np.asarray(loaded.vertices).copy()
    transform = np.eye(4)
    transform[:3, :3] = np.asarray([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    if abs(np.linalg.det(transform[:3, :3]) - 1.0) > 1e-12:
        raise AssertionError("GLB storage conversion must be right-handed")
    loaded.apply_transform(transform)
    converted = np.asarray(loaded.vertices)
    expected = source_vertices[:, [0, 2, 1]].copy()
    expected[:, 2] *= -1.0
    maximum_error = float(np.max(np.abs(converted - expected)))
    if maximum_error > 1e-9:
        raise AssertionError(f"unexpected GLB pre-rotation error: {maximum_error}")
    loaded.export(destination)
    return {
        "vertex_count": int(len(loaded.vertices)),
        "face_count": int(len(loaded.faces)),
        "maximum_pre_rotation_error": maximum_error,
        "source_bounds": [source_vertices.min(axis=0).tolist(), source_vertices.max(axis=0).tolist()],
        "stored_glb_bounds": [converted.min(axis=0).tolist(), converted.max(axis=0).tolist()],
    }


def main() -> None:
    main_full = FULL / "static_scene_full.glb"
    main_asset = ASSET / "static_scene_asset_ready.glb"
    collision_full = FULL / "static_collision_full.glb"
    collision_asset = ASSET / "static_collision_asset_ready.glb"
    metrics_path = VALIDATION / "geometry_export_metrics.json"
    failed_report = VALIDATION / "blender_import_full.json"
    failed_renders = FULL / "renders"
    report_path = VALIDATION / "glb_axis_normalization.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite {report_path}")
    for first, second in ((main_full, main_asset), (collision_full, collision_asset)):
        if sha256(first) != sha256(second):
            raise AssertionError(f"variant GLBs differ before normalization: {first.name}")

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%z")
    backup = M3 / "review/backups" / f"log_043_blender_axis_mismatch_{stamp}"
    for source in (main_full, main_asset, collision_full, collision_asset, metrics_path):
        hardlink_backup(source, backup / source.relative_to(ROOT))
    if failed_report.is_file():
        hardlink_backup(failed_report, backup / failed_report.relative_to(ROOT))
    if failed_renders.is_dir():
        for source in sorted(failed_renders.glob("*.png")):
            hardlink_backup(source, backup / source.relative_to(ROOT))

    main_temp = FULL / ".static_scene_full.axis_normalized.glb"
    collision_temp = FULL / ".static_collision_full.axis_normalized.glb"
    if main_temp.exists() or collision_temp.exists():
        raise FileExistsError("refusing stale GLB normalization temporary file")
    main_stats = normalized_export(main_full, main_temp)
    collision_stats = normalized_export(collision_full, collision_temp)
    os.replace(main_temp, main_full)
    os.replace(collision_temp, collision_full)
    main_asset.unlink()
    collision_asset.unlink()
    os.link(main_full, main_asset)
    os.link(collision_full, collision_asset)

    if failed_renders.is_dir():
        for path in failed_renders.glob("*.png"):
            path.unlink()
        failed_renders.rmdir()
    if failed_report.exists():
        failed_report.unlink()

    metrics = json.loads(metrics_path.read_text(encoding="ascii"))
    metrics.update({
        "full_glb_sha256": sha256(main_full),
        "collision_glb_sha256": sha256(collision_full),
        "asset_ready_main_geometry_byte_identical": sha256(main_full) == sha256(main_asset),
        "asset_ready_collision_geometry_byte_identical": sha256(collision_full) == sha256(collision_asset),
        "glb_storage_axis_conversion": "canonical Blender (x,y,z) stored as glTF (x,z,-y)",
        "glb_blender_import_coordinate_system": "right-handed Z-up blender_world",
        "glb_axis_normalized_at": datetime.now().astimezone().isoformat(),
    })
    metrics_temp = metrics_path.with_suffix(".json.tmp")
    metrics_temp.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="ascii")
    os.replace(metrics_temp, metrics_path)

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "reason": "Blender glTF import applies (x,y,z)->(x,-z,y); pre-rotate stored GLB coordinates to preserve canonical Z-up blender_world",
        "backup": str(backup),
        "backup_preserves_log_041_glbs_and_failed_log_043_renders": True,
        "storage_pre_rotation": [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]],
        "rotation_determinant": 1.0,
        "ply_changed": False,
        "camera_poses_changed": False,
        "scale_changed": False,
        "main": {**main_stats, "sha256": sha256(main_full)},
        "collision": {**collision_stats, "sha256": sha256(collision_full)},
        "asset_ready_main_byte_identical": sha256(main_full) == sha256(main_asset),
        "asset_ready_collision_byte_identical": sha256(collision_full) == sha256(collision_asset),
    }
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
