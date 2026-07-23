#!/usr/bin/env python3
"""
Module 3: Physical Parameter Inference
=======================================
.glb assets → material (CLIP) → mass/density → collision hull → physics JSON

Usage:
    # Single object
    python run_pipeline.module3_physics.py --glb assets/table_000.glb

    # Batch from Module 2 output
    python run_pipeline.module3_physics.py --glb-dir ./assets/ --material-map "table:wood,chair:metal,cup:ceramic"

    # Skip CLIP (manual materials)
    python run_pipeline.module3_physics.py --glb-dir ./assets/ --no-clip --material-map "table:wood"
"""

import argparse
import sys
import os
import time
import json

from pipeline.module3_physics.pipeline import PhysicsPipeline


def parse_material_map(s: str) -> dict:
    """Parse 'table:wood,chair:metal,cup:ceramic' → dict."""
    if not s:
        return {}
    result = {}
    for pair in s.split(","):
        k, v = pair.strip().split(":")
        result[k.strip()] = v.strip()
    return result


def main():
    parser = argparse.ArgumentParser(description="Module 3: Physical Parameter Inference")
    parser.add_argument("--glb", default=None,
                        help="Single .glb file to process")
    parser.add_argument("--glb-dir", default=None,
                        help="Directory of .glb files to batch-process")
    parser.add_argument("--output", "-o", default=None,
                        help="Output directory (default: same as input)")
    parser.add_argument("--no-clip", action="store_true",
                        help="Disable CLIP material classification")
    parser.add_argument("--material-map", default=None,
                        help='Override materials: "table:wood,chair:metal,cup:ceramic"')
    parser.add_argument("--device", default="cuda",
                        help="Device (cuda/cpu)")
    args = parser.parse_args()

    material_map = parse_material_map(args.material_map or "")

    pipeline = PhysicsPipeline(
        device=args.device,
        use_clip=not args.no_clip,
    )

    t0 = time.time()

    if args.glb:
        result = pipeline.run_from_glb(
            args.glb,
            output_dir=args.output,
            material_override=material_map.get(None),
        )
        print(f"\n  Material: {result['material']['label']}")
        print(f"  Mass:     {result['physics']['mass_kg']:.3f} kg")
        print(f"  Friction: {result['physics']['friction']:.2f}")
        print(f"  Collision: {result['collision']['type']}")

    elif args.glb_dir:
        results = pipeline.run_batch(
            args.glb_dir,
            output_dir=args.output,
            material_map=material_map,
        )
        print(f"\n  Processed {len(results)} objects")

    else:
        print("ERROR: --glb or --glb-dir required")
        sys.exit(1)

    print(f"\n  Module 3 complete in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
