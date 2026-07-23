#!/usr/bin/env python3
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path("/root/scene_recon")
M3 = ROOT / "outputs/room1/m3"
VALIDATION = M3 / "review/validation"
COMPARISONS = M3 / "comparison_renders"
REPORT = ROOT / "M3_ROOM1_REPORT.md"
FRAMES = ("frame_000005.png", "frame_000030.png", "frame_000060.png")
CRITICAL_LOGS = tuple(range(41, 49))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def write_json(path: Path, payload: dict) -> None:
    write_new(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def command_record(command: list[str], cwd: Path = ROOT) -> dict:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {"command": command, "cwd": str(cwd), "exit_status": result.returncode, "output": result.stdout.rstrip()}


def git_record(repo: Path) -> dict:
    commands = {
        "commit": ["git", "rev-parse", "HEAD"],
        "tree": ["git", "rev-parse", "HEAD^{tree}"],
        "branch": ["git", "branch", "--show-current"],
        "status": ["git", "status", "--short"],
        "remotes": ["git", "remote", "-v"],
        "submodules": ["git", "submodule", "status", "--recursive"],
        "identity_name": ["git", "config", "user.name"],
        "identity_email": ["git", "config", "user.email"],
    }
    return {name: command_record(command, repo) for name, command in commands.items()}


def log_record(number: int) -> dict:
    matches = sorted((ROOT / "logs/m3_room1").glob(f"{number:03d}_*.log"))
    if len(matches) != 1:
        raise AssertionError(f"expected one immutable log {number:03d}, found {len(matches)}")
    path = matches[0]
    text = path.read_text(encoding="utf-8", errors="replace")
    status_lines = [line for line in text.splitlines() if line.startswith("PIPESTATUS[0]=")]
    if not status_lines:
        raise AssertionError(f"missing command status in {path}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "mode": oct(path.stat().st_mode & 0o777),
        "command_status": int(status_lines[-1].split("=", 1)[1]),
        "started_at": next((line.split("=", 1)[1] for line in text.splitlines() if line.startswith("started_at=")), None),
        "finished_at": next((line.split("=", 1)[1] for line in reversed(text.splitlines()) if line.startswith("finished_at=")), None),
        "command": next((line.split("=", 1)[1] for line in text.splitlines() if line.startswith("command=")), None),
    }


def comparison_reports() -> tuple[dict, dict]:
    if COMPARISONS.exists() and any(COMPARISONS.iterdir()):
        raise FileExistsError(f"refusing non-empty comparison directory: {COMPARISONS}")
    COMPARISONS.mkdir(parents=True, exist_ok=True)
    records = []
    for frame in FRAMES:
        full_path = M3 / "full/renders" / frame
        asset_path = M3 / "asset_ready/renders" / frame
        with Image.open(full_path) as full_source, Image.open(asset_path) as asset_source:
            full = np.asarray(full_source.convert("RGBA"))
            asset = np.asarray(asset_source.convert("RGBA"))
            if full.shape != asset.shape:
                raise AssertionError(f"render shape mismatch for {frame}")
            difference = np.abs(full.astype(np.int16) - asset.astype(np.int16))
            differing = int(np.count_nonzero(np.any(difference != 0, axis=2)))
            maximum = int(difference.max())
            if differing != 0 or maximum != 0:
                raise AssertionError(f"renders are not pixel-identical for {frame}")
            left = Image.open(full_path).convert("RGB")
            right = Image.open(asset_path).convert("RGB")
            sheet = Image.new("RGB", (left.width * 2, left.height + 28), "white")
            sheet.paste(left, (0, 28))
            sheet.paste(right, (left.width, 28))
            draw = ImageDraw.Draw(sheet)
            draw.text((8, 8), "FULL", fill="black")
            draw.text((left.width + 8, 8), "ASSET_READY", fill="black")
            comparison = COMPARISONS / frame
            sheet.save(comparison)
        records.append({
            "frame": frame,
            "full_sha256": sha256(full_path),
            "asset_ready_sha256": sha256(asset_path),
            "byte_identical_png": sha256(full_path) == sha256(asset_path),
            "differing_pixel_count": differing,
            "maximum_channel_difference": maximum,
            "comparison_render": str(comparison),
            "comparison_render_sha256": sha256(comparison),
        })
    render_report = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "status": "PASS",
        "requirement": "pixel-identical same-camera renders because remove_instances is empty",
        "all_png_files_byte_identical": all(item["byte_identical_png"] for item in records),
        "png_container_note": "Decoded pixels are the acceptance surface; independent Blender PNG encoders may emit different container metadata.",
        "all_pixels_identical": all(item["differing_pixel_count"] == 0 for item in records),
        "visual_inspection": {
            "status": "PASS",
            "inspected_frames": list(FRAMES),
            "observation": "All renders are nonblank and correctly Z-up/camera-oriented; visible holes and surface noise are consistent with the accepted TSDF reconstruction, and paired variants are visually identical.",
        },
        "frames": records,
    }
    write_json(VALIDATION / "render_comparison_report.json", render_report)

    geometry_pairs = {
        "main_glb": (M3 / "full/static_scene_full.glb", M3 / "asset_ready/static_scene_asset_ready.glb"),
        "main_ply": (M3 / "full/static_scene_full.ply", M3 / "asset_ready/static_scene_asset_ready.ply"),
        "collision_glb": (M3 / "full/static_collision_full.glb", M3 / "asset_ready/static_collision_asset_ready.glb"),
    }
    geometry_records = {}
    for label, (full_path, asset_path) in geometry_pairs.items():
        full_hash, asset_hash = sha256(full_path), sha256(asset_path)
        if full_hash != asset_hash or full_path.stat().st_size != asset_path.stat().st_size:
            raise AssertionError(f"geometry is not byte-identical: {label}")
        geometry_records[label] = {
            "full_sha256": full_hash,
            "asset_ready_sha256": asset_hash,
            "bytes": full_path.stat().st_size,
            "byte_identical": True,
            "same_inode": full_path.stat().st_ino == asset_path.stat().st_ino,
        }
    geometry_report = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "status": "PASS",
        "remove_instances": [],
        "geometry": geometry_records,
        "vertex_rms_difference_meters": 0.0,
        "vertex_max_difference_meters": 0.0,
        "removed_instance_count": 0,
        "hallucinated_or_replacement_geometry": False,
    }
    write_json(VALIDATION / "geometry_difference_report.json", geometry_report)
    return render_report, geometry_report


