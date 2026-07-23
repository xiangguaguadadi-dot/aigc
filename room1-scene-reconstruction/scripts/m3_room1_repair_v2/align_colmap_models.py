#!/usr/bin/env python3
"""Estimate a robust Sim(3) from the anchor submodel into the main COLMAP model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pycolmap
from scipy.spatial import cKDTree


def image_by_name(reconstruction: pycolmap.Reconstruction, name: str):
    for image in reconstruction.images.values():
        if image.name == name:
            return image
    raise KeyError(name)


def umeyama(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    covariance = target_centered.T @ source_centered / len(source)
    u, singular, vt = np.linalg.svd(covariance)
    sign = np.ones(3)
    if np.linalg.det(u @ vt) < 0:
        sign[-1] = -1
    rotation = u @ np.diag(sign) @ vt
    variance = np.mean(np.sum(source_centered * source_centered, axis=1))
    scale = float(np.sum(singular * sign) / variance)
    translation = target_mean - scale * rotation @ source_mean
    return scale, rotation, translation


def transform(points: np.ndarray, scale: float, rotation: np.ndarray,
              translation: np.ndarray) -> np.ndarray:
    return (scale * (rotation @ points.T)).T + translation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--anchor', type=Path, required=True)
    parser.add_argument('--common-image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    main_recon = pycolmap.Reconstruction(str(args.main))
    anchor_recon = pycolmap.Reconstruction(str(args.anchor))
    main_image = image_by_name(main_recon, args.common_image)
    anchor_image = image_by_name(anchor_recon, args.common_image)
    main_points = [point for point in main_image.points2D if point.has_point3D()]
    anchor_points = [point for point in anchor_image.points2D if point.has_point3D()]
    main_xy = np.asarray([point.xy for point in main_points], dtype=np.float64)
    anchor_xy = np.asarray([point.xy for point in anchor_points], dtype=np.float64)
    tree = cKDTree(main_xy)
    distances, indices = tree.query(anchor_xy, distance_upper_bound=1.5)
    source, target, feature_indices = [], [], []
    used_main: set[int] = set()
    for anchor_index, (distance, main_index) in enumerate(zip(distances, indices)):
        if not np.isfinite(distance) or main_index >= len(main_points) or int(main_index) in used_main:
            continue
        main_point = main_points[int(main_index)]
        anchor_point = anchor_points[anchor_index]
        main_id = int(main_point.point3D_id)
        anchor_id = int(anchor_point.point3D_id)
        if main_id not in main_recon.points3D or anchor_id not in anchor_recon.points3D:
            continue
        used_main.add(int(main_index))
        source.append(np.asarray(anchor_recon.points3D[anchor_id].xyz, dtype=np.float64))
        target.append(np.asarray(main_recon.points3D[main_id].xyz, dtype=np.float64))
        feature_indices.append(anchor_index)
    source = np.asarray(source)
    target = np.asarray(target)
    if len(source) < 6:
        nearest = float(np.min(distances)) if len(distances) else None
        raise SystemExit(
            f'too few shared triangulated features: {len(source)}; '
            f'main_observations={len(main_points)} anchor_observations={len(anchor_points)} '
            f'nearest_pixel_distance={nearest}'
        )

    rng = np.random.default_rng(20260723)
    threshold = 0.10
    best_inliers = np.zeros(len(source), dtype=bool)
    best_median = float('inf')
    for _ in range(5000):
        sample = rng.choice(len(source), 3, replace=False)
        try:
            scale, rotation, translation = umeyama(source[sample], target[sample])
        except np.linalg.LinAlgError:
            continue
        if not np.isfinite(scale) or scale <= 0:
            continue
        residuals = np.linalg.norm(transform(source, scale, rotation, translation) - target, axis=1)
        inliers = residuals <= threshold
        if inliers.sum() < 3:
            continue
        median = float(np.median(residuals[inliers]))
        if inliers.sum() > best_inliers.sum() or (
            inliers.sum() == best_inliers.sum() and median < best_median
        ):
            best_inliers = inliers
            best_median = median
    if best_inliers.sum() < 6:
        raise SystemExit(f'insufficient Sim(3) inliers: {best_inliers.sum()}/{len(source)}')

    scale, rotation, translation = umeyama(source[best_inliers], target[best_inliers])
    residuals = np.linalg.norm(transform(source, scale, rotation, translation) - target, axis=1)
    refined_inliers = residuals <= threshold
    scale, rotation, translation = umeyama(source[refined_inliers], target[refined_inliers])
    residuals = np.linalg.norm(transform(source, scale, rotation, translation) - target, axis=1)

    matrix = np.eye(4)
    matrix[:3, :3] = scale * rotation
    matrix[:3, 3] = translation
    report = {
        'source_model': str(args.anchor),
        'target_model': str(args.main),
        'common_image': args.common_image,
        'shared_triangulated_feature_count': len(source),
        'inlier_count': int(refined_inliers.sum()),
        'inlier_ratio': float(refined_inliers.mean()),
        'ransac_threshold_main_units': threshold,
        'scale_main_units_per_anchor_unit': scale,
        'rotation_determinant': float(np.linalg.det(rotation)),
        'inlier_rmse_main_units': float(np.sqrt(np.mean(residuals[refined_inliers] ** 2))),
        'inlier_median_main_units': float(np.median(residuals[refined_inliers])),
        'anchor_to_main_similarity': matrix.tolist(),
        'inlier_feature_indices': np.asarray(feature_indices)[refined_inliers].tolist(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
