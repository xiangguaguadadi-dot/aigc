"""
Exporter — Normalize and export object meshes as .glb files.

Each output .glb:
  - Centered at origin
  - Scaled to unit bounding sphere
  - Contains vertex colors (if available)
  - Accompanied by metadata JSON
"""

import os
import json
import numpy as np
from typing import Dict, Optional, Tuple


def normalize_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """
    Center mesh at origin and scale to unit bounding sphere.

    Returns
    -------
    vertices_norm : (V, 3)  normalized vertices
    centroid : (3,)  original centroid
    scale : float  original scale factor
    """
    centroid = (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    centered = vertices - centroid
    distances = np.linalg.norm(centered, axis=1)
    scale = np.percentile(distances, 98)
    if scale < 1e-6:
        scale = 1.0

    vertices_norm = centered / scale
    return vertices_norm, centroid, scale


def export_glb(
    path: str,
    vertices: np.ndarray,
    faces: np.ndarray,
    vertex_colors: Optional[np.ndarray] = None,
    normalize: bool = True,
) -> Tuple[np.ndarray, float]:
    """
    Export a single mesh as .glb.

    Returns (centroid, scale) for metadata.
    """
    try:
        import trimesh
    except ImportError:
        raise ImportError("trimesh is required for .glb export. pip install trimesh")

    centroid = np.zeros(3, dtype=np.float32)
    scale = 1.0

    if normalize:
        vertices, centroid, scale = normalize_mesh(vertices, faces)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

    if vertex_colors is not None:
        colors_uint8 = np.clip(vertex_colors, 0, 255).astype(np.uint8)
        mesh.visual.vertex_colors = colors_uint8

    mesh.export(path, file_type="glb")
    return centroid, scale


def export_asset(
    obj_id: int,
    vertices: np.ndarray,
    faces: np.ndarray,
    label: str,
    output_dir: str,
    vertex_colors: Optional[np.ndarray] = None,
    extra_meta: Optional[Dict] = None,
) -> str:
    """
    Export one object as .glb + .json metadata.

    Returns path to the .glb file.
    """
    os.makedirs(output_dir, exist_ok=True)

    safe_name = label.replace(" ", "_").replace(".", "")
    glb_path = os.path.join(output_dir, f"{safe_name}_{obj_id:03d}.glb")

    # Normalize and export
    centroid, scale = export_glb(glb_path, vertices, faces, vertex_colors)

    # Metadata JSON
    meta = {
        "object_id": obj_id,
        "label": label,
        "num_vertices": int(len(vertices)),
        "num_faces": int(len(faces)),
        "original_centroid": centroid.tolist(),
        "normalization_scale": float(scale),  # scale factor: real = normalized × scale
        "original_scale": float(scale),
        "bounds": {
            "min": (vertices.min(axis=0) / scale + centroid).tolist(),
            "max": (vertices.max(axis=0) / scale + centroid).tolist(),
        },
    }
    if extra_meta:
        meta.update(extra_meta)

    meta_path = glb_path.replace(".glb", ".json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return glb_path


def export_asset_summary(
    exported: Dict[int, Dict],
    output_dir: str,
) -> str:
    """Write summary JSON for all exported assets."""
    summary = []
    for obj_id, info in exported.items():
        summary.append({
            "object_id": obj_id,
            "label": info.get("label", ""),
            "path": info.get("glb_path", ""),
            "num_vertices": info.get("num_vertices", 0),
            "num_faces": info.get("num_faces", 0),
            "centroid": info.get("centroid", [0, 0, 0]),
            "scale": info.get("scale", 1.0),
        })

    summary_path = os.path.join(output_dir, "asset_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    return summary_path