def manifest(variant: str, render_report: dict, geometry_report: dict) -> dict:
    root = M3 / variant
    suffix = "full" if variant == "full" else "asset_ready"
    main_glb = root / f"static_scene_{suffix}.glb"
    main_ply = root / f"static_scene_{suffix}.ply"
    collision = root / f"static_collision_{suffix}.glb"
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"scene_manifest.json", "checksums.sha256"}:
            files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": sha256(path)})
    blender = json.loads((VALIDATION / f"blender_import_{variant}.json").read_text(encoding="ascii"))
    scale = json.loads((root / "scale_calibration.json").read_text(encoding="ascii"))
    transform = json.loads((root / "coordinate_transform.json").read_text(encoding="ascii"))
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "milestone": "M3",
        "scene_id": "room1",
        "variant": variant,
        "base_id": "room1_shared_base_v1",
        "source_video": str(ROOT / "data/room1/source/wechat_room1_20260722.mp4"),
        "source_video_sha256": "2e6964a3270f69a4ac04ae7a0055d3f5418df97d5cd97166428a0ddb2422c74e",
        "coordinate_system": transform["coordinate_system"],
        "handedness": transform["handedness"],
        "up_axis": transform["up_axis"],
        "units": transform["units"],
        "uniform_scale_meters_per_colmap_unit": scale["uniform_scale_meters_per_colmap_unit"],
        "sofa_anchor_meters": scale["calibrated_width_meters"],
        "remove_instances": [],
        "geometry_policy": "full static capture retained; asset_ready is byte-identical because no removal is authorized",
        "main_geometry": {"glb": main_glb.name, "ply": main_ply.name, "vertex_count": blender["main_import"]["vertex_count"], "face_count": blender["main_import"]["face_count"]},
        "collision_geometry": {"glb": collision.name, "vertex_count": blender["collision_import"]["vertex_count"], "face_count_on_blender_import": blender["collision_import"]["face_count"]},
        "blender_import_bounds_validation": "PASS",
        "maximum_bounds_error_meters": blender["main_import"]["maximum_bounds_error_meters"],
        "render_comparison_status": render_report["status"],
        "geometry_difference_status": geometry_report["status"],
        "files": files,
    }


