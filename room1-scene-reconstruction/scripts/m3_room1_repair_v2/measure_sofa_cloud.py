#!/usr/bin/env python3
"""Fuse selected SAM sofa masks with rendered depth and estimate its width."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import open3d as o3d
import pycolmap


ROOT = Path('/root/scene_recon')
BASE = ROOT / 'outputs/room1/m3_repair_v2/base'
MODEL = ROOT / 'outputs/room1/m3_repair_v2/model_planargs'
SEG = ROOT / 'outputs/room1/m3_repair_v2/review/sofa_segmentation'
OUT = ROOT / 'outputs/room1/m3_repair_v2/review/sofa_metric_measurement.json'
FRAMES = [186, 187, 188, 189, 190, 191, 192]


def choose_mask(masks: np.ndarray) -> int:
    # Visual review of all eight overlays identifies detection 2 as the stable
    # chair instance; the larger "lounge" masks include the table and floor.
    if len(masks) <= 2:
        raise ValueError(f'expected stable sofa mask index 2, got {len(masks)} masks')
    return 2


def radial_unproject(u: np.ndarray, v: np.ndarray, depth: np.ndarray,
                     params: np.ndarray) -> np.ndarray:
    focal, cx, cy, k = params
    xd = (u - cx) / focal
    yd = (v - cy) / focal
    xu, yu = xd.copy(), yd.copy()
    for _ in range(6):
        radius2 = xu * xu + yu * yu
        factor = 1.0 + k * radius2
        xu, yu = xd / factor, yd / factor
    return np.column_stack((xu * depth, yu * depth, depth))


def main() -> None:
    recon = pycolmap.Reconstruction(str(BASE / 'sparse_fast_v3'))
    images = {image.name: image for image in recon.images.values()}
    camera = next(iter(recon.cameras.values()))
    world_points = []
    selected = {}
    frame_stats = {}
    for number in FRAMES:
        stem = f'frame_{number:06d}'
        name = stem + '.jpg'
        image = images[name]
        masks = np.load(SEG / f'{stem}_masks.npy', allow_pickle=False)
        index = choose_mask(masks)
        mask = masks[index]
        depth = np.load(MODEL / f'train/ours_30000/renders_depth/{stem}.npy', allow_pickle=False)
        if depth.shape != mask.shape:
            raise ValueError(f'{stem} depth={depth.shape} mask={mask.shape}')
        yy, xx = np.where(mask)
        keep = (yy % 3 == 0) & (xx % 3 == 0)
        yy, xx = yy[keep], xx[keep]
        values = depth[yy, xx].astype(np.float64)
        valid = np.isfinite(values) & (values > 0.05) & (values < 25.0)
        yy, xx, values = yy[valid], xx[valid], values[valid]
        camera_points = radial_unproject(xx.astype(float), yy.astype(float), values,
                                         np.asarray(camera.params, dtype=float))
        pose = image.cam_from_world()
        rotation = np.asarray(pose.rotation.matrix(), dtype=float).T
        translation = np.asarray(pose.translation, dtype=float)
        centers = -rotation @ translation
        world = (rotation @ camera_points.T).T + centers
        world_points.append(world)
        frame_stats[stem] = {
            'point_count': int(len(world)),
            'median_world': np.median(world, axis=0).tolist(),
            'p01_world': np.percentile(world, 1, axis=0).tolist(),
            'p99_world': np.percentile(world, 99, axis=0).tolist(),
        }
        selected[stem] = {
            'mask_index': index,
            'mask_pixels': int(mask.sum()),
            'sampled_valid_points': int(len(world)),
        }

    points = np.concatenate(world_points, axis=0)
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    cloud, keep_indices = cloud.remove_statistical_outlier(nb_neighbors=30, std_ratio=1.5)
    points = np.asarray(cloud.points)
    labels = np.asarray(cloud.cluster_dbscan(eps=0.25, min_points=40, print_progress=False))
    cluster_sizes = {
        int(label): int((labels == label).sum())
        for label in np.unique(labels) if label >= 0
    }
    largest_label = max(cluster_sizes, key=cluster_sizes.get)
    cluster_points = points[labels == largest_label]
    # Camera Y points down; use the opposite mean camera Y as a robust up estimate.
    camera_down = np.asarray([
        np.asarray(item.cam_from_world().rotation.matrix(), dtype=float).T[:, 1]
        for item in images.values()
    ])
    up = -camera_down.mean(axis=0)
    up /= np.linalg.norm(up)
    horizontal = points - np.outer(points @ up, up)
    covariance = np.cov(horizontal.T)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    axes = eigenvectors[:, order]
    projected = np.column_stack((points @ axes[:, 0], points @ axes[:, 1], points @ up))
    extents = np.percentile(projected, 99.0, axis=0) - np.percentile(projected, 1.0, axis=0)
    cluster_projected = np.column_stack((cluster_points @ axes[:, 0], cluster_points @ axes[:, 1], cluster_points @ up))
    cluster_extents = np.percentile(cluster_projected, 99.0, axis=0) - np.percentile(cluster_projected, 1.0, axis=0)
    measurement = {
        'frame_count': len(FRAMES),
        'raw_points_before_filter': int(sum(len(item) for item in world_points)),
        'raw_points_after_statistical_filter': int(len(points)),
        'dbscan_cluster_count': len(cluster_sizes),
        'dbscan_largest_cluster_label': int(largest_label),
        'dbscan_largest_cluster_points': int(len(cluster_points)),
        'dbscan_top_cluster_sizes': sorted(cluster_sizes.values(), reverse=True)[:10],
        'selected_masks': selected,
        'frame_world_stats': frame_stats,
        'up_axis_colmap_world': up.tolist(),
        'horizontal_pca_axes_colmap_world': axes[:, :2].T.tolist(),
        'horizontal_extent_axis0_colmap_units': float(extents[0]),
        'horizontal_extent_axis1_colmap_units': float(extents[1]),
        'vertical_extent_colmap_units': float(extents[2]),
        'width_candidate_colmap_units': float(max(extents[0], extents[1])),
        'cluster_width_candidate_colmap_units': float(max(cluster_extents[0], cluster_extents[1])),
        'cluster_horizontal_extent_axis0_colmap_units': float(cluster_extents[0]),
        'cluster_horizontal_extent_axis1_colmap_units': float(cluster_extents[1]),
        'width_candidate_reason': 'larger horizontal PCA extent is the outside armrest-to-armrest axis for this chair view set',
    }
    OUT.write_text(json.dumps(measurement, indent=2) + '\n')
    print(json.dumps(measurement, indent=2))


if __name__ == '__main__':
    main()
