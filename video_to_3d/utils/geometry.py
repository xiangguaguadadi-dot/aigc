"""Geometry utilities: transforms, alignment, filtering."""

import numpy as np


def similarity_transform(
    src: np.ndarray, dst: np.ndarray
) -> tuple[np.ndarray, float, np.ndarray]:
    """Compute similarity transform (R, s, t) aligning src to dst.

    Uses Umeyama algorithm: finds R (rotation), s (scale), t (translation)
    such that s * R @ src + t ≈ dst.

    Args:
        src: (N, 3) source points
        dst: (N, 3) target points

    Returns:
        R: (3, 3) rotation matrix
        s: scale factor
        t: (3,) translation vector
    """
    assert src.shape == dst.shape and src.shape[0] >= 3

    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)

    src_centered = src - src_mean
    dst_centered = dst - dst_mean

    src_var = np.sum(src_centered ** 2)
    H = src_centered.T @ dst_centered

    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T

    # Handle reflection case
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    s = np.trace(np.diag(S) @ R) / src_var if src_var > 0 else 1.0
    t = dst_mean - s * R @ src_mean

    return R, s, t


def transform_points(points: np.ndarray, R: np.ndarray, t: np.ndarray, scale: float = 1.0) -> np.ndarray:
    """Apply (s * R @ x + t) to a set of points.

    Args:
        points: (N, 3) input points
        R: (3, 3) rotation
        t: (3,) translation
        scale: uniform scale

    Returns:
        (N, 3) transformed points
    """
    return scale * (R @ points.T).T + t


def compute_point_cloud_extent(points: np.ndarray) -> dict:
    """Compute bounding box and extent of a point cloud.

    Args:
        points: (N, 3) point cloud

    Returns:
        dict with min, max, center, dimensions, diagonal
    """
    pts_min = points.min(axis=0)
    pts_max = points.max(axis=0)
    center = (pts_min + pts_max) / 2
    dims = pts_max - pts_min
    diag = np.linalg.norm(dims)

    return {
        "min": pts_min.tolist(),
        "max": pts_max.tolist(),
        "center": center.tolist(),
        "dimensions": dims.tolist(),
        "diagonal": float(diag),
    }


def normalize_to_unit_box(points: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """Scale and translate points so the longest axis spans [0, 1].

    Args:
        points: (N, 3) point cloud

    Returns:
        normalized: (N, 3) normalized points
        scale: scale factor applied
        translation: translation applied before scaling
    """
    center = (points.max(axis=0) + points.min(axis=0)) / 2
    translated = points - center
    max_extent = translated.max(axis=0) - translated.min(axis=0)
    scale = 1.0 / max_extent.max() if max_extent.max() > 0 else 1.0
    normalized = translated * scale
    return normalized, scale, center
