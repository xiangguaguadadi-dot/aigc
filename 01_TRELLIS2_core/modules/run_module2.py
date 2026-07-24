#!/usr/bin/env python3
"""
Module 2: Object-Centric Reconstruction
========================================
Labeled point cloud → per-object watertight mesh → .glb assets

Usage:
    # From Module 1 output (labeled point cloud)
    python run_pipeline.module2_reconstruction.py --input output_module1/labeled_scene.ply --output ./assets

    # From per-object PLY files
    python run_pipeline.module2_reconstruction.py --input-dir output_module1/per_object/ --output ./assets

    # Tune quality
    python run_pipeline.module2_reconstruction.py --input scene.ply --output ./assets --method poisson --depth 10
"""

import argparse
import sys
import os
import time
import json
import glob
from pathlib import Path

import numpy as np

from pipeline.module2_reconstruction.pipeline import ReconstructionPipeline


def load_labeled_ply(path: str):
    """Load a PLY with object_id vertex property (output of Module 1)."""
    try:
        import open3d as o3d
    except ImportError:
        print("open3d required. pip install open3d")
        sys.exit(1)

    pcd = o3d.io.read_point_cloud(path)
    if len(pcd.points) == 0:
        raise ValueError(f"Empty point cloud: {path}")

    points = np.asarray(pcd.points).astype(np.float32)
    colors = np.asarray(pcd.colors)
    if colors.max() <= 1.0:
        colors = (colors * 255).astype(np.uint8)
    else:
        colors = colors.astype(np.uint8)

    # Read object_id attribute if present; otherwise all = 0
    try:
        # Re-read with full attributes
        pcd_full = o3d.t.io.read_point_cloud(path)
        labels = pcd_full.point.object_id.numpy().flatten().astype(np.int32)
    except Exception:
        labels = np.zeros(len(points), dtype=np.int32)

    return points, colors, labels


def load_per_object_ply_dir(directory: str):
    """Load from directory of per-object PLY files."""
    ply_files = sorted(glob.glob(os.path.join(directory, "*.ply")))

    all_points, all_colors, all_labels = [], [], []
    label_names = {}

    for i, ply_path in enumerate(ply_files):
        name = Path(ply_path).stem
        try:
            import open3d as o3d
            pcd = o3d.io.read_point_cloud(ply_path)
        except ImportError:
            continue

        pts = np.asarray(pcd.points).astype(np.float32)
        cols = np.asarray(pcd.colors)
        if cols.max() <= 1.0:
            cols = (cols * 255).astype(np.uint8)

        all_points.append(pts)
        all_colors.append(cols)
        all_labels.append(np.full(len(pts), i, dtype=np.int32))
        label_names[i] = name.split("_")[0] if "_" in name else name

    if not all_points:
        raise ValueError("No valid PLY files found")

    return (
        np.concatenate(all_points),
        np.concatenate(all_colors),
        np.concatenate(all_labels),
        label_names,
    )


def main():
    parser = argparse.ArgumentParser(description="Module 2: Object-Centric Reconstruction")
    parser.add_argument("--input", default=None,
                        help="Path to labeled PLY (from Module 1)")
    parser.add_argument("--input-dir", default=None,
                        help="Directory of per-object PLY files")
    parser.add_argument("--output", "-o", default="./assets_module2",
                        help="Output directory for .glb assets")
    parser.add_argument("--method", default="poisson", choices=["poisson", "alpha_shape"],
                        help="Mesh reconstruction method")
    parser.add_argument("--depth", type=int, default=9,
                        help="Poisson octree depth (8-10)")
    parser.add_argument("--alpha", type=float, default=0.03,
                        help="Alpha shape parameter (smaller=tighter)")
    parser.add_argument("--min-points", type=int, default=200,
                        help="Minimum points per object")
    parser.add_argument("--no-fill-holes", action="store_true",
                        help="Skip hole-filling pass")
    parser.add_argument("--no-normalize", action="store_true",
                        help="Keep original coordinates")
    parser.add_argument("--downsample", type=int, default=1,
                        help="Downsample factor (1=full)")
    args = parser.parse_args()

    # ---- Load data ----
    if args.input:
        print(f"Loading labeled PLY: {args.input}")
        points, colors, labels = load_labeled_ply(args.input)
        # Try to read label_names from companion JSON
        meta_path = os.path.join(os.path.dirname(args.input), "segmentation_meta.json")
        label_names = {}
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
            label_names = {int(k): v for k, v in meta.get("label_mapping", {}).items()}
    elif args.input_dir:
        print(f"Loading from directory: {args.input_dir}")
        points, colors, labels, label_names = load_per_object_ply_dir(args.input_dir)
    else:
        print("ERROR: --input or --input-dir required")
        sys.exit(1)

    print(f"  {len(points):,} points, {len(np.unique(labels))} objects")

    # ---- Run pipeline ----
    pipeline = ReconstructionPipeline(
        method=args.method,
        depth=args.depth,
        alpha=args.alpha,
        min_points=args.min_points,
        fill_holes=not args.no_fill_holes,
        downsample=args.downsample,
        normalize=not args.no_normalize,
    )

    t0 = time.time()
    result = pipeline.run(
        points=points,
        colors=colors,
        labels=labels,
        label_names=label_names,
        output_dir=args.output,
    )

    t_total = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Module 2 complete in {t_total:.1f}s")
    print(f"  Assets exported: {len(result)}")
    print(f"  Output: {os.path.abspath(args.output)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
