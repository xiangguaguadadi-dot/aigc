"""
3D Mask Lifter — Back-project 2D masks to 3D space.

Given:
  - 2D binary masks (N, H, W)
  - Depth map (H, W) in meters
  - Camera intrinsic (3×3)

Produces:
  - Labeled 3D point cloud with object IDs
  - Per-object PLY exports
"""

from __future__ import annotations

import os
from typing import List, Tuple, Optional, Dict

import numpy as np


class MaskLifter3D:
    """
    Lift 2D segmentation masks to 3D using depth maps.

    Usage:
        lifter = MaskLifter3D(intrinsic_3x3, depth_scale=1.0)
        labeled_points, object_ids = lifter.lift(rgb, depth_map, masks, labels)
        lifter.export_ply(labeled_points, object_ids, label_names, output_dir)
    """

    def __init__(
        self,
        intrinsic: np.ndarray,
        depth_scale: float = 1.0,
        min_depth: float = 0.1,
        max_depth: float = 10.0,
    ):
        """
        Parameters
        ----------
        intrinsic : np.ndarray  shape (3, 3), camera intrinsic matrix K
        depth_scale : float  multiplier to convert raw depth to meters
        min_depth : float  minimum valid depth in meters
        max_depth : float  maximum valid depth in meters
        """
        self.K = intrinsic.astype(np.float64)
        self.depth_scale = depth_scale
        self.min_depth = min_depth
        self.max_depth = max_depth

        # Precompute pixel grid
        self._fx = self.K[0, 0]
        self._fy = self.K[1, 1]
        self._cx = self.K[0, 2]
        self._cy = self.K[1, 2]

    def _depth_to_camera_points(
        self,
        depth_map: np.ndarray,
    ) -> np.ndarray:
        """
        Convert depth map to camera-space 3D points.

        Parameters
        ----------
        depth_map : np.ndarray  shape (H, W), depth in meters

        Returns
        -------
        cam_pts : np.ndarray  shape (H, W, 3)
        """
        H, W = depth_map.shape
        v, u = np.mgrid[0:H, 0:W]

        depth = depth_map.astype(np.float64) * self.depth_scale

        # Mask invalid depths
        valid = (depth > self.min_depth) & (depth < self.max_depth)

        X = (u - self._cx) * depth / self._fx
        Y = (v - self._cy) * depth / self._fy
        Z = depth

        cam_pts = np.stack([X, Y, Z], axis=-1)
        cam_pts[~valid] = np.nan

        return cam_pts

    def lift(
        self,
        rgb: np.ndarray,
        depth_map: np.ndarray,
        masks: np.ndarray,
        object_ids: np.ndarray,
    ) -> Dict[int, Dict[str, np.ndarray]]:
        """
        Lift 2D masks to 3D point clouds.

        Parameters
        ----------
        rgb : np.ndarray  shape (H, W, 3), float or uint8 RGB
        depth_map : np.ndarray  shape (H, W), depth values
        masks : np.ndarray  shape (N, H, W), binary masks
        object_ids : np.ndarray  shape (N,), integer ID per mask

        Returns
        -------
        objects_3d : dict  object_id → {"points": (M,3), "colors": (M,3), "mask_name": str}
        """
        # Ensure rgb is 0-255 uint8
        if rgb.dtype == np.float32 or rgb.dtype == np.float64:
            if rgb.max() <= 1.0:
                rgb_uint8 = (rgb * 255).astype(np.uint8)
            else:
                rgb_uint8 = rgb.astype(np.uint8)
        else:
            rgb_uint8 = rgb.astype(np.uint8)

        # Camera-space 3D points
        cam_pts = self._depth_to_camera_points(depth_map)
        H, W = depth_map.shape

        objects_3d = {}
        for i in range(len(masks)):
            mask = masks[i].astype(bool)
            obj_id = int(object_ids[i])

            # Extract 3D points within this mask
            pts = cam_pts[mask]       # (K, 3)
            colors = rgb_uint8[mask]  # (K, 3)

            # Filter out invalid (NaN) depth
            valid = ~np.isnan(pts).any(axis=-1)
            pts = pts[valid]
            colors = colors[valid]

            if len(pts) == 0:
                continue

            # Merge with existing object if same ID
            if obj_id in objects_3d:
                existing = objects_3d[obj_id]
                objects_3d[obj_id] = {
                    "points": np.concatenate([existing["points"], pts], axis=0),
                    "colors": np.concatenate([existing["colors"], colors], axis=0),
                    "mask_name": existing["mask_name"],
                }
            else:
                objects_3d[obj_id] = {
                    "points": pts,
                    "colors": colors,
                    "mask_name": f"object_{obj_id:03d}",
                }

        return objects_3d

    def export_ply(
        self,
        objects_3d: Dict[int, Dict[str, np.ndarray]],
        label_names: Dict[int, str],
        output_dir: str,
        downsample: int = 1,
    ) -> List[str]:
        """
        Export per-object PLY files.

        Returns list of exported file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        saved_paths = []

        for obj_id, data in objects_3d.items():
            name = label_names.get(obj_id, f"object_{obj_id:03d}")
            safe_name = name.replace(" ", "_").replace(".", "")

            pts = data["points"][::downsample]
            colors = data["colors"][::downsample]

            if len(pts) == 0:
                continue

            ply_path = os.path.join(output_dir, f"{safe_name}_{obj_id:03d}.ply")
            _write_ply(ply_path, pts, colors)
            saved_paths.append(ply_path)

        return saved_paths

    def build_labeled_point_cloud(
        self,
        objects_3d: Dict[int, Dict[str, np.ndarray]],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Fuse all objects into a single labeled point cloud.

        Returns
        -------
        points : (M, 3)
        colors : (M, 3) uint8
        labels : (M,) int32 object IDs
        """
        all_pts, all_colors, all_labels = [], [], []
        for obj_id, data in objects_3d.items():
            n = len(data["points"])
            all_pts.append(data["points"])
            all_colors.append(data["colors"])
            all_labels.append(np.full(n, obj_id, dtype=np.int32))

        if not all_pts:
            return (
                np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.uint8),
                np.zeros((0,), dtype=np.int32),
            )

        return (
            np.concatenate(all_pts, axis=0),
            np.concatenate(all_colors, axis=0),
            np.concatenate(all_labels, axis=0),
        )


def _write_ply(path: str, points: np.ndarray, colors: np.ndarray):
    """Write a colored point cloud as PLY ASCII."""
    colors = np.clip(colors, 0, 255).astype(np.uint8)
    with open(path, "w") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(points)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        f.write("end_header\n")
        for i in range(len(points)):
            f.write(
                f"{points[i, 0]:.6f} {points[i, 1]:.6f} {points[i, 2]:.6f} "
                f"{colors[i, 0]} {colors[i, 1]} {colors[i, 2]}\n"
            )
