"""Camera model, projection, and unprojection utilities."""

import json
import numpy as np
from pathlib import Path
from typing import Optional

def pinhole_projection(points_3d: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Project 3D world points to 2D image coordinates.

    Args:
        points_3d: (N, 3) world coordinates
        K: (3, 3) intrinsic matrix
        R: (3, 3) rotation matrix (world→camera)
        t: (3,) translation vector (world→camera)

    Returns:
        (N, 2) pixel coordinates
    """
    # Transform to camera coordinates
    cam_coords = (R @ points_3d.T + t[:, None]).T  # (N, 3)
    # Project
    uv_homogeneous = K @ cam_coords.T  # (3, N)
    uv = uv_homogeneous[:2] / uv_homogeneous[2:3]
    return uv.T


def unproject_points(
    depths: np.ndarray,
    K: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
    mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Unproject depth map to 3D world points.

    Args:
        depths: (H, W) depth values in camera coordinates
        K: (3, 3) intrinsic matrix
        R: (3, 3) rotation (camera→world, i.e., camera orientation in world)
        t: (3,) translation (camera position in world)
        mask: (H, W) boolean mask of valid pixels. If None, all valid depths used.

    Returns:
        (N, 3) 3D points in world coordinates
    """
    H, W = depths.shape
    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]

    # Create pixel grid
    u, v = np.meshgrid(np.arange(W), np.arange(H))
    u = u.astype(np.float32)
    v = v.astype(np.float32)

    if mask is None:
        mask = depths > 0

    valid = mask & (depths > 0) & np.isfinite(depths)

    u_valid = u[valid]
    v_valid = v[valid]
    d_valid = depths[valid]

    # Unproject to camera coordinates
    x_cam = (u_valid - cx) * d_valid / fx
    y_cam = (v_valid - cy) * d_valid / fy
    z_cam = d_valid

    points_cam = np.stack([x_cam, y_cam, z_cam], axis=1)  # (N, 3)

    # Transform to world coordinates
    points_world = (R @ points_cam.T).T + t  # (N, 3)

    return points_world


def estimate_focal_length(image_width: int, image_height: int, fov_degrees: float = 60.0) -> float:
    """Estimate focal length from image dimensions and assumed FOV.

    Args:
        image_width: Width in pixels
        image_height: Height in pixels
        fov_degrees: Assumed horizontal field of view

    Returns:
        Focal length in pixels
    """
    fov_rad = np.radians(fov_degrees)
    focal = image_width / (2.0 * np.tan(fov_rad / 2.0))
    return focal


def build_intrinsics(fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    """Build a 3x3 pinhole intrinsic matrix."""
    return np.array([
        [fx, 0, cx],
        [0, fy, cy],
        [0,  0,  1],
    ], dtype=np.float64)


def save_cameras(cameras: dict, path: Path | str):
    """Save camera data to JSON, converting numpy arrays to lists."""
    class _Encoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            return super().default(obj)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cameras, f, indent=2, cls=_Encoder)


def load_cameras(path: Path | str) -> dict:
    """Load camera data from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