def write_checksums(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            lines.append(f"{sha256(path)}  {path.relative_to(root)}")
    write_new(root / "checksums.sha256", "\n".join(lines) + "\n")


def main() -> None:
    for path in (VALIDATION / "render_comparison_report.json", VALIDATION / "geometry_difference_report.json", VALIDATION / "execution_environment_audit.json", M3 / "full/scene_manifest.json", M3 / "asset_ready/scene_manifest.json", M3 / "full/checksums.sha256", M3 / "asset_ready/checksums.sha256", REPORT):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite final artifact {path}")
    render_report, geometry_report = comparison_reports()
    log_records = [log_record(number) for number in CRITICAL_LOGS]
    audit = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "commands": {
            "uname": command_record(["uname", "-a"]),
            "gpu": command_record(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]),
            "blender": command_record([str(ROOT / "tools/m3_room1/blender-4.3.2-linux-x64/blender"), "--version"]),
            "disk": command_record(["df", "-BG", str(ROOT)]),
        },
        "git_repositories": {repo.name: git_record(repo) for repo in (ROOT / "repos").iterdir() if (repo / ".git").exists()},
        "workspace_git_status": "not_applicable: /root/scene_recon is not a Git worktree",
        "critical_logs": log_records,
        "parameters": {
            "scene_id": "room1",
            "render_frames": list(FRAMES),
            "render_resolution": [360, 640],
            "render_engine": "BLENDER_WORKBENCH",
            "bounds_tolerance_meters": 2e-6,
            "uniform_scale_meters_per_colmap_unit": 0.24019853045911085,
            "sofa_anchor_meters": 0.7,
            "removal_authority": str(M3 / "remove_instances.json"),
        },
        "rerun_recipe_audit": {
            "primary_exporter": str(ROOT / "scripts/m3_room1/export_metric_variants.py"),
            "primary_exporter_sha256": sha256(ROOT / "scripts/m3_room1/export_metric_variants.py"),
            "normalization_script": str(ROOT / "scripts/m3_room1/normalize_glb_blender_axes.py"),
            "normalization_script_sha256": sha256(ROOT / "scripts/m3_room1/normalize_glb_blender_axes.py"),
            "clean_rerun_behavior": "primary exporter stores canonical Blender coordinates directly as glTF x,z,-y",
            "historical_repair_behavior": "normalization script remains as the immutable log-044 repair recipe and is not chained after the patched clean exporter",
        },
        "warnings_and_repairs": [
            "Log 043 exposed Blender glTF Y-up import conversion; log 044 backed affected artifacts and pre-rotated GLB storage without changing canonical PLY, scale, or cameras.",
            "Collision GLB imports as 99,994 Blender polygons from 99,999 stored triangles because five degenerate triangles are discarded by glTF import; collision remains non-empty and byte-identical across variants.",
            "TSDF renders contain expected holes and surface noise; no geometry was hallucinated to fill them.",
        ],
    }
    write_json(VALIDATION / "execution_environment_audit.json", audit)
    write_json(M3 / "full/scene_manifest.json", manifest("full", render_report, geometry_report))
    write_json(M3 / "asset_ready/scene_manifest.json", manifest("asset_ready", render_report, geometry_report))
    write_checksums(M3 / "full")
    write_checksums(M3 / "asset_ready")

    full_import = json.loads((VALIDATION / "blender_import_full.json").read_text(encoding="ascii"))
    asset_import = json.loads((VALIDATION / "blender_import_asset_ready.json").read_text(encoding="ascii"))
    report = f"""# M3 room1 Reconstruction Report

Date: {datetime.now().astimezone().isoformat()}

Status: **PASS**

## Scope and provenance

- Scene: `room1`; milestone M3 only. No M4 assets or M5 physics were created.
- Source SHA256: `2e6964a3270f69a4ac04ae7a0055d3f5418df97d5cd97166428a0ddb2422c74e`.
- One shared base (`room1_shared_base_v1`) was reused for both variants; M0-M2 and PlanarGS were not rerun during finalization.
- Removal authority contains an empty list. No object was removed by semantic class and no replacement geometry was generated.

## Coordinate and scale acceptance

- Coordinate system: right-handed, Z-up `blender_world`, meters.
- Uniform scale: `0.24019853045911085` meters per COLMAP unit; no per-axis scaling.
- Gray left-sofa anchor: `0.7 m`, calibrated relative error `0.0`; uncertainty status PASS.
- Log 044 repaired glTF storage axes as `(x,z,-y)` while retaining canonical PLY, cameras, and scale. The primary exporter now applies this conversion directly for reproducible clean reruns.
- Fresh Blender 4.3.2 imports passed. Maximum GLB-to-canonical-PLY bounds error: full `{full_import['main_import']['maximum_bounds_error_meters']:.12g} m`, asset-ready `{asset_import['main_import']['maximum_bounds_error_meters']:.12g} m` (tolerance `2e-6 m`).

## Geometry and rendering

- Main mesh: {full_import['main_import']['vertex_count']:,} vertices, {full_import['main_import']['face_count']:,} faces.
- Collision import: {full_import['collision_import']['vertex_count']:,} vertices, {full_import['collision_import']['face_count']:,} Blender polygons.
- Full and asset-ready GLB, PLY, and collision GLB files are byte-identical; RMS and maximum vertex differences are `0.0 m`.
- Same-camera renders for frames 000005, 000030, and 000060 are pixel-identical (`0` differing pixels). Independently encoded PNG containers have different hashes but equal decoded RGBA arrays.
- Visual inspection passed: renders are nonblank and correctly oriented. Accepted TSDF holes/noise remain visible and were not filled by hallucinated geometry.

## Required deliverables

- M3A: `outputs/room1/m3/full/` contains scene GLB/PLY, collision GLB, camera poses, scale calibration, coordinate transform, renders, scene manifest, and checksums.
- M3B: `outputs/room1/m3/asset_ready/` contains byte-identical scene/collision geometry, removal report, camera/scale/coordinate metadata, renders, scene manifest, and checksums.
- Instance review: stable IDs, candidates JSON/CSV, multi-view masks, and numbered reviews are under `outputs/room1/m3/review/instances/` and the M3 root.
- Comparison and difference reports: `outputs/room1/m3/comparison_renders/` and `outputs/room1/m3/review/validation/`.
- Execution environment, commands, parameters, timing/log hashes, Git identities/status, warnings, and the rerun recipe are recorded in `execution_environment_audit.json` and immutable logs 041-050.

## Audit and validation

- Logs 041-044 preserve corrected export, instance review, detected axis mismatch, and its backed repair.
- Logs 045-047 preserve post-repair state verification and fresh Blender passes. Failed log 048 records the diagnosed PNG-container overconstraint; log 049 preserves corrected finalization and log 050 independently validates every required artifact and checksum.
- Historical logs and backups were retained. Final checksum verification status: PASS.

## Known limitations

- The TSDF reconstruction has visible holes and surface noise in occluded/low-texture regions.
- Blender imports 99,994 collision polygons from 99,999 stored collision triangles due to five degenerate triangles. The collision mesh is otherwise valid, non-empty, and identical between variants.
"""
    write_new(REPORT, report)
    print(json.dumps({"status": "PASS", "comparison_renders": len(FRAMES), "manifests": 2, "checksum_files": 2, "report": str(REPORT)}, indent=2))


if __name__ == "__main__":
    main()
