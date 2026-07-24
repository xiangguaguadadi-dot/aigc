#!/usr/bin/env python3
"""
Module 1: Perception & Instance Segmentation
=============================================
Grounding DINO + SAM → 2D masks → 3D labeled point cloud

Usage:
    # 2D only (no depth)
    python run_pipeline.module1_perception.py --image room.jpg --prompt "chair . table . sofa"

    # 2D + 3D lifting (with depth & camera)
    python run_pipeline.module1_perception.py --image room.jpg --depth depth.npy --intrinsic 525,0,320,0,525,240,0,0,1

    # Cloud GPU mode (auto-install deps)
    python run_pipeline.module1_perception.py --image room.jpg --setup
"""

import argparse
import sys
import os
import time
import json
from pathlib import Path

import numpy as np
from PIL import Image

from pipeline.module1_perception.config import SegmentationConfig
from pipeline.module1_perception.pipeline import SegmentationPipeline


def parse_intrinsic(s: str) -> np.ndarray:
    """Parse 'fx,0,cx,0,fy,cy,0,0,1' or 'fx,cx,fy,cy' → (3,3) matrix."""
    vals = [float(x) for x in s.split(",")]
    if len(vals) == 4:
        fx, cx, fy, cy = vals
        return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    elif len(vals) == 9:
        return np.array(vals, dtype=np.float64).reshape(3, 3)
    else:
        raise ValueError(f"Expected 4 or 9 values for intrinsic, got {len(vals)}")


def main():
    parser = argparse.ArgumentParser(description="Module 1: Perception & Segmentation")
    parser.add_argument("--image", required=True, help="Path to input RGB image")
    parser.add_argument("--depth", default=None, help="Path to depth map (.npy or .png)")
    parser.add_argument("--intrinsic", default=None,
                        help="Camera intrinsic: fx,cx,fy,cy or full 3x3 (comma-separated)")
    parser.add_argument("--prompt", default=None,
                        help="Text prompt, e.g. 'chair . table . sofa'")
    parser.add_argument("--output", "-o", default="./output_module1",
                        help="Output directory")
    parser.add_argument("--box-threshold", type=float, default=0.35)
    parser.add_argument("--text-threshold", type=float, default=0.25)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--setup", action="store_true",
                        help="Auto-install dependencies on cloud GPU")
    args = parser.parse_args()

    # ---- Auto-setup on cloud GPU ----
    if args.setup:
        _auto_setup()

    # ---- Load image ----
    rgb = np.array(Image.open(args.image).convert("RGB"))
    print(f"Loaded image: {rgb.shape}")

    # ---- Load depth (optional) ----
    depth_map = None
    if args.depth:
        if args.depth.endswith(".npy"):
            depth_map = np.load(args.depth)
        else:
            depth_map = np.array(Image.open(args.depth)).astype(np.float32)
            if depth_map.ndim == 3:
                depth_map = depth_map.mean(axis=-1)
        print(f"Loaded depth: {depth_map.shape}")

    # ---- Parse intrinsic (optional) ----
    intrinsic = None
    if args.intrinsic:
        intrinsic = parse_intrinsic(args.intrinsic)
        print(f"Intrinsic:\n{intrinsic}")

    # ---- Config ----
    config = SegmentationConfig()
    config.output_dir = args.output
    config.device = args.device
    config.gdino_box_threshold = args.box_threshold
    config.gdino_text_threshold = args.text_threshold
    if args.prompt:
        config.text_prompt = args.prompt

    # ---- Run pipeline ----
    t0 = time.time()
    pipeline = SegmentationPipeline(config)
    result = pipeline.run(
        rgb_image=rgb,
        depth_map=depth_map,
        intrinsic_3x3=intrinsic,
        text_prompt=args.prompt,
    )

    # ---- Export ----
    exported = pipeline.export(result, args.output)

    t_total = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Module 1 complete in {t_total:.1f}s")
    print(f"  Objects found: {len(result['labels'])}")
    print(f"  Labels: {result['labels']}")
    if result["labeled_pcd"] is not None:
        pts, _, _ = result["labeled_pcd"]
        print(f"  Labeled 3D points: {len(pts):,}")
    print(f"  Output: {os.path.abspath(args.output)}")
    print(f"{'='*60}")


def _auto_setup():
    """Auto-install dependencies on cloud GPU."""
    import subprocess
    deps = [
        "groundingdino-py",
        "segment-anything",
        "huggingface_hub",
        "matplotlib",
        "opencv-python",
    ]
    print("[Setup] Installing dependencies...")
    for dep in deps:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", dep], check=False)
    print("[Setup] Done.")


if __name__ == "__main__":
    main()
