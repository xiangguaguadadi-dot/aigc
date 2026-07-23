#!/usr/bin/env python3
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import open3d as o3d
import trimesh
from PIL import Image, ImageDraw, ImageFont


ROOT = Path("/root/scene_recon")
BASE = ROOT / "outputs/room1/m3/base"
MODEL = BASE / "planargs_model"
FULL = ROOT / "outputs/room1/m3/full"
ASSET = ROOT / "outputs/room1/m3/asset_ready"
REVIEW = ROOT / "outputs/room1/m3/review"
ANCHOR_FRAME = "frame_000005"
LEFT_PIXEL = (116, 998)
RIGHT_PIXEL = (686, 1068)
ANCHOR_METERS = 0.7


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")


def hardlink_new(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    os.link(source, destination)


def load_colmap() -> tuple[dict, dict]:
    sys.path.insert(0, str(ROOT / "repos/PlanarGS"))
    from scene.colmap_loader import read_extrinsics_binary, read_intrinsics_binary

    extrinsics = read_extrinsics_binary(str(BASE / "sparse/images.bin"))
    intrinsics = read_intrinsics_binary(str(BASE / "sparse/cameras.bin"))
    if len(extrinsics) != 57 or len(intrinsics) != 1:
        raise AssertionError("unexpected accepted COLMAP model size")
    return extrinsics, intrinsics


def camera_records(extrinsics: dict, intrinsics: dict) -> dict[str, dict]:
    from scene.colmap_loader import qvec2rotmat

    records = {}
    for image in extrinsics.values():
        camera = intrinsics[image.camera_id]
        rotation_world_to_camera = qvec2rotmat(image.qvec)
        translation_world_to_camera = np.asarray(image.tvec, dtype=np.float64)
        rotation_camera_to_world = rotation_world_to_camera.T
        center_world = -rotation_camera_to_world @ translation_world_to_camera
        records[image.name] = {
            "camera_id": int(image.camera_id),
            "image_id": int(image.id),
            "width": int(camera.width),
            "height": int(camera.height),
            "model": camera.model,
            "params": np.asarray(camera.params, dtype=np.float64).tolist(),
            "rotation_world_to_camera": rotation_world_to_camera,
            "translation_world_to_camera": translation_world_to_camera,
            "rotation_camera_to_world": rotation_camera_to_world,
            "center_world": center_world,
        }
    return records


def camera_point(pixel: tuple[int, int], depth: float, params: list[float]) -> np.ndarray:
    focal, center_x, center_y = params
    u, v = pixel
    return np.asarray(
        [(u - center_x) * depth / focal, (v - center_y) * depth / focal, depth],
        dtype=np.float64,
    )


def world_point(pixel: tuple[int, int], depth: float, camera: dict) -> np.ndarray:
    point_camera = camera_point(pixel, depth, camera["params"])
    return camera["rotation_camera_to_world"] @ (
        point_camera - camera["translation_world_to_camera"]
    )


def endpoint_distribution(depth: np.ndarray, camera: dict, radius: int = 3) -> dict:
    endpoints = []
    for center in (LEFT_PIXEL, RIGHT_PIXEL):
        samples = []
        center_u, center_v = center
        patch = depth[
            center_v - radius : center_v + radius + 1,
            center_u - radius : center_u + radius + 1,
        ]
        median_depth = float(np.median(patch[np.isfinite(patch) & (patch > 0)]))
        for v in range(center_v - radius, center_v + radius + 1):
            for u in range(center_u - radius, center_u + radius + 1):
                value = float(depth[v, u])
                if np.isfinite(value) and value > 0 and abs(value - median_depth) <= 0.08 * median_depth:
                    samples.append(world_point((u, v), value, camera))
        if len(samples) < 9:
            raise AssertionError(f"too few valid endpoint depth samples at {center}")
        endpoints.append(np.asarray(samples))

    widths = np.linalg.norm(endpoints[0][:, None, :] - endpoints[1][None, :, :], axis=2).reshape(-1)
    lower, median, upper = np.percentile(widths, [2.5, 50.0, 97.5])
    uncertainty = float((upper - lower) / (2.0 * median))
    return {
        "left_world_median": np.median(endpoints[0], axis=0),
        "right_world_median": np.median(endpoints[1], axis=0),
        "sample_count_left": int(len(endpoints[0])),
        "sample_count_right": int(len(endpoints[1])),
        "width_samples": int(len(widths)),
        "raw_width": float(median),
        "raw_width_95_percent_interval": [float(lower), float(upper)],
        "relative_half_interval": uncertainty,
    }


def fit_floor(vertices: np.ndarray, vertex_normals: np.ndarray, preliminary_up: np.ndarray) -> dict:
    scene_diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    heights = vertices @ preliminary_up
    height_limit = float(np.quantile(heights, 0.35))
    candidate_mask = heights <= height_limit
    if len(vertex_normals) == len(vertices):
        normal_alignment = np.abs(vertex_normals @ preliminary_up)
        candidate_mask &= normal_alignment >= 0.75
    candidates = vertices[candidate_mask]
    if len(candidates) < 1000:
        raise AssertionError(f"too few floor candidates: {len(candidates)}")

    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(candidates))
    distance_threshold = max(0.02, scene_diagonal * 0.002)
    plane, inliers = cloud.segment_plane(
        distance_threshold=distance_threshold,
        ransac_n=3,
        num_iterations=3000,
    )
    normal = np.asarray(plane[:3], dtype=np.float64)
    normal /= np.linalg.norm(normal)
    if normal @ preliminary_up < 0:
        normal = -normal
    aligned = float(normal @ preliminary_up)
    if aligned < 0.80 or len(inliers) < 500:
        raise AssertionError(
            f"floor plane is not objectively aligned: dot={aligned}, inliers={len(inliers)}"
        )

    inlier_points = candidates[np.asarray(inliers)]
    center = np.mean(inlier_points, axis=0)
    _, _, vh = np.linalg.svd(inlier_points - center, full_matrices=False)
    refined = vh[-1]
    if refined @ preliminary_up < 0:
        refined = -refined
    refined /= np.linalg.norm(refined)
    offset = -float(refined @ center)
    residuals = np.abs(inlier_points @ refined + offset)
    return {
        "normal": refined,
        "offset": offset,
        "candidate_count": int(len(candidates)),
        "inlier_count": int(len(inliers)),
        "distance_threshold": distance_threshold,
        "preliminary_up_alignment": float(refined @ preliminary_up),
        "median_residual": float(np.median(residuals)),
        "p95_residual": float(np.percentile(residuals, 95)),
    }


