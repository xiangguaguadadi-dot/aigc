from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .errors import Idea54Error
from .hashing import geometry_sha256, sha256_file


@dataclass(frozen=True)
class Geometry:
    vertices: np.ndarray
    faces: np.ndarray
    vertex_normals: np.ndarray

    @property
    def sha256(self) -> str:
        return geometry_sha256(self.vertices, self.faces, self.vertex_normals)


@dataclass(frozen=True)
class Material:
    base_color: np.ndarray
    metallic: np.ndarray
    roughness: np.ndarray
    opacity: np.ndarray


@dataclass(frozen=True)
class Camera:
    width: int
    height: int
    k: np.ndarray
    world_to_camera: np.ndarray
    near: float
    far: float


@dataclass(frozen=True)
class AssetBundle:
    root: Path
    manifest: dict[str, Any]
    geometry: Geometry
    material: Material
    camera: Camera
    observation: np.ndarray
    mask: np.ndarray


def _require_shape(name: str, value: np.ndarray, shape: tuple[int | None, ...]) -> None:
    if value.ndim != len(shape) or any(s is not None and value.shape[i] != s for i, s in enumerate(shape)):
        raise Idea54Error("INVALID_SHAPE", f"{name} has shape {value.shape}; expected {shape}")


def _finite(name: str, value: np.ndarray) -> None:
    if not np.isfinite(value).all():
        raise Idea54Error("NONFINITE_ARRAY", f"{name} contains NaN or Inf")


def _bounded(name: str, value: np.ndarray, low: float, high: float) -> None:
    _finite(name, value)
    if value.size and (float(value.min()) < low or float(value.max()) > high):
        raise Idea54Error("PBR_RANGE_VIOLATION", f"{name} must be in [{low}, {high}]")


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        raise Idea54Error("MISSING_FILE", str(path))
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def load_bundle(root: str | Path, verify_hashes: bool = True) -> AssetBundle:
    root = Path(root).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise Idea54Error("MISSING_MANIFEST", str(manifest_path))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "pbr-asset-bundle-v1":
        raise Idea54Error("UNSUPPORTED_SCHEMA", str(manifest.get("schema_version")))

    files = manifest.get("files", {})
    required = {"geometry", "material_prior", "camera", "observation", "mask"}
    if set(files) != required:
        raise Idea54Error("INVALID_MANIFEST_FILES", f"expected exactly {sorted(required)}")
    resolved: dict[str, Path] = {}
    for key, entry in files.items():
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise Idea54Error("UNSAFE_PATH", str(relative))
        path = (root / relative).resolve()
        if root not in path.parents:
            raise Idea54Error("UNSAFE_PATH", str(relative))
        if not path.is_file():
            raise Idea54Error("MISSING_FILE", str(path))
        if verify_hashes and sha256_file(path) != entry.get("sha256"):
            raise Idea54Error("HASH_MISMATCH", str(relative))
        resolved[key] = path

    geo = _load_npz(resolved["geometry"])
    vertices = np.asarray(geo["vertices"], dtype=np.float32)
    faces = np.asarray(geo["faces"], dtype=np.int32)
    normals = np.asarray(geo["vertex_normals"], dtype=np.float32)
    _require_shape("vertices", vertices, (None, 3))
    _require_shape("faces", faces, (None, 3))
    _require_shape("vertex_normals", normals, (vertices.shape[0], 3))
    _finite("vertices", vertices)
    _finite("vertex_normals", normals)
    if faces.size and (int(faces.min()) < 0 or int(faces.max()) >= vertices.shape[0]):
        raise Idea54Error("BAD_FACE_INDEX", "faces reference vertices outside the array")
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths < 1e-8):
        raise Idea54Error("INVALID_NORMAL", "zero-length vertex normal")
    normals = normals / lengths[:, None]
    geometry = Geometry(vertices, faces, normals.astype(np.float32))

    pbr = _load_npz(resolved["material_prior"])
    n = vertices.shape[0]
    material = Material(
        np.asarray(pbr["base_color"], dtype=np.float32),
        np.asarray(pbr["metallic"], dtype=np.float32),
        np.asarray(pbr["roughness"], dtype=np.float32),
        np.asarray(pbr["opacity"], dtype=np.float32),
    )
    for name, value, width, low in (
        ("base_color", material.base_color, 3, 0.0),
        ("metallic", material.metallic, 1, 0.0),
        ("roughness", material.roughness, 1, 0.04),
        ("opacity", material.opacity, 1, 0.0),
    ):
        _require_shape(name, value, (n, width))
        _bounded(name, value, low, 1.0)

    camera_payload = json.loads(resolved["camera"].read_text(encoding="utf-8"))
    camera = Camera(
        int(camera_payload["width"]),
        int(camera_payload["height"]),
        np.asarray(camera_payload["K"], dtype=np.float32),
        np.asarray(camera_payload["world_to_camera"], dtype=np.float32),
        float(camera_payload["near"]),
        float(camera_payload["far"]),
    )
    _require_shape("K", camera.k, (3, 3))
    _require_shape("world_to_camera", camera.world_to_camera, (4, 4))
    if not 0 < camera.near < camera.far:
        raise Idea54Error("INVALID_CLIP_RANGE", "expected 0 < near < far")

    observation = np.asarray(Image.open(resolved["observation"]).convert("RGB"), dtype=np.float32) / 255.0
    mask = np.asarray(Image.open(resolved["mask"]).convert("L"), dtype=np.float32) / 255.0
    if observation.shape[:2] != (camera.height, camera.width) or mask.shape != (camera.height, camera.width):
        raise Idea54Error("IMAGE_SIZE_MISMATCH", "camera, observation, and mask sizes differ")
    coverage = float((mask > 0.5).mean())
    if coverage <= 0.001 or coverage >= 0.999:
        raise Idea54Error("INVALID_MASK_COVERAGE", f"coverage={coverage:.6f}")
    return AssetBundle(root, manifest, geometry, material, camera, observation, mask)


def validate_bundle(root: str | Path) -> dict[str, Any]:
    bundle = load_bundle(root)
    return {
        "status": "valid",
        "schema_version": bundle.manifest["schema_version"],
        "vertices": int(bundle.geometry.vertices.shape[0]),
        "faces": int(bundle.geometry.faces.shape[0]),
        "mask_coverage": float((bundle.mask > 0.5).mean()),
        "geometry_sha256": bundle.geometry.sha256,
    }
