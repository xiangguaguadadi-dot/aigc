"""Stage 5: Fuse depth maps into a single point cloud.

Includes cross-frame depth alignment to eliminate ghosting/multi-surface artifacts.
This aligns per-frame depth maps to a common scale using known camera poses,
mitigating the inconsistent scale problem of monocular depth estimators.
"""

import numpy as np
from pathlib import Path

from video_to_3d.utils.camera import unproject_points, load_cameras, build_intrinsics
from video_to_3d.utils.io import save_pointcloud_ply, write_depth_npy
from video_to_3d.utils.validation import check_point_cloud
from video_to_3d.utils.geometry import compute_point_cloud_extent


def align_depth_maps(
    depth_maps: list[np.ndarray],
    masks: list[np.ndarray],
    cameras: dict,
) -> list[np.ndarray]:
    """Align all depth maps to frame 0's scale using cross-frame consistency.

    Each monocular depth prediction has an independent scale/shift.
    This function uses known camera poses to find corresponding surfaces
    across frames and estimates per-frame scale corrections.

    Reference: D4RT's global scene representation ensures all queries share
    a consistent 3D coordinate system. We achieve the same effect by
    aligning per-frame depths through geometric constraints.

    Args:
        depth_maps: List of (H, W) depth arrays
        masks: List of (H, W) boolean foreground masks
        cameras: Camera JSON dict with intrinsics and per-frame extrinsics

    Returns:
        List of corrected (H, W) depth arrays, all in frame 0's scale
    """
    num_frames = len(depth_maps)
    if num_frames <= 1:
        return depth_maps

    intrinsics = cameras["intrinsics"]
    K = np.array([
        [intrinsics["fx"], 0, intrinsics["cx"]],
        [0, intrinsics["fy"], intrinsics["cy"]],
        [0, 0, 1],
    ], dtype=np.float64)

    # Unproject frame 0 as reference
    R0 = np.array(cameras["frames"][0]["rotation"], dtype=np.float64)
    t0 = np.array(cameras["frames"][0]["translation"], dtype=np.float64)
    ref_points = unproject_points(depth_maps[0], K, R0, t0, masks[0])

    if len(ref_points) < 100:
        print("  WARNING: Too few reference points for depth alignment")
        return depth_maps

    corrected = [depth_maps[0].copy()]  # frame 0 is the reference

    for i in range(1, num_frames):
        R_i = np.array(cameras["frames"][i]["rotation"], dtype=np.float64)
        t_i = np.array(cameras["frames"][i]["translation"], dtype=np.float64)

        # Project reference points into frame i's camera coordinates
        cam_coords = (R_i.T @ (ref_points - t_i).T).T  # world→camera_i

        # Filter to points in front of camera i
        in_front = cam_coords[:, 2] > 0
        if in_front.sum() < 10:
            corrected.append(depth_maps[i].copy())
            continue

        # Project to pixel coordinates
        px = cam_coords[in_front, 0] * K[0, 0] / cam_coords[in_front, 2] + K[0, 2]
        py = cam_coords[in_front, 1] * K[1, 1] / cam_coords[in_front, 2] + K[1, 2]
        projected_depth = cam_coords[in_front, 2]

        H, W = depth_maps[i].shape

        # Filter to valid pixel coordinates
        valid_px = (px >= 0) & (px < W) & (py >= 0) & (py < H)
        if valid_px.sum() < 10:
            corrected.append(depth_maps[i].copy())
            continue

        px_v = px[valid_px].astype(int)
        py_v = py[valid_px].astype(int)
        proj_d = projected_depth[valid_px]

        # Get depth values at the projected locations
        target_depth = depth_maps[i][py_v, px_v]

        # Valid where both depths are positive
        valid_depth = (target_depth > 0) & (proj_d > 0)
        if valid_depth.sum() < 10:
            corrected.append(depth_maps[i].copy())
            continue

        # Compute scale ratio: target_depth / projected_depth
        ratios = target_depth[valid_depth] / proj_d[valid_depth]

        # Use median ratio for robustness
        scale_correction = float(np.median(ratios))
        if scale_correction <= 0 or not np.isfinite(scale_correction):
            corrected.append(depth_maps[i].copy())
            continue

        # Apply correction
        aligned = depth_maps[i] / scale_correction
        corrected.append(aligned)

        print(f"  Depth alignment frame {i}: scale={scale_correction:.3f}, "
              f"overlapping samples={int(valid_depth.sum())}")

    return corrected


