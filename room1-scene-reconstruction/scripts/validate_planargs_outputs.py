#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image
from plyfile import PlyData


WORKSPACE = Path("/root/scene_recon")
PLANARGS_ROOT = WORKSPACE / "repos" / "PlanarGS"
DEFAULT_SCENE = WORKSPACE / "data" / "planargs_official" / "classroom"
DEFAULT_MODEL = WORKSPACE / "outputs" / "planargs_official" / "classroom_full"
DEFAULT_STATS = (
    WORKSPACE
    / "outputs"
    / "planargs_official"
    / "classroom_validation"
    / "mask_foreground_ratios.json"
)


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise AssertionError(f"missing or empty file: {path}")


def files_in(path: Path) -> list[Path]:
    if not path.is_dir():
        raise AssertionError(f"missing directory: {path}")
    files = sorted(item for item in path.iterdir() if item.is_file())
    if not files:
        raise AssertionError(f"empty directory: {path}")
    return files


def binary_count(path: Path) -> int:
    require_file(path)
    with path.open("rb") as handle:
        raw = handle.read(8)
    if len(raw) != 8:
        raise AssertionError(f"invalid COLMAP binary header: {path}")
    return struct.unpack("<Q", raw)[0]


def finite_array(path: Path) -> None:
    array = np.load(path, allow_pickle=False)
    if array.size == 0 or not np.isfinite(array).all():
        raise AssertionError(f"empty or non-finite numeric array: {path}")


def validate_scene(scene: Path) -> dict:
    image_dir = scene / "images"
    sparse_dir = scene / "sparse"
    image_files = files_in(image_dir)
    for image_path in image_files:
        with Image.open(image_path) as image:
            image.verify()

    camera_bin = sparse_dir / "cameras.bin"
    image_bin = sparse_dir / "images.bin"
    point_bin = sparse_dir / "points3D.bin"
    for path in (camera_bin, image_bin, point_bin):
        require_file(path)

    sys.path.insert(0, str(PLANARGS_ROOT))
    from scene.colmap_loader import (  # pylint: disable=import-outside-toplevel
        read_extrinsics_binary,
        read_intrinsics_binary,
        read_points3D_binary,
    )

    cameras = read_intrinsics_binary(str(camera_bin))
    registered = read_extrinsics_binary(str(image_bin))
    _, _, parsed_points = read_points3D_binary(str(point_bin))
    raw_point_count = binary_count(point_bin)
    if not cameras or not registered or raw_point_count <= 0:
        raise AssertionError("COLMAP model has zero cameras, images, or sparse points")
    if parsed_points.size == 0:
        raise AssertionError("PlanarGS parser retained zero valid sparse points")

    missing = sorted(
        image.name for image in registered.values() if not (image_dir / image.name).is_file()
    )
    if missing:
        raise AssertionError(f"COLMAP references missing images: {missing[:10]}")
    unknown_cameras = sorted(
        image.camera_id for image in registered.values() if image.camera_id not in cameras
    )
    if unknown_cameras:
        raise AssertionError(f"COLMAP images reference unknown cameras: {unknown_cameras}")

    result = {
        "scene": str(scene),
        "image_file_count": len(image_files),
        "camera_count": len(cameras),
        "registered_image_count": len(registered),
        "sparse_point_count_raw": raw_point_count,
        "sparse_point_count_planargs_valid": int(parsed_points.shape[0]),
        "image_references_valid": True,
    }
    print(json.dumps(result, sort_keys=True))
    return result


