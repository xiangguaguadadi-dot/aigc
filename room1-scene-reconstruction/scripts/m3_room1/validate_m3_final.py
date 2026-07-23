#!/usr/bin/env python3
import hashlib
import json
import stat
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path("/root/scene_recon")
M3 = ROOT / "outputs/room1/m3"
VALIDATION = M3 / "review/validation"
EXPECTED_SOURCE = "2e6964a3270f69a4ac04ae7a0055d3f5418df97d5cd97166428a0ddb2422c74e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checksum_file(root: Path) -> int:
    checksum_file = root / "checksums.sha256"
    count = 0
    for line in checksum_file.read_text(encoding="ascii").splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise AssertionError(f"checksum failure: {path}")
        count += 1
    if count == 0:
        raise AssertionError(f"empty checksum file: {checksum_file}")
    return count


def main() -> None:
    output = VALIDATION / "final_m3_validation.json"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    required = {
        "full": ["static_scene_full.glb", "static_scene_full.ply", "static_collision_full.glb", "camera_poses.json", "scale_calibration.json", "coordinate_transform.json", "scene_manifest.json", "checksums.sha256"],
        "asset_ready": ["static_scene_asset_ready.glb", "static_scene_asset_ready.ply", "static_collision_asset_ready.glb", "camera_poses.json", "scale_calibration.json", "coordinate_transform.json", "removal_report.json", "scene_manifest.json", "checksums.sha256"],
    }
    for variant, names in required.items():
        for name in names:
            path = M3 / variant / name
            if not path.is_file() or path.stat().st_size <= 0:
                raise AssertionError(f"missing required artifact: {path}")
    if sha256(ROOT / "data/room1/source/wechat_room1_20260722.mp4") != EXPECTED_SOURCE:
        raise AssertionError("source video checksum mismatch")
    removal = json.loads((M3 / "remove_instances.json").read_text(encoding="ascii"))
    if removal.get("remove_instances") != []:
        raise AssertionError("removal authority changed")

    pairs = [
        ("static_scene_full.glb", "static_scene_asset_ready.glb"),
        ("static_scene_full.ply", "static_scene_asset_ready.ply"),
        ("static_collision_full.glb", "static_collision_asset_ready.glb"),
        ("camera_poses.json", "camera_poses.json"),
        ("coordinate_transform.json", "coordinate_transform.json"),
        ("scale_calibration.json", "scale_calibration.json"),
    ]
    pair_hashes = {}
    for full_name, asset_name in pairs:
        full_path, asset_path = M3 / "full" / full_name, M3 / "asset_ready" / asset_name
        if sha256(full_path) != sha256(asset_path):
            raise AssertionError(f"variant artifact mismatch: {full_name}")
        pair_hashes[full_name] = sha256(full_path)
    scale = json.loads((M3 / "full/scale_calibration.json").read_text(encoding="ascii"))
    if abs(scale["uniform_scale_meters_per_colmap_unit"] - 0.24019853045911085) > 1e-15 or scale["calibrated_width_meters"] != 0.7:
        raise AssertionError("scale contract failed")

    imports = {}
    for variant in ("full", "asset_ready"):
        report = json.loads((VALIDATION / f"blender_import_{variant}.json").read_text(encoding="ascii"))
        main = report["main_import"]
        if main["bounds_validation"] != "PASS" or main["maximum_bounds_error_meters"] > main["bounds_tolerance_meters"]:
            raise AssertionError(f"Blender bounds validation failed: {variant}")
        if main["vertex_count"] <= 0 or main["face_count"] <= 0 or report["collision_import"]["face_count"] <= 0:
            raise AssertionError(f"empty Blender import: {variant}")
        imports[variant] = report
        manifest = json.loads((M3 / variant / "scene_manifest.json").read_text(encoding="ascii"))
        if manifest["variant"] != variant or manifest["source_video_sha256"] != EXPECTED_SOURCE:
            raise AssertionError(f"manifest mismatch: {variant}")
    if imports["full"]["main_import"]["canonical_ply_bounds_meters"] != imports["asset_ready"]["main_import"]["canonical_ply_bounds_meters"]:
        raise AssertionError("canonical variant PLY bounds differ")

    render_checks = []
    for frame in ("frame_000005.png", "frame_000030.png", "frame_000060.png"):
        full_path, asset_path = M3 / "full/renders" / frame, M3 / "asset_ready/renders" / frame
        with Image.open(full_path) as full_image, Image.open(asset_path) as asset_image:
            full = np.asarray(full_image)
            asset = np.asarray(asset_image)
            if not np.array_equal(full, asset) or not np.any(full):
                raise AssertionError(f"render pixels invalid: {frame}")
        comparison = M3 / "comparison_renders" / frame
        if not comparison.is_file() or comparison.stat().st_size <= 0:
            raise AssertionError(f"missing comparison render: {comparison}")
        render_checks.append({"frame": frame, "full_sha256": sha256(full_path), "asset_ready_sha256": sha256(asset_path), "pixel_identical": True})

    checksum_counts = {variant: verify_checksum_file(M3 / variant) for variant in required}
    for number in range(41, 50):
        matches = list((ROOT / "logs/m3_room1").glob(f"{number:03d}_*.log"))
        if len(matches) != 1 or stat.S_IMODE(matches[0].stat().st_mode) != 0o444:
            raise AssertionError(f"immutable log validation failed: {number:03d}")
    normalization = json.loads((VALIDATION / "glb_axis_normalization.json").read_text(encoding="ascii"))
    backup = Path(normalization["backup"])
    if not backup.is_dir() or not any(backup.rglob("*")):
        raise AssertionError("log-044 backup missing")
    for required_review in (M3 / "removable_candidates.json", M3 / "removable_candidates.csv", M3 / "review/instances/numbered_instance_review_sheet.jpg", VALIDATION / "geometry_difference_report.json", VALIDATION / "render_comparison_report.json", VALIDATION / "execution_environment_audit.json", ROOT / "M3_ROOM1_REPORT.md"):
        if not required_review.is_file() or required_review.stat().st_size <= 0:
            raise AssertionError(f"missing review/final artifact: {required_review}")
    mask_count = len(list((M3 / "review/instances/masks").rglob("*.png")))
    numbered_count = len(list((M3 / "review/instances/numbered_reviews").glob("*.jpg")))
    if mask_count <= 0 or numbered_count <= 0:
        raise AssertionError("instance multi-view review is incomplete")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "status": "PASS",
        "required_artifacts_valid": True,
        "checksums_valid": True,
        "checksum_entry_counts": checksum_counts,
        "variant_artifacts_byte_identical": pair_hashes,
        "render_checks": render_checks,
        "blender_bounds_validation": {variant: imports[variant]["main_import"]["maximum_bounds_error_meters"] for variant in imports},
        "scale_validation": "PASS",
        "remove_instances": [],
        "instance_mask_count": mask_count,
        "numbered_review_count": numbered_count,
        "preserved_backup": str(backup),
        "m4_assets_generated": False,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
