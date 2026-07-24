"""Stage-level pre/post condition checks."""

import numpy as np
from pathlib import Path


class ValidationError(Exception):
    """Raised when a validation check fails."""
    pass


def check_file_exists(path: Path | str, label: str = "File"):
    """Verify that a file exists and is non-empty."""
    p = Path(path)
    if not p.exists():
        raise ValidationError(f"{label} not found: {p}")
    if p.stat().st_size == 0:
        raise ValidationError(f"{label} is empty: {p}")


def check_finite(arr: np.ndarray, label: str = "Array"):
    """Verify all values are finite (no NaN, no Inf)."""
    if not np.isfinite(arr).all():
        n_nan = int(np.isnan(arr).sum())
        n_inf = int(np.isinf(arr).sum())
        raise ValidationError(f"{label} contains {n_nan} NaN and {n_inf} Inf values")


def check_depth_map(depth: np.ndarray, label: str = "Depth"):
    """Validate a depth map."""
    check_finite(depth, label)
    valid = depth > 0
    if not valid.any():
        raise ValidationError(f"{label} has no valid (positive) values")
    if depth.ndim != 2:
        raise ValidationError(f"{label} should be 2D (H x W), got shape {depth.shape}")


def check_point_cloud(points: np.ndarray, label: str = "PointCloud"):
    """Validate a point cloud."""
    check_finite(points, label)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValidationError(f"{label} should be (N, 3), got shape {points.shape}")
    if points.shape[0] < 10:
        raise ValidationError(f"{label} has too few points: {points.shape[0]}")
    # Check for degenerate extent
    extent = np.ptp(points, axis=0)
    if (extent < 1e-6).any():
        raise ValidationError(f"{label} degenerated extent: {extent}")


def check_image(img: np.ndarray, label: str = "Image"):
    """Validate an image array."""
    if img.ndim not in [2, 3]:
        raise ValidationError(f"{label} should be 2D or 3D, got shape {img.shape}")
    if img.size == 0:
        raise ValidationError(f"{label} is empty")
    check_finite(img, label)


def check_mesh(mesh: "trimesh.Trimesh", label: str = "Mesh"):
    """Validate a trimesh mesh."""
    if len(mesh.vertices) == 0:
        raise ValidationError(f"{label} has no vertices")
    if len(mesh.faces) == 0:
        raise ValidationError(f"{label} has no faces")
    check_finite(mesh.vertices, f"{label} vertices")
    check_finite(mesh.faces, f"{label} faces")


def check_cameras(cameras: dict, expected_frames: int, label: str = "Cameras"):
    """Validate camera data structure."""
    if "frames" not in cameras:
        raise ValidationError(f"{label} missing 'frames' key")
    if len(cameras["frames"]) != expected_frames:
        raise ValidationError(
            f"{label} expected {expected_frames} frames, got {len(cameras['frames'])}"
        )
    if "intrinsics" not in cameras:
        raise ValidationError(f"{label} missing 'intrinsics' key")
    for i, frame in enumerate(cameras["frames"]):
        if "rotation" not in frame:
            raise ValidationError(f"{label} frame {i} missing 'rotation'")
        if "translation" not in frame:
            raise ValidationError(f"{label} frame {i} missing 'translation'")
