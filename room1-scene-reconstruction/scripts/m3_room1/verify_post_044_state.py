#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path("/root/scene_recon")
M3 = ROOT / "outputs/room1/m3"
EXPECTED_VIDEO_SHA256 = "2e6964a3270f69a4ac04ae7a0055d3f5418df97d5cd97166428a0ddb2422c74e"
EXPECTED_SCALE = 0.24019853045911085


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_equal(first: Path, second: Path, label: str) -> str:
    first_hash, second_hash = sha256(first), sha256(second)
    if first_hash != second_hash:
        raise AssertionError(f"{label} differs: {first} != {second}")
    return first_hash


def main() -> None:
    output = M3 / "review/validation/post_044_state_verification.json"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    video = ROOT / "data/room1/source/wechat_room1_20260722.mp4"
    if sha256(video) != EXPECTED_VIDEO_SHA256:
        raise AssertionError("source video checksum mismatch")
    removal = json.loads((M3 / "remove_instances.json").read_text(encoding="ascii"))
    if removal.get("remove_instances") != []:
        raise AssertionError("removal authority is not the required empty list")
    normalization = json.loads((M3 / "review/validation/glb_axis_normalization.json").read_text(encoding="ascii"))
    backup = Path(normalization["backup"])
    if not backup.is_dir() or not any(backup.rglob("*")):
        raise AssertionError("log-044 backup is missing or empty")

    full = M3 / "full"
    asset = M3 / "asset_ready"
    pairs = {
        "main_glb": (full / "static_scene_full.glb", asset / "static_scene_asset_ready.glb"),
        "collision_glb": (full / "static_collision_full.glb", asset / "static_collision_asset_ready.glb"),
        "main_ply": (full / "static_scene_full.ply", asset / "static_scene_asset_ready.ply"),
        "camera_poses": (full / "camera_poses.json", asset / "camera_poses.json"),
        "coordinate_transform": (full / "coordinate_transform.json", asset / "coordinate_transform.json"),
        "scale_calibration": (full / "scale_calibration.json", asset / "scale_calibration.json"),
    }
    identical = {label: require_equal(*paths, label) for label, paths in pairs.items()}
    scale = json.loads((full / "scale_calibration.json").read_text(encoding="ascii"))
    if abs(float(scale["uniform_scale_meters_per_colmap_unit"]) - EXPECTED_SCALE) > 1e-15:
        raise AssertionError("corrected sofa scale is not preserved")
    if float(scale["calibrated_width_meters"]) != 0.7:
        raise AssertionError("sofa anchor is not calibrated to 0.7 m")
    for variant in ("full", "asset_ready"):
        render_root = M3 / variant / "renders"
        report = M3 / "review/validation" / f"blender_import_{variant}.json"
        if render_root.exists() or report.exists():
            raise AssertionError(f"fresh Blender outputs already exist for {variant}")

    exporter = ROOT / "scripts/m3_room1/export_metric_variants.py"
    exporter_text = exporter.read_text(encoding="ascii")
    if "gltf_vertices = vertices[:, [0, 2, 1]].copy()" not in exporter_text:
        raise AssertionError("primary exporter does not preserve canonical Blender axes")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "status": "PASS",
        "source_video_sha256": EXPECTED_VIDEO_SHA256,
        "remove_instances": [],
        "uniform_scale_meters_per_colmap_unit": EXPECTED_SCALE,
        "calibrated_sofa_width_meters": 0.7,
        "byte_identical_variant_artifacts": identical,
        "axis_normalization_report": str(M3 / "review/validation/glb_axis_normalization.json"),
        "preserved_backup": str(backup),
        "primary_exporter_sha256": sha256(exporter),
        "rerun_recipe": "export_metric_variants.py now stores canonical Blender coordinates as glTF (x,z,-y); no separate normalization pass is required for a clean rerun",
        "fresh_blender_outputs_absent": True,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
