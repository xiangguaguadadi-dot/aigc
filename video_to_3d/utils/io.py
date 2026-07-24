"""File I/O utilities for meshes, point clouds, and images."""

import numpy as np
from pathlib import Path
import cv2
import trimesh


def read_image(path: Path | str) -> np.ndarray:
    """Read image as RGB uint8 array (H, W, 3)."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def read_image_rgba(path: Path | str) -> np.ndarray:
    """Read image as RGBA uint8 array (H, W, 4)."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    return img


def write_depth_npy(path: Path | str, depth: np.ndarray):
    """Save depth map as NPY (float32)."""
    np.save(str(path), depth.astype(np.float32))


def read_depth_npy(path: Path | str) -> np.ndarray:
    """Load depth map from NPY."""
    return np.load(str(path))


def save_depth_visualization(path: Path | str, depth: np.ndarray):
    """Save depth map as a normalized PNG for visualization."""
    d = depth.copy()
    valid = d > 0
    if valid.any():
        d_min, d_max = d[valid].min(), d[valid].max()
        if d_max > d_min:
            d[valid] = (d[valid] - d_min) / (d_max - d_min)
    d[d < 0] = 0
    d[d > 1] = 1
    img = (d * 255).astype(np.uint8)
    img_colored = cv2.applyColorMap(img, cv2.COLORMAP_INFERNO)
    cv2.imwrite(str(path), img_colored)


def load_mesh(path: Path | str) -> trimesh.Trimesh:
    """Load a mesh from file (PLY, OBJ, GLB, etc.)."""
    mesh = trimesh.load(str(path))
    if isinstance(mesh, trimesh.Scene):
        # Flatten scene to single mesh
        mesh = mesh.dump(concatenate=True)
    return mesh


def save_mesh(mesh: trimesh.Trimesh, path: Path | str):
    """Save mesh to file. Format inferred from extension."""
    trimesh.exchange.export.export_mesh(mesh, str(path))


def save_pointcloud_ply(path: Path | str, points: np.ndarray, colors: np.ndarray | None = None):
    """Save point cloud as PLY using trimesh."""
    if colors is not None and colors.dtype != np.uint8:
        colors = (np.clip(colors, 0, 1) * 255).astype(np.uint8)
    pc = trimesh.points.PointCloud(points, colors=colors)
    pc.export(str(path))