def validate_numeric_files(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.suffix.lower() == ".npy":
            finite_array(path)


def validate_priors(
    scene: Path,
    registered_count: int,
    stats_output: Path,
    skip_planar: bool,
) -> dict:
    geom_root = scene / "geomprior"
    geom_dirs = {
        name: files_in(geom_root / name)
        for name in ("aligned_depth", "resized_confs", "prior_normal")
    }
    for name, paths in geom_dirs.items():
        if len(paths) != registered_count:
            raise AssertionError(
                f"{name} count {len(paths)} != registered images {registered_count}"
            )
        validate_numeric_files(paths)

    weights_path = geom_root / "depth_weights.json"
    require_file(weights_path)
    with weights_path.open("r", encoding="utf-8") as handle:
        weights = json.load(handle)
    if not isinstance(weights, dict) or len(weights) != registered_count:
        raise AssertionError("depth_weights.json count does not match registered images")
    numeric_weights = np.asarray(list(weights.values()), dtype=np.float64)
    if not np.isfinite(numeric_weights).all():
        raise AssertionError("depth_weights.json contains NaN or Inf")

    result = {
        "geomprior_counts": {name: len(paths) for name, paths in geom_dirs.items()},
        "depth_weight_count": len(weights),
    }
    if skip_planar:
        print(json.dumps(result, sort_keys=True))
        return result

    mask_files = files_in(scene / "planarprior" / "mask")
    if len(mask_files) != registered_count:
        raise AssertionError(
            f"planar mask count {len(mask_files)} != registered images {registered_count}"
        )
    ratios = {}
    for path in mask_files:
        mask = np.load(path, allow_pickle=False)
        if mask.size == 0 or not np.isfinite(mask).all():
            raise AssertionError(f"invalid planar mask: {path}")
        ratio = float(np.count_nonzero(mask) / mask.size)
        if not math.isfinite(ratio) or ratio < 0.0 or ratio > 1.0:
            raise AssertionError(f"invalid foreground ratio for {path}: {ratio}")
        ratios[path.name] = ratio
    if not any(0.0 < ratio < 1.0 for ratio in ratios.values()):
        raise AssertionError("all planar masks are uniformly black or white")

    stats_output.parent.mkdir(parents=True, exist_ok=True)
    with stats_output.open("w", encoding="utf-8") as handle:
        json.dump(ratios, handle, indent=2, sort_keys=True)
        handle.write("\n")
    result.update(
        {
            "planar_mask_count": len(mask_files),
            "mask_ratio_min": min(ratios.values()),
            "mask_ratio_max": max(ratios.values()),
            "mask_ratio_mean": float(np.mean(list(ratios.values()))),
            "mask_stats": str(stats_output),
        }
    )
    print(json.dumps(result, sort_keys=True))
    return result


def ply_counts(path: Path, require_faces: bool) -> tuple[int, int]:
    require_file(path)
    ply = PlyData.read(str(path))
    if "vertex" not in ply:
        raise AssertionError(f"PLY has no vertex element: {path}")
    vertex = ply["vertex"]
    vertex_count = len(vertex)
    if vertex_count <= 0:
        raise AssertionError(f"PLY has zero vertices: {path}")
    for field in ("x", "y", "z"):
        if field not in vertex.data.dtype.names:
            raise AssertionError(f"PLY is missing vertex field {field}: {path}")
        if not np.isfinite(vertex[field]).all():
            raise AssertionError(f"PLY contains non-finite {field}: {path}")
    face_count = len(ply["face"]) if "face" in ply else 0
    if require_faces and face_count <= 0:
        raise AssertionError(f"PLY mesh has zero faces: {path}")
    return vertex_count, face_count


def validate_logs(logs: Iterable[Path]) -> None:
    fatal = re.compile(
        r"Traceback|CUDA error|out of memory|segmentation fault|"
        r"illegal memory access|missing checkpoint|No such file or directory.*\.so",
        re.IGNORECASE,
    )
    nonfinite = re.compile(r"\b(?:nan|inf)\b", re.IGNORECASE)
    for path in logs:
        require_file(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        match = fatal.search(text)
        if match:
            raise AssertionError(f"fatal pattern {match.group(0)!r} in log: {path}")
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = nonfinite.search(line)
            dust3r_range_config = (
                "instantiating :" in line
                and "depth_mode=" in line
                and "conf_mode=" in line
            )
            if match and not dust3r_range_config:
                raise AssertionError(
                    f"fatal pattern {match.group(0)!r} in log: "
                    f"{path}:{line_number}"
                )
        status = re.findall(r"PIPESTATUS\[0\]=(\d+)", text)
        if status and status[-1] != "0":
            raise AssertionError(f"nonzero recorded PIPESTATUS[0] in log: {path}")


def validate_full(model: Path, registered_count: int, logs: list[Path]) -> dict:
    gaussian = model / "point_cloud" / "iteration_30000" / "point_cloud.ply"
    mesh = model / "mesh" / "tsdf_fusion_post.ply"
    gaussian_points, _ = ply_counts(gaussian, require_faces=False)
    mesh_vertices, mesh_faces = ply_counts(mesh, require_faces=True)

    render_root = model / "train" / "ours_30000"
    rgb = files_in(render_root / "renders")
    depth = files_in(render_root / "renders_depth")
    normal = files_in(render_root / "renders_normal")
    for label, paths in (("RGB", rgb), ("depth", depth), ("normal", normal)):
        if len(paths) != registered_count:
            raise AssertionError(
                f"{label} render count {len(paths)} != registered images {registered_count}"
            )
    validate_numeric_files(depth)
    for path in rgb + normal:
        with Image.open(path) as image:
            image.verify()
    validate_logs(logs)

    result = {
        "gaussian_point_count": gaussian_points,
        "mesh_vertex_count": mesh_vertices,
        "mesh_face_count": mesh_faces,
        "rgb_render_count": len(rgb),
        "depth_render_count": len(depth),
        "normal_render_count": len(normal),
        "fatal_log_scan": "PASS",
    }
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("scene", "priors", "full"), required=True)
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--stats-output", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--skip-planar", action="store_true")
    parser.add_argument("--log", action="append", type=Path, default=[])
    args = parser.parse_args()

    scene_result = validate_scene(args.scene.resolve())
    if args.stage == "scene":
        print("planargs_scene_validation=PASS")
        return
    validate_priors(
        args.scene.resolve(),
        scene_result["registered_image_count"],
        args.stats_output.resolve(),
        args.skip_planar,
    )
    if args.stage == "priors":
        print("planargs_priors_validation=PASS")
        return
    validate_full(
        args.model_path.resolve(),
        scene_result["registered_image_count"],
        [path.resolve() for path in args.log],
    )
    print("planargs_full_validation=PASS")


if __name__ == "__main__":
    main()
