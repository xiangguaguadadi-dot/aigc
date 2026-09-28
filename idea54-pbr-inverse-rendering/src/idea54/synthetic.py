from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .cameras import look_at, perspective_intrinsics
from .geometry import primitive_mesh, vertex_normals
from .hashing import sha256_file


def _truth_material(vertices: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    normalized = (vertices - vertices.min(axis=0)) / np.maximum(vertices.max(axis=0) - vertices.min(axis=0), 1e-6)
    base = np.clip(0.12 + 0.76 * normalized[:, [0, 1, 2]], 0, 1).astype(np.float32)
    base = np.clip(base * rng.uniform(0.85, 1.15, size=(1, 3)), 0, 1).astype(np.float32)
    metallic = (normalized[:, 1:2] > 0.58).astype(np.float32) * 0.75 + 0.05
    roughness = np.clip(0.18 + 0.65 * normalized[:, 2:3], 0.04, 1).astype(np.float32)
    opacity = np.ones((len(vertices), 1), dtype=np.float32)
    return {"base_color": base, "metallic": metallic, "roughness": roughness, "opacity": opacity}


def _prior_material(truth: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {
        "base_color": np.clip(truth["base_color"] + rng.normal(0, 0.08, truth["base_color"].shape), 0, 1).astype(np.float32),
        "metallic": np.clip(truth["metallic"] + rng.normal(0, 0.12, truth["metallic"].shape), 0, 1).astype(np.float32),
        "roughness": np.clip(truth["roughness"] + rng.normal(0, 0.10, truth["roughness"].shape), 0.04, 1).astype(np.float32),
        "opacity": truth["opacity"].copy(),
    }


def _write_manifest(root: Path, source: str, metadata: dict) -> None:
    mapping = {
        "geometry": "geometry.npz",
        "material_prior": "material_prior.npz",
        "camera": "camera.json",
        "observation": "observation.png",
        "mask": "observation_mask.png",
    }
    payload = {
        "schema_version": "pbr-asset-bundle-v1",
        "source": source,
        "coordinate_system": "right-handed-y-up",
        "units": "unitless",
        "metadata": metadata,
        "files": {key: {"path": path, "sha256": sha256_file(root / path)} for key, path in mapping.items()},
    }
    (root / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_synthetic_bundle(root: str | Path, object_name: str, image_size: int, seed: int) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    vertices, faces = primitive_mesh(object_name)
    normals = vertex_normals(vertices, faces)
    truth = _truth_material(vertices, seed)
    prior = _prior_material(truth, seed + 10_000)
    np.savez(root / "geometry.npz", vertices=vertices, faces=faces, vertex_normals=normals)
    np.savez(root / "material_prior.npz", **prior)
    evaluation = root / "evaluation"
    evaluation.mkdir()
    np.savez(evaluation / "material_gt.npz", **truth)
    camera = {
        "width": image_size,
        "height": image_size,
        "K": perspective_intrinsics(image_size, image_size).tolist(),
        "world_to_camera": look_at(np.array([1.4, 1.1, 1.8], np.float32)).tolist(),
        "near": 0.1,
        "far": 10.0,
    }
    (root / "camera.json").write_text(json.dumps(camera, indent=2) + "\n", encoding="utf-8")
    Image.new("RGB", (image_size, image_size), (0, 0, 0)).save(root / "observation.png")
    mask = np.zeros((image_size, image_size), dtype=np.uint8)
    quarter = image_size // 4
    mask[quarter : image_size - quarter, quarter : image_size - quarter] = 255
    Image.fromarray(mask, mode="L").save(root / "observation_mask.png")
    heldout = []
    for angle in (45, 135, 225):
        radians = np.deg2rad(angle)
        eye = np.array([2 * np.cos(radians), 0.9, 2 * np.sin(radians)], np.float32)
        heldout.append({**camera, "world_to_camera": look_at(eye).tolist()})
    (evaluation / "heldout_cameras.json").write_text(json.dumps(heldout, indent=2) + "\n", encoding="utf-8")
    _write_manifest(root, "programmatic-synthetic", {"object": object_name, "seed": seed, "observation_status": "placeholder_requires_cuda_render"})
    return root


def replace_observation(root: Path, rgb: np.ndarray, mask: np.ndarray) -> None:
    Image.fromarray(np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="RGB").save(root / "observation.png")
    Image.fromarray(np.clip(mask * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="L").save(root / "observation_mask.png")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["metadata"]["observation_status"] = "rendered"
    for key in ("observation", "mask"):
        path = root / manifest["files"][key]["path"]
        manifest["files"][key]["sha256"] = sha256_file(path)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
