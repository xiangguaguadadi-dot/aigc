"""
Collision Body Generation.

Given a mesh (.glb), compute:
  1. Mesh volume (for mass calculation)
  2. Convex hull — for collision detection
  3. Oriented Bounding Box — for primitive collision (fallback)
  4. Shape classification: box-like → OBB, irregular → convex hull
"""

import numpy as np
from typing import Tuple, Optional, Dict
from dataclasses import dataclass


@dataclass
class CollisionBody:
    """Collision shape for physics simulation."""
    type: str  # "convex_hull" | "obb_box" | "sphere" | "composite"
    vertices: Optional[np.ndarray] = None   # (V, 3) for convex hull
    faces: Optional[np.ndarray] = None      # (F, 3)
    obb_center: Optional[np.ndarray] = None # (3,) for OBB
    obb_extents: Optional[np.ndarray] = None # (3,) half-extents
    volume_m3: float = 0.0


def compute_mesh_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """
    Compute volume of a closed triangle mesh using the divergence theorem.

    Returns volume in cubic units.
    """
    if len(faces) == 0:
        return 0.0

    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]

    # Signed volume: (1/6) * sum( (v0 × v1) · v2 )
    cross = np.cross(v1 - v0, v2 - v0)
    volume = np.abs(np.sum((v0 * cross).sum(axis=-1))) / 6.0
    return float(volume)


def compute_convex_hull(
    vertices: np.ndarray,
    max_faces: int = 256,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute convex hull of point cloud / mesh vertices.

    Returns (hull_vertices, hull_faces).
    """
    try:
        import open3d as o3d
    except ImportError:
        return _simple_obb_vertices(vertices)

    if len(vertices) < 4:
        return vertices, np.zeros((0, 3), dtype=np.int32)

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(vertices)

    try:
        hull, _ = pcd.compute_convex_hull()
    except Exception:
        return _simple_obb_vertices(vertices)

    hull_verts = np.asarray(hull.vertices)
    hull_faces = np.asarray(hull.triangles)

    # Simplify if too many faces
    if len(hull_faces) > max_faces:
        hull = hull.simplify_quadric_decimation(target_number_of_triangles=max_faces)
        hull_verts = np.asarray(hull.vertices)
        hull_faces = np.asarray(hull.triangles)

    return hull_verts, hull_faces


def compute_obb(vertices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Oriented Bounding Box via PCA.

    Returns (center, half_extents).
    """
    centroid = vertices.mean(axis=0)
    centered = vertices - centroid
    cov = np.cov(centered.T)

    try:
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        # Fallback: axis-aligned bounding box
        mins = vertices.min(axis=0)
        maxs = vertices.max(axis=0)
        return (mins + maxs) / 2, (maxs - mins) / 2

    # Sort by eigenvalue (largest first)
    order = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, order]

    # Project onto principal axes
    projected = centered @ eigenvectors
    mins = projected.min(axis=0)
    maxs = projected.max(axis=0)
    half_extents = (maxs - mins) / 2

    return centroid, half_extents


def classify_shape(
    vertices: np.ndarray,
) -> str:
    """
    Classify object as box-like or irregular.

    Heuristic: compare volume of convex hull vs OBB volume.
    Box-like objects have hull_volume / obb_volume ≈ 1.0.
    """
    if len(vertices) < 4:
        return "irregular"

    try:
        hull_verts, hull_faces = compute_convex_hull(vertices)
    except Exception:
        return "irregular"

    hull_vol = compute_mesh_volume(hull_verts, hull_faces)
    _, extents = compute_obb(vertices)
    obb_vol = extents[0] * extents[1] * extents[2] * 8  # full extents

    if obb_vol < 1e-9:
        return "irregular"

    ratio = hull_vol / obb_vol
    # > 0.85 → well-approximated by box
    return "box_like" if ratio > 0.85 else "irregular"


def generate_collision_body(
    vertices: np.ndarray,
    faces: np.ndarray,
    shape_type: str = "auto",
) -> CollisionBody:
    """
    Generate collision shape for a mesh.

    Parameters
    ----------
    vertices : (V, 3)
    faces : (F, 3)
    shape_type : "auto" | "convex_hull" | "obb" | "sphere"

    Returns CollisionBody.
    """
    volume = compute_mesh_volume(vertices, faces)

    if shape_type == "auto":
        shape_type = classify_shape(vertices)

    if shape_type == "sphere":
        centroid, extents = compute_obb(vertices)
        radius = float(np.linalg.norm(extents))
        return CollisionBody(
            type="sphere",
            obb_center=centroid,
            obb_extents=np.array([radius]),
            volume_m3=volume,
        )

    elif shape_type == "box_like" or shape_type == "obb":
        centroid, extents = compute_obb(vertices)
        return CollisionBody(
            type="obb_box",
            obb_center=centroid,
            obb_extents=extents,
            volume_m3=volume,
        )

    else:  # convex_hull
        hull_v, hull_f = compute_convex_hull(vertices)
        return CollisionBody(
            type="convex_hull",
            vertices=hull_v,
            faces=hull_f,
            volume_m3=volume,
        )


def _simple_obb_vertices(vertices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Generate 8 corners of an AABB as a simple 'hull'."""
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    corners = np.array([
        [mins[0], mins[1], mins[2]],
        [maxs[0], mins[1], mins[2]],
        [maxs[0], maxs[1], mins[2]],
        [mins[0], maxs[1], mins[2]],
        [mins[0], mins[1], maxs[2]],
        [maxs[0], mins[1], maxs[2]],
        [maxs[0], maxs[1], maxs[2]],
        [mins[0], maxs[1], maxs[2]],
    ])
    faces = np.array([
        [0,1,2], [0,2,3], [4,5,6], [4,6,7],
        [0,1,5], [0,5,4], [2,3,7], [2,7,6],
        [0,3,7], [0,7,4], [1,2,6], [1,6,5],
    ])
    return corners, faces
