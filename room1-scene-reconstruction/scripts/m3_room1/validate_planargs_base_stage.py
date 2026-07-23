#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from plyfile import PlyData


ROOT = Path("/root/scene_recon")
BASE = ROOT / "outputs/room1/m3/base"
MODEL = BASE / "planargs_model"
REVIEW = ROOT / "outputs/room1/m3/review/planargs"
PLANARGS = ROOT / "repos/PlanarGS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files(path: Path, suffix: str | None = None) -> list[Path]:
    if not path.is_dir():
        raise AssertionError(f"missing directory: {path}")
    result = sorted(item for item in path.iterdir() if item.is_file())
    if suffix is not None:
        result = [item for item in result if item.suffix == suffix]
    if not result:
        raise AssertionError(f"empty directory: {path}")
    return result


def finite_npy(path: Path) -> np.ndarray:
    array = np.load(path, allow_pickle=False)
    if array.size == 0 or not np.isfinite(array).all():
        raise AssertionError(f"invalid numeric array: {path}")
    return array


def registered_stems() -> set[str]:
    sys.path.insert(0, str(PLANARGS))
    from scene.colmap_loader import read_extrinsics_binary

    images = read_extrinsics_binary(str(BASE / "sparse/images.bin"))
    result = {Path(image.name).stem for image in images.values()}
    if len(result) != 57:
        raise AssertionError(f"expected 57 registered images, got {len(result)}")
    if "frame_000005" not in result:
        raise AssertionError("registered set is missing sofa anchor frame_000005")
    return result


def validate_geom() -> dict:
    registered = registered_stems()
    geom = BASE / "geomprior"
    groups = sorted(path for path in geom.glob("_group*") if path.is_dir())
    if len(groups) != 4:
        raise AssertionError(f"expected four DUSt3R groups, got {len(groups)}")
    raw_depth = [path for group in groups for path in files(group / "depth", ".npy")]
    raw_conf = [path for group in groups for path in files(group / "confs", ".npy")]
    if len(raw_depth) != 93 or len(raw_conf) != 93:
        raise AssertionError(
            f"expected 93 raw depth/conf files, got {len(raw_depth)}/{len(raw_conf)}"
        )
    if {path.stem for path in raw_depth} != {f"frame_{index:06d}" for index in range(1, 94)}:
        raise AssertionError("raw DUSt3R depth names do not match the frozen 93 frames")

    aligned = {}
    for name in ("aligned_depth", "resized_confs", "prior_normal"):
        paths = files(geom / name, ".npy")
        if {path.stem for path in paths} != registered:
            raise AssertionError(f"{name} names do not match registered COLMAP views")
        for path in paths:
            finite_npy(path)
        aligned[name] = len(paths)

    weights_path = geom / "depth_weights.json"
    weights = json.loads(weights_path.read_text(encoding="ascii"))
    if set(weights) != registered:
        raise AssertionError("depth weight names do not match registered COLMAP views")
    values = np.asarray(list(weights.values()), dtype=np.float64)
    if not np.isfinite(values).all():
        raise AssertionError("depth weights contain NaN or Inf")

    return {
        "group_size": 30,
        "group_count": len(groups),
        "raw_depth_count": len(raw_depth),
        "raw_confidence_count": len(raw_conf),
        "registered_image_count": len(registered),
        "aligned_counts": aligned,
        "depth_weight_count": len(weights),
        "depth_weights_sha256": sha256(weights_path),
    }


def validate_planar() -> dict:
    result = validate_geom()
    registered = registered_stems()
    mask_paths = files(BASE / "planarprior/mask", ".npy")
    if {path.stem for path in mask_paths} != registered:
        raise AssertionError("LP3 mask names do not match registered COLMAP views")
    ratios = {}
    for path in mask_paths:
        mask = finite_npy(path)
        ratio = float(np.count_nonzero(mask) / mask.size)
        if not math.isfinite(ratio) or not 0.0 <= ratio <= 1.0:
            raise AssertionError(f"invalid LP3 mask ratio: {path}={ratio}")
        ratios[path.name] = ratio
    if not any(0.0 < ratio < 1.0 for ratio in ratios.values()):
        raise AssertionError("all LP3 masks are uniformly empty or full")
    stats_path = REVIEW / "mask_foreground_ratios.json"
    if stats_path.exists():
        raise FileExistsError(f"refusing to overwrite {stats_path}")
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(ratios, indent=2, sort_keys=True) + "\n", encoding="ascii")
    result.update(
        {
            "planar_mask_count": len(mask_paths),
            "mask_ratio_min": min(ratios.values()),
            "mask_ratio_max": max(ratios.values()),
            "mask_ratio_mean": float(np.mean(list(ratios.values()))),
            "mask_stats": str(stats_path),
            "mask_stats_sha256": sha256(stats_path),
        }
    )
    return result


def ply_counts(path: Path, require_faces: bool) -> tuple[int, int]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise AssertionError(f"missing PLY: {path}")
    ply = PlyData.read(str(path))
    if "vertex" not in ply or len(ply["vertex"]) <= 0:
        raise AssertionError(f"PLY has no vertices: {path}")
    vertex = ply["vertex"]
    for field in ("x", "y", "z"):
        if not np.isfinite(vertex[field]).all():
            raise AssertionError(f"non-finite {field} in {path}")
    faces = len(ply["face"]) if "face" in ply else 0
    if require_faces and faces <= 0:
        raise AssertionError(f"PLY has no faces: {path}")
    return len(vertex), faces


def validate_train() -> dict:
    gaussian = MODEL / "point_cloud/iteration_30000/point_cloud.ply"
    points, _ = ply_counts(gaussian, require_faces=False)
    return {
        "iteration": 30000,
        "gaussian_path": str(gaussian),
        "gaussian_size_bytes": gaussian.stat().st_size,
        "gaussian_point_count": points,
        "gaussian_sha256": sha256(gaussian),
    }


def validate_render() -> dict:
    result = validate_train()
    registered = registered_stems()
    mesh = MODEL / "mesh/tsdf_fusion_post.ply"
    vertices, faces_count = ply_counts(mesh, require_faces=True)
    render_root = MODEL / "train/ours_30000"
    counts = {}
    for name, suffix in (("rgb", ".jpg"), ("depth", ".npy"), ("normal", ".jpg")):
        folder = {
            "rgb": "renders",
            "depth": "renders_depth",
            "normal": "renders_normal",
        }[name]
        paths = files(render_root / folder, suffix)
        if {path.stem for path in paths} != registered:
            raise AssertionError(f"{name} render names do not match registered views")
        if name == "depth":
            for path in paths:
                finite_npy(path)
        else:
            for path in paths:
                with Image.open(path) as image:
                    image.verify()
        counts[f"{name}_render_count"] = len(paths)
    result.update(
        {
            **counts,
            "mesh_path": str(mesh),
            "mesh_size_bytes": mesh.stat().st_size,
            "mesh_vertex_count": vertices,
            "mesh_face_count": faces_count,
            "mesh_sha256": sha256(mesh),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("geom", "planar", "train", "render"))
    args = parser.parse_args()
    output_path = REVIEW / f"{args.stage}_validation.json"
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite {output_path}")

    validators = {
        "geom": validate_geom,
        "planar": validate_planar,
        "train": validate_train,
        "render": validate_render,
    }
    result = validators[args.stage]()
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_id": "room1_shared_base_v1",
        "stage": args.stage,
        "status": "PASS",
        **result,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"validation_path={output_path}")
    print(f"validation_sha256={sha256(output_path)}")


if __name__ == "__main__":
    main()