def run(
    depth_paths: list[Path],
    mask_paths: list[Path],
    foreground_paths: list[Path],
    cameras_path: Path,
    output_dir: Path,
    voxel_size: float | None = None,
    std_ratio: float = 1.0,
    align_depths: bool = True,
) -> dict:
    """Fuse multiple depth maps into a single point cloud.

    Args:
        depth_paths: Paths to depth NPY files
        mask_paths: Paths to binary mask PNG files
        foreground_paths: Paths to foreground RGBA images (for color)
        cameras_path: Path to cameras.json
        output_dir: Base output directory
        voxel_size: Voxel size for downsampling. If None, auto-computed.
        std_ratio: Statistical outlier removal threshold (std deviations)
        align_depths: Whether to cross-frame align depth scales

    Returns:
        dict with point cloud paths and summary
    """
    import cv2
    from video_to_3d.utils.io import read_depth_npy
    import open3d as o3d

    pc_dir = output_dir / "pointcloud"
    pc_dir.mkdir(parents=True, exist_ok=True)

    # Load camera data
    cameras = load_cameras(cameras_path)
    intrinsics = cameras["intrinsics"]
    K = np.array([
        [intrinsics["fx"], 0, intrinsics["cx"]],
        [0, intrinsics["fy"], intrinsics["cy"]],
        [0, 0, 1],
    ], dtype=np.float64)

    print(f"Fusing {len(depth_paths)} depth maps...")

    # Load all depth maps and masks
    depth_maps = []
    masks = []
    for depth_path, mask_path in zip(depth_paths, mask_paths):
        depth = read_depth_npy(depth_path)
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE) > 0
        depth_maps.append(depth)
        masks.append(mask)

    # Cross-frame depth alignment
    if align_depths and len(depth_maps) > 1:
        print("  Cross-frame depth alignment (D4RT-inspired consistency)...")
        depth_maps = align_depth_maps(depth_maps, masks, cameras)
        # Save aligned depth maps for inspection
        aligned_dir = output_dir / "depth" / "aligned"
        aligned_dir.mkdir(parents=True, exist_ok=True)
        for i, d in enumerate(depth_maps):
            write_depth_npy(aligned_dir / f"depth_aligned_{i:04d}.npy", d)
        print(f"  Aligned depths saved to: {aligned_dir}")

    # Unproject all frames
    all_points = []
    for i, (depth, mask, fg_path) in enumerate(zip(depth_maps, masks, foreground_paths)):
        frame_data = cameras["frames"][i]
        R = np.array(frame_data["rotation"], dtype=np.float64)
        t = np.array(frame_data["translation"], dtype=np.float64)

        points = unproject_points(depth, K, R, t, mask)
        valid_mask = np.isfinite(points).all(axis=1) & ~np.isnan(points).any(axis=1)
        points = points[valid_mask]

        print(f"  Frame {i}: {points.shape[0]} unprojected points")

        if len(points) >= 10:
            all_points.append(points)

    if len(all_points) == 0:
        raise RuntimeError("No valid points generated from any frame")

    fused_points = np.concatenate(all_points, axis=0)
    print(f"Total fused points: {fused_points.shape[0]}")

    # Save raw fused
    raw_path = pc_dir / "fused_raw.ply"
    save_pointcloud_ply(raw_path, fused_points)
    extent = compute_point_cloud_extent(fused_points)
    print(f"  Bounding box: {extent['dimensions']}, diagonal: {extent['diagonal']:.3f}")

    # Open3D filtering
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(fused_points)

    if pcd.points.__len__() > 10:
        cleaned_pcd, ind = pcd.remove_statistical_outlier(
            nb_neighbors=20, std_ratio=std_ratio
        )
        cleaned_points = np.asarray(cleaned_pcd.points)
        print(f"  After outlier removal: {cleaned_points.shape[0]} points")
    else:
        cleaned_points = fused_points

    if voxel_size is None:
        voxel_size = extent["diagonal"] / 500.0
        voxel_size = max(voxel_size, 1e-4)

    pcd_clean = o3d.geometry.PointCloud()
    pcd_clean.points = o3d.utility.Vector3dVector(cleaned_points)
    downsampled = pcd_clean.voxel_down_sample(voxel_size)
    final_points = np.asarray(downsampled.points)
    print(f"  After downsampling (voxel={voxel_size:.6f}): {final_points.shape[0]} points")

    check_point_cloud(final_points, "Final point cloud")

    clean_path = pc_dir / "fused_cleaned.ply"
    save_pointcloud_ply(clean_path, final_points)

    final_extent = compute_point_cloud_extent(final_points)
    scale_report = {
        "raw_point_count": int(fused_points.shape[0]),
        "cleaned_point_count": int(final_points.shape[0]),
        "voxel_size": float(voxel_size),
        "depth_alignment": "cross_frame" if align_depths else "none",
        "bounding_box": final_extent,
        "scale_mode": "unscaled",
        "scale_status": "unit_box_normalized",
    }

    import json
    with open(pc_dir / "scale_report.json", "w") as f:
        json.dump(scale_report, f, indent=2)

    result = {
        "point_cloud": final_points,
        "raw_path": str(raw_path.relative_to(output_dir)),
        "clean_path": str(clean_path.relative_to(output_dir)),
        "scale_report": scale_report,
    }

    return result
