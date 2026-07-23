#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix


ROOT = Path("/root/scene_recon")
M3 = ROOT / "outputs/room1/m3"
REVIEW_VALIDATION = M3 / "review/validation"
RENDER_FRAMES = ("frame_000005.jpg", "frame_000030.jpg", "frame_000060.jpg")
BOUNDS_TOLERANCE_METERS = 2e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mesh_world_bounds(mesh_objects: list) -> tuple[np.ndarray, np.ndarray]:
    minima = np.full(3, np.inf, dtype=np.float64)
    maxima = np.full(3, -np.inf, dtype=np.float64)
    for obj in mesh_objects:
        coordinates = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
        obj.data.vertices.foreach_get("co", coordinates)
        coordinates = coordinates.reshape((-1, 3)).astype(np.float64)
        matrix = np.asarray(obj.matrix_world, dtype=np.float64)
        world = coordinates @ matrix[:3, :3].T + matrix[:3, 3]
        minima = np.minimum(minima, world.min(axis=0))
        maxima = np.maximum(maxima, world.max(axis=0))
    return minima, maxima


def canonical_ply_bounds(path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    properties = []
    vertex_count = None
    with path.open("rb") as handle:
        while True:
            line = handle.readline()
            if not line:
                raise ValueError(f"unterminated PLY header: {path}")
            decoded = line.decode("ascii").strip()
            if decoded == "format binary_little_endian 1.0":
                continue
            if decoded.startswith("element vertex "):
                vertex_count = int(decoded.split()[-1])
            elif decoded.startswith("element face "):
                break
            elif vertex_count is not None and decoded.startswith("property "):
                _, kind, name = decoded.split()
                properties.append((name, {"double": "<f8", "float": "<f4", "uchar": "u1"}[kind]))
        while decoded != "end_header":
            decoded = handle.readline().decode("ascii").strip()
        offset = handle.tell()
    if vertex_count is None or [name for name, _ in properties[:3]] != ["x", "y", "z"]:
        raise ValueError(f"unsupported canonical PLY vertex layout: {path}")
    vertices = np.memmap(path, mode="r", offset=offset, dtype=np.dtype(properties), shape=(vertex_count,))
    minima = np.asarray([vertices[axis].min() for axis in ("x", "y", "z")], dtype=np.float64)
    maxima = np.asarray([vertices[axis].max() for axis in ("x", "y", "z")], dtype=np.float64)
    return minima, maxima, vertex_count


def import_glb(path: Path) -> tuple[list, dict]:
    before = set(bpy.data.objects)
    result = bpy.ops.import_scene.gltf(filepath=str(path))
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender failed to import {path}: {result}")
    imported = [obj for obj in bpy.data.objects if obj not in before]
    mesh_objects = [obj for obj in imported if obj.type == "MESH"]
    vertices = sum(len(obj.data.vertices) for obj in mesh_objects)
    faces = sum(len(obj.data.polygons) for obj in mesh_objects)
    if not mesh_objects or vertices <= 0 or faces <= 0:
        raise AssertionError(f"empty GLB import: {path}")
    bounds_min, bounds_max = mesh_world_bounds(mesh_objects)
    return imported, {
        "path": str(path),
        "sha256": sha256(path),
        "mesh_object_count": len(mesh_objects),
        "vertex_count": vertices,
        "face_count": faces,
        "imported_world_bounds_meters": [bounds_min.tolist(), bounds_max.tolist()],
    }


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("full", "asset_ready"), required=True)
    args = parser.parse_args(argv)

    if args.variant == "full":
        root = M3 / "full"
        main_glb = root / "static_scene_full.glb"
        collision_glb = root / "static_collision_full.glb"
    else:
        root = M3 / "asset_ready"
        main_glb = root / "static_scene_asset_ready.glb"
        collision_glb = root / "static_collision_asset_ready.glb"
    render_root = root / "renders"
    report_path = REVIEW_VALIDATION / f"blender_import_{args.variant}.json"
    if render_root.exists() or report_path.exists():
        raise FileExistsError(f"refusing to overwrite Blender output for {args.variant}")
    render_root.mkdir(parents=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    main_objects, main_stats = import_glb(main_glb)
    collision_objects, collision_stats = import_glb(collision_glb)
    for obj in collision_objects:
        obj.hide_render = True
        obj.hide_viewport = True

    canonical_ply = root / ("static_scene_full.ply" if args.variant == "full" else "static_scene_asset_ready.ply")
    ply_min, ply_max, ply_vertex_count = canonical_ply_bounds(canonical_ply)
    imported_bounds = np.asarray(main_stats["imported_world_bounds_meters"], dtype=np.float64)
    ply_bounds = np.stack((ply_min, ply_max))
    bounds_error = float(np.max(np.abs(imported_bounds - ply_bounds)))
    if bounds_error > BOUNDS_TOLERANCE_METERS:
        raise AssertionError(
            f"imported GLB bounds differ from canonical PLY by {bounds_error} m "
            f"(tolerance {BOUNDS_TOLERANCE_METERS} m)"
        )
    main_stats.update({
        "canonical_ply_path": str(canonical_ply),
        "canonical_ply_sha256": sha256(canonical_ply),
        "canonical_ply_vertex_count": ply_vertex_count,
        "canonical_ply_bounds_meters": ply_bounds.tolist(),
        "maximum_bounds_error_meters": bounds_error,
        "bounds_tolerance_meters": BOUNDS_TOLERANCE_METERS,
        "bounds_validation": "PASS",
    })

    pose_payload = json.loads((root / "camera_poses.json").read_text(encoding="ascii"))
    pose_by_image = {entry["image"]: entry for entry in pose_payload["poses"]}
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 360
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "VERTEX"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.show_specular_highlight = False
    scene.world.color = (0.055, 0.055, 0.055)

    camera_data = bpy.data.cameras.new("M3ValidationCamera")
    camera = bpy.data.objects.new("M3ValidationCamera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.sensor_width = 36.0
    camera_data.clip_start = 0.01
    camera_data.clip_end = 100.0

    render_records = []
    for frame_name in RENDER_FRAMES:
        entry = pose_by_image[frame_name]
        camera.matrix_world = Matrix(entry["blender_camera_to_world"])
        camera.data.lens = float(entry["fx"]) * camera.data.sensor_width / float(entry["width"])
        camera.data.shift_x = (float(entry["cx"]) - float(entry["width"]) / 2.0) / float(entry["width"])
        camera.data.shift_y = (float(entry["height"]) / 2.0 - float(entry["cy"])) / float(entry["width"])
        output = render_root / f"{Path(frame_name).stem}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        if not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError(f"missing Blender render: {output}")
        render_records.append({"camera_image": frame_name, "path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size})

    scale = json.loads((root / "scale_calibration.json").read_text(encoding="ascii"))
    transform = json.loads((root / "coordinate_transform.json").read_text(encoding="ascii"))
    if abs(float(scale["calibrated_width_meters"]) - 0.7) / 0.7 > 0.05:
        raise AssertionError("Blender input metadata fails sofa scale contract")
    if not transform.get("uniform_scale_only") or transform.get("up_axis") != "+Z" or transform.get("handedness") != "right-handed":
        raise AssertionError("Blender input metadata fails coordinate contract")

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "variant": args.variant,
        "blender_version": bpy.app.version_string,
        "background_mode": True,
        "main_import": main_stats,
        "collision_import": collision_stats,
        "camera_poses_sha256": sha256(root / "camera_poses.json"),
        "scale_calibration_sha256": sha256(root / "scale_calibration.json"),
        "coordinate_transform_sha256": sha256(root / "coordinate_transform.json"),
        "coordinate_validation": "PASS",
        "scale_validation": "PASS",
        "render_engine": scene.render.engine,
        "render_resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "renders": render_records,
    }
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
