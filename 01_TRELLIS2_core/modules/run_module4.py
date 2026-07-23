#!/usr/bin/env python3
"""
Module 4: Scene Assembly & Physics Engine
==========================================
Load Module 3 physics assets → build PyBullet scene → simulate gravity

Usage:
    python run_pipeline.module4_simulation.py --physics-dir ./m3_output --output ./m4_output

    # With original poses from Module 1
    python run_pipeline.module4_simulation.py --physics-dir ./m3_output --labeled-pcd scene.ply

    # With GUI (watch simulation)
    python run_pipeline.module4_simulation.py --physics-dir ./m3_output --gui

    # Longer settle time
    python run_pipeline.module4_simulation.py --physics-dir ./m3_output --settle-time 5.0
"""

import argparse
import sys
import os
import time
import json

from pipeline.module4_simulation.pipeline import SimulationPipeline


def main():
    parser = argparse.ArgumentParser(description="Module 4: Scene Assembly & Physics")
    parser.add_argument("--physics-dir", required=True,
                        help="Module 3 output directory (physics assets)")
    parser.add_argument("--output", "-o", default="./output_module4")
    parser.add_argument("--labeled-pcd", default=None,
                        help="Module 1 labeled PLY for original poses")
    parser.add_argument("--gui", action="store_true",
                        help="Show PyBullet GUI window")
    parser.add_argument("--settle-time", type=float, default=3.0,
                        help="Simulation time in seconds")
    parser.add_argument("--ground-height", type=float, default=-2.0,
                        help="Ground plane Y position")
    parser.add_argument("--scale-factor", type=float, default=1.0,
                        help="Real-world meter-to-unit scale")
    args = parser.parse_args()

    # Load label names from Module 1 meta if available
    label_names = None
    if args.labeled_pcd:
        meta_path = os.path.join(os.path.dirname(args.labeled_pcd), "segmentation_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
            label_names = {int(k): v for k, v in meta.get("label_mapping", {}).items()}

    pipeline = SimulationPipeline(
        gui=args.gui,
        settle_time=args.settle_time,
    )

    t0 = time.time()
    result = pipeline.run(
        physics_dir=args.physics_dir,
        output_dir=args.output,
        labeled_pcd=args.labeled_pcd,
        label_names=label_names,
        ground_height=args.ground_height,
        scale_factor=args.scale_factor,
    )

    print(f"\n{'='*60}")
    print(f"  Module 4 complete in {time.time()-t0:.1f}s")
    print(f"  Objects simulated: {result['scene_graph'].objects.__len__()}")
    print(f"  Output: {os.path.abspath(args.output)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
