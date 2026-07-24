#!/usr/bin/env python3
"""
Full Pipeline: Photo → TRELLIS.2 → 3D → M1→M2→M3→M4→M5 → Physics Asset

Usage:
    python run_pipeline.py --image photo.jpg --output ./results
    python run_pipeline.py --image photo.jpg --mode single --material wood
"""

import argparse, os, sys, time, json, subprocess, tempfile, shutil
from pathlib import Path
import numpy as np

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pre-model"))


def main():
    parser = argparse.ArgumentParser(description="Full Pipeline: Photo → Physics Asset")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", "-o", default="./output")
    parser.add_argument("--mode", default="single", choices=["single", "multi"])
    parser.add_argument("--prompt", default="object")
    parser.add_argument("--material", default=None)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    t_start = time.time()

    # ============================================================
    # Step 0: TRELLIS.2 → 3D Mesh
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  [0/5] TRELLIS.2: Image → 3D Mesh")
    print(f"{'='*60}")

    glb_path = os.path.join(args.output, "model.glb")

    # Run generate.py from pre-model
    generate_script = os.path.join(PROJECT_ROOT, "pre-model", "generate.py")
    if os.path.exists(generate_script):
        cmd = [
            sys.executable, generate_script,
            args.image, "-o", glb_path, "--steps", str(args.steps),
        ]
        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        print(result.stdout[-1500:])
        if result.returncode != 0:
            print(f"  TRELLIS.2 failed: {result.stderr[-500:]}")
            sys.exit(1)
    else:
        print(f"  TRELLIS.2 not found at {generate_script}")
        print("  Skipping — using existing GLB if available")
        if not os.path.exists(glb_path):
            sys.exit(1)

    size_mb = os.path.getsize(glb_path) / 1024**2
    print(f"  → {glb_path} ({size_mb:.1f} MB)")

    # ============================================================
    # Load GLB mesh
    # ============================================================
    import trimesh
    mesh = trimesh.load(glb_path)
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    vertices = mesh.vertices.astype(np.float32)
    faces = mesh.faces.astype(np.int32)
    print(f"  Mesh: {len(vertices):,} vertices, {len(faces):,} faces")

    # ============================================================
    # Module 1: Perception (single-object: label from prompt)
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  [1/5] Module 1: Perception & Segmentation")
    print(f"{'='*60}")

    label = args.prompt.strip().split(".")[0].strip()
    label_names = {0: label}
    labels = np.zeros(len(vertices), dtype=np.int32)
    colors = np.full((len(vertices), 3), 180, dtype=np.uint8)  # default gray

    # If mesh has vertex colors, use them
    if hasattr(mesh.visual, 'vertex_colors') and mesh.visual.vertex_colors is not None:
        colors = mesh.visual.vertex_colors[:, :3].astype(np.uint8)

    print(f"  Labeled as: '{label}'")

    # ============================================================
    # Module 2: Reconstruction
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  [2/5] Module 2: Object-Centric Reconstruction")
    print(f"{'='*60}")

    from pipeline.module2_reconstruction.pipeline import ReconstructionPipeline
    m2_dir = os.path.join(args.output, "m2_assets")
    pipeline_m2 = ReconstructionPipeline(method="poisson", depth=8, min_points=10)
    m2_result = pipeline_m2.run(vertices, colors, labels, label_names, m2_dir)

    # ============================================================
    # Module 3: Physics
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  [3/5] Module 3: Physics Parameters")
    print(f"{'='*60}")

    from pipeline.module3_physics.pipeline import PhysicsPipeline
    m3_dir = os.path.join(args.output, "m3_physics")
    pipeline_m3 = PhysicsPipeline(device=args.device)
    m3_result = pipeline_m3.run_batch(
        m2_dir, m3_dir,
        material_map={label: args.material} if args.material else None,
    )

    # ============================================================
    # Module 4: Simulation
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  [4/5] Module 4: Physics Simulation")
    print(f"{'='*60}")

    from pipeline.module4_simulation.pipeline import SimulationPipeline
    m4_dir = os.path.join(args.output, "m4_simulation")
    pipeline_m4 = SimulationPipeline(gui=False, settle_time=2.0)
    m4_result = pipeline_m4.run(m3_dir, m4_dir)

    # ============================================================
    # Module 5: Interaction
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  [5/5] Module 5: Interaction Demo")
    print(f"{'='*60}")

    from pipeline.module5_interaction.controller import InteractionController
    m5_dir = os.path.join(args.output, "m5_interaction")
    os.makedirs(m5_dir, exist_ok=True)

    ctrl = InteractionController(gui=False)
    ctrl.load_settled_scene(
        os.path.join(m4_dir, "settled_state.json"),
        os.path.join(m4_dir, "scene_description.json"),
    )

    import pybullet as p
    names = [n for n in ctrl._body_map if n != "ground"]
    if names:
        target = ctrl.get_body_id(names[0])
        pos, _ = p.getBasePositionAndOrientation(target)
        ctrl.grasp(target, pos, max_force=1000)
        ctrl.drag_delta((0, 2.0, 0))
        ctrl.step(120)
        ctrl.release(transfer_velocity=True)
        ctrl.step(240)

    states = ctrl.get_all_states()
    with open(os.path.join(m5_dir, "interaction_result.json"), "w") as f:
        json.dump(states, f, indent=2, default=str)
    ctrl.close()
    print(f"  Interaction complete: {len(states)} objects")

    # ============================================================
    # Summary
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  Pipeline Complete!")
    print(f"  Total time: {time.time()-t_start:.1f}s")
    print(f"  Output: {os.path.abspath(args.output)}")
    print(f"  Sub-dirs: {os.listdir(args.output)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
