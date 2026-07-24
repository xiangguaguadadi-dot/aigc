"""
Object Separator — Extract per-object point clouds by ID.

Input:  labeled point cloud (points, colors, labels) from Module 1
Output: dict of object_id → {"points": (M,3), "colors": (M,3), "label": str}
"""

import numpy as np
from typing import Dict, List, Tuple, Optional


def separate_by_label(
    points: np.ndarray,
    colors: np.ndarray,
    labels: np.ndarray,
    label_names: Dict[int, str],
    min_points: int = 100,
) -> Dict[int, Dict]:
    """
    Split a fused labeled point cloud into per-object dicts.

    Parameters
    ----------
    points : (N, 3) float
    colors : (N, 3) uint8
    labels : (N,) int32  object ID per point
    label_names : dict  id → semantic name
    min_points : int  skip objects with fewer than this many points

    Returns
    -------
    objects : dict  id → {"points", "colors", "label", "count"}
    """
    objects = {}
    unique_ids = np.unique(labels)

    for obj_id in unique_ids:
        mask = labels == obj_id
        count = mask.sum()
        if count < min_points:
            continue

        name = label_names.get(int(obj_id), f"object_{obj_id:03d}")

        objects[int(obj_id)] = {
            "points": points[mask].astype(np.float32),
            "colors": colors[mask],
            "label": name,
            "count": count,
        }

    return objects


def compute_centroid_and_scale(
    points: np.ndarray,
) -> Tuple[np.ndarray, float]:
    """
    Compute centroid and bounding-sphere radius of a point cloud.

    Returns: centroid (3,), scale (float)
    """
    centroid = points.mean(axis=0)
    distances = np.linalg.norm(points - centroid, axis=1)
    scale = np.percentile(distances, 95)  # robust to outliers
    if scale < 1e-6:
        scale = 1.0
    return centroid, scale


def normalize_points(
    points: np.ndarray,
    centroid: Optional[np.ndarray] = None,
    scale: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Normalize a point cloud: center at origin, unit scale.

    Returns: normalized_points (N,3), centroid (3,), scale (float)
    """
    if centroid is None or scale is None:
        centroid, scale = compute_centroid_and_scale(points)

    normalized = (points - centroid) / scale
    return normalized, centroid, scale