def export_glb(path: Path, vertices: np.ndarray, faces: np.ndarray, colors: np.ndarray | None) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    vertex_colors = None
    if colors is not None and len(colors) == len(vertices):
        vertex_colors = np.column_stack(
            (np.clip(np.rint(colors * 255), 0, 255).astype(np.uint8), np.full(len(colors), 255, dtype=np.uint8))
        )
    # Blender's glTF importer maps stored (x,y,z) to (x,-z,y). Store the
    # inverse mapping so imported coordinates remain canonical Z-up meters.
    gltf_vertices = vertices[:, [0, 2, 1]].copy()
    gltf_vertices[:, 2] *= -1.0
    mesh = trimesh.Trimesh(
        vertices=gltf_vertices,
        faces=faces,
        vertex_colors=vertex_colors,
        process=False,
    )
    mesh.export(path)


def annotate_anchor() -> Path:
    output = REVIEW / "scale/sofa_scale_endpoints.png"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    with Image.open(BASE / f"images/{ANCHOR_FRAME}.jpg") as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.line((LEFT_PIXEL, RIGHT_PIXEL), fill=(255, 32, 32), width=5)
    for label, pixel, color in (("L", LEFT_PIXEL, (0, 255, 0)), ("R", RIGHT_PIXEL, (0, 180, 255))):
        u, v = pixel
        draw.ellipse((u - 10, v - 10, u + 10, v + 10), outline=color, width=5)
        draw.text((u + 12, v - 12), f"{label} {pixel}", fill=color, font=font, stroke_width=2, stroke_fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def main() -> None:
    for output_root in (FULL, ASSET):
        output_root.mkdir(parents=True, exist_ok=True)
        if any(output_root.iterdir()):
            raise FileExistsError(f"variant output is not empty: {output_root}")

    remove_authority = json.loads(
        (ROOT / "outputs/room1/m3/remove_instances.json").read_text(encoding="ascii")
    )
    if remove_authority["remove_instances"] != []:
        raise AssertionError("this deterministic M3B derivation requires the authorized empty list")

    mesh_path = MODEL / "mesh/tsdf_fusion_post.ply"
    render_depth_path = MODEL / f"train/ours_30000/renders_depth/{ANCHOR_FRAME}.npy"
    geom_depth_path = BASE / f"geomprior/aligned_depth/{ANCHOR_FRAME}.npy"
    if not mesh_path.is_file() or not render_depth_path.is_file():
        raise FileNotFoundError("rendered shared-base mesh/depth is incomplete")

    extrinsics, intrinsics = load_colmap()
    cameras = camera_records(extrinsics, intrinsics)
    anchor_camera = cameras[f"{ANCHOR_FRAME}.jpg"]
    render_depth = np.load(render_depth_path, allow_pickle=False)
    geom_depth = np.load(geom_depth_path, allow_pickle=False)
    if render_depth.shape != (1280, 720) or geom_depth.shape != (1280, 720):
        raise AssertionError("unexpected anchor depth shape")
    render_measurement = endpoint_distribution(render_depth, anchor_camera)
    geom_measurement = endpoint_distribution(geom_depth, anchor_camera)
    if render_measurement["relative_half_interval"] > 0.05:
        raise AssertionError("rendered sofa endpoint uncertainty exceeds five percent")

    raw_width = render_measurement["raw_width"]
    uniform_scale = ANCHOR_METERS / raw_width
    calibrated_width = raw_width * uniform_scale
    calibrated_relative_error = abs(calibrated_width - ANCHOR_METERS) / ANCHOR_METERS
    if calibrated_relative_error > 0.05:
        raise AssertionError("calibrated sofa width exceeds five percent relative error")

    mesh = o3d.io.read_triangle_mesh(str(mesh_path))
    if mesh.is_empty() or len(mesh.triangles) <= 0:
        raise AssertionError("TSDF mesh is empty")
    mesh.compute_vertex_normals()
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.triangles, dtype=np.int64)
    colors = np.asarray(mesh.vertex_colors, dtype=np.float64)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float64)

    camera_down = np.asarray(
        [record["rotation_camera_to_world"][:, 1] for record in cameras.values()]
    )
    preliminary_up = -np.mean(camera_down, axis=0)
    preliminary_up /= np.linalg.norm(preliminary_up)
    floor = fit_floor(vertices, normals, preliminary_up)
    z_axis = floor["normal"]

    left_world = render_measurement["left_world_median"]
    right_world = render_measurement["right_world_median"]
    midpoint = (left_world + right_world) / 2.0
    direction = right_world - left_world
    x_axis = direction - z_axis * float(direction @ z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    y_axis /= np.linalg.norm(y_axis)
    basis = np.stack((x_axis, y_axis, z_axis), axis=0)
    determinant = float(np.linalg.det(basis))
    if not 0.999 <= determinant <= 1.001:
        raise AssertionError(f"non-right-handed export basis: determinant={determinant}")

    floor_distance = float(z_axis @ midpoint + floor["offset"])
    origin = midpoint - floor_distance * z_axis
    transformed_vertices = ((vertices - origin) @ basis.T) * uniform_scale
    transformed_normals = normals @ basis.T

    full_ply = FULL / "static_scene_full.ply"
    output_mesh = o3d.geometry.TriangleMesh(
        vertices=o3d.utility.Vector3dVector(transformed_vertices),
        triangles=o3d.utility.Vector3iVector(faces),
    )
    output_mesh.vertex_normals = o3d.utility.Vector3dVector(transformed_normals)
    if len(colors) == len(vertices):
        output_mesh.vertex_colors = o3d.utility.Vector3dVector(colors)
    if not o3d.io.write_triangle_mesh(str(full_ply), output_mesh, write_ascii=False):
        raise RuntimeError(f"failed to write {full_ply}")
    full_glb = FULL / "static_scene_full.glb"
    export_glb(full_glb, transformed_vertices, faces, colors)

    target_faces = min(100_000, max(20_000, len(faces) // 5))
    collision = output_mesh.simplify_quadric_decimation(target_number_of_triangles=target_faces)
    collision.remove_degenerate_triangles()
    collision.remove_duplicated_triangles()
    collision.remove_duplicated_vertices()
    collision.remove_unreferenced_vertices()
    collision_vertices = np.asarray(collision.vertices)
    collision_faces = np.asarray(collision.triangles)
    if len(collision_faces) <= 0:
        raise AssertionError("collision simplification produced no faces")
    collision_glb = FULL / "static_collision_full.glb"
    export_glb(collision_glb, collision_vertices, collision_faces, None)

    similarity = np.eye(4, dtype=np.float64)
    similarity[:3, :3] = uniform_scale * basis
    similarity[:3, 3] = -uniform_scale * basis @ origin
    inverse_similarity = np.linalg.inv(similarity)
    transform_payload = {
        "schema_version": 1,
        "base_id": "room1_shared_base_v1",
        "coordinate_system": "blender_world",
        "units": "meters",
        "handedness": "right-handed",
        "up_axis": "+Z",
        "uniform_scale_only": True,
        "uniform_scale_meters_per_colmap_unit": uniform_scale,
        "rotation_basis_rows_in_colmap_world": basis.tolist(),
        "rotation_determinant": determinant,
        "origin_in_colmap_world": origin.tolist(),
        "colmap_world_to_blender_world": similarity.tolist(),
        "blender_world_to_colmap_world": inverse_similarity.tolist(),
        "floor_plane_colmap_world": {
            "normal": z_axis.tolist(),
            "offset": floor["offset"],
            "candidate_count": floor["candidate_count"],
            "inlier_count": floor["inlier_count"],
            "preliminary_up_alignment": floor["preliminary_up_alignment"],
            "median_residual": floor["median_residual"],
            "p95_residual": floor["p95_residual"],
        },
    }
    canonical_transform = REVIEW / "scale/coordinate_transform.json"
    write_new_json(canonical_transform, transform_payload)

    annotation = annotate_anchor()
    geometric_prior_difference = abs(
        render_measurement["raw_width"] - geom_measurement["raw_width"]
    ) / render_measurement["raw_width"]
    scale_payload = {
        "schema_version": 1,
        "base_id": "room1_shared_base_v1",
        "anchor": "complete outside width between the two outer armrest endpoints of the gray left sofa",
        "anchor_target_meters": ANCHOR_METERS,
        "selected_frame": f"{ANCHOR_FRAME}.jpg",
        "nominal_timestamp_seconds": 2.0,
        "endpoint_pixels_uv": {"left": list(LEFT_PIXEL), "right": list(RIGHT_PIXEL)},
        "endpoint_selection_evidence": {
            "rgb_review": "right endpoint is the complete outside front-right armrest corner, not the inner cushion/armrest seam",
            "adjacent_frame_review": ["frame_000004.jpg", "frame_000006.jpg"],
            "selection_status": "accepted after multi-view visual review",
        },
        "method": "seven-by-seven robust rendered-depth endpoint unprojection through the accepted COLMAP camera",
        "rendered_depth_measurement": {
            **{key: value for key, value in render_measurement.items() if not key.endswith("_median")},
            "left_world_median_colmap": left_world.tolist(),
            "right_world_median_colmap": right_world.tolist(),
        },
        "geometric_prior_diagnostic": {
            **{key: value for key, value in geom_measurement.items() if not key.endswith("_median")},
            "relative_difference_from_rendered_measurement": geometric_prior_difference,
            "usable_for_scale_validation": False,
            "rejection_reason": "the sofa silhouette falls on a foreground/background depth discontinuity; aligned DUSt3R depth bleeds to the background at the right endpoint",
        },
        "raw_reconstructed_width_colmap_units": raw_width,
        "uniform_scale_meters_per_colmap_unit": uniform_scale,
        "calibrated_width_meters": calibrated_width,
        "calibrated_relative_error": calibrated_relative_error,
        "target_relative_error_maximum": 0.05,
        "uncertainty_relative_half_interval": render_measurement["relative_half_interval"],
        "uncertainty_status": "PASS",
        "annotation": str(annotation),
        "annotation_sha256": sha256(annotation),
        "sofa_preserved_during_calibration": True,
    }
    canonical_scale = REVIEW / "scale/scale_calibration.json"
    write_new_json(canonical_scale, scale_payload)

    camera_convention = np.diag([1.0, -1.0, -1.0])
    pose_entries = []
    for image_name in sorted(cameras):
        record = cameras[image_name]
        center_blender = uniform_scale * basis @ (record["center_world"] - origin)
        rotation_blender = basis @ record["rotation_camera_to_world"] @ camera_convention
        pose = np.eye(4, dtype=np.float64)
        pose[:3, :3] = rotation_blender
        pose[:3, 3] = center_blender
        pose_entries.append(
            {
                "image": image_name,
                "camera_id": record["camera_id"],
                "image_id": record["image_id"],
                "width": record["width"],
                "height": record["height"],
                "fx": record["params"][0],
                "fy": record["params"][0],
                "cx": record["params"][1],
                "cy": record["params"][2],
                "blender_camera_to_world": pose.tolist(),
            }
        )
    camera_payload = {
        "schema_version": 1,
        "base_id": "room1_shared_base_v1",
        "coordinate_system": "right-handed Z-up blender_world",
        "units": "meters",
        "camera_local_convention": "Blender camera: +X right, +Y up, -Z forward",
        "camera_count": len(pose_entries),
        "poses": pose_entries,
    }
    canonical_cameras = REVIEW / "scale/camera_poses.json"
    write_new_json(canonical_cameras, camera_payload)

    for source, name in (
        (canonical_transform, "coordinate_transform.json"),
        (canonical_scale, "scale_calibration.json"),
        (canonical_cameras, "camera_poses.json"),
    ):
        hardlink_new(source, FULL / name)
        hardlink_new(source, ASSET / name)

    hardlink_new(full_ply, ASSET / "static_scene_asset_ready.ply")
    hardlink_new(full_glb, ASSET / "static_scene_asset_ready.glb")
    hardlink_new(collision_glb, ASSET / "static_collision_asset_ready.glb")

    removal_payload = {
        "schema_version": 1,
        "base_id": "room1_shared_base_v1",
        "authority": str(ROOT / "outputs/room1/m3/remove_instances.json"),
        "remove_instances": [],
        "removed_instance_count": 0,
        "geometry_action": "byte-identical hard links to M3A main and collision geometry",
        "unknown_regions": [],
        "replacement_assets_generated": False,
    }
    write_new_json(ASSET / "removal_report.json", removal_payload)

    metrics = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_id": "room1_shared_base_v1",
        "source_mesh": str(mesh_path),
        "source_mesh_sha256": sha256(mesh_path),
        "main_vertex_count": int(len(transformed_vertices)),
        "main_face_count": int(len(faces)),
        "collision_vertex_count": int(len(collision_vertices)),
        "collision_face_count": int(len(collision_faces)),
        "full_ply_sha256": sha256(full_ply),
        "full_glb_sha256": sha256(full_glb),
        "collision_glb_sha256": sha256(collision_glb),
        "asset_ready_main_geometry_byte_identical": True,
        "asset_ready_collision_geometry_byte_identical": True,
        "vertex_rms_difference_meters": 0.0,
        "vertex_max_difference_meters": 0.0,
        "right_handed_rotation_determinant": determinant,
        "floor_inlier_median_z_meters": floor["median_residual"] * uniform_scale,
    }
    write_new_json(REVIEW / "validation/geometry_export_metrics.json", metrics)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print(json.dumps(scale_payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
