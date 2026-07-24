#!/usr/bin/env python3
"""
Module 5: Interaction Controller
=================================
Ray casting → grasp → drag → push → throw demo.

Usage:
    # Full demo with all interactions
    python run_pipeline.module5_interaction.py --scene ./m4_output/settled_state.json

    # Interactive mode (requires display)
    python run_pipeline.module5_interaction.py --scene ./m4_output/settled_state.json --gui

    # Programmatic demo (no GUI)
    python run_pipeline.module5_interaction.py --scene ./m4_output/settled_state.json --demo
"""

import argparse
import sys
import os
import time
import json
import numpy as np

from pipeline.module5_interaction.controller import InteractionController
from pipeline.module5_interaction.interaction import ray_cast, apply_push, throw_object


def run_demo(ctrl: InteractionController, output_dir: str):
    """
    Run a scripted demo of all interaction primitives.
    """
    os.makedirs(output_dir, exist_ok=True)
    log = []

    # Find a dynamic object
    obj_names = [n for n in ctrl._body_map.keys() if n != "ground"]
    if not obj_names:
        print("No objects to interact with!")
        return

    target_name = obj_names[0]
    target_id = ctrl.get_body_id(target_name)
    print(f"\n  Target: {target_name} (id={target_id})")

    import pybullet as p

    # ---- 1. Ray Cast ----
    print("\n[1] Ray Casting...")
    # Shoot ray from above toward the object's position
    target_pos, _ = p.getBasePositionAndOrientation(target_id)
    camera_pos = (target_pos[0] + 2, target_pos[1] + 3, target_pos[2] + 2)
    direction = (
        target_pos[0] - camera_pos[0],
        target_pos[1] - camera_pos[1],
        target_pos[2] - camera_pos[2],
    )
    hit = ctrl.ray_pick_world(camera_pos, direction)
    if hit:
        print(f"  Hit: {hit['object_name']} at {hit['hit_position']}")
        log.append({"action": "ray_cast", "result": hit})
    else:
        print(f"  Ray miss (tried to hit {target_name})")
        log.append({"action": "ray_cast", "result": "miss"})

    # ---- 2. Grasp ----
    print("\n[2] Grasping...")
    pos, _ = p.getBasePositionAndOrientation(target_id)
    print(f"  Object at: {pos}")
    ctrl.grasp(target_id, pos, max_force=1000)
    ctrl.step(60)
    log.append({"action": "grasp", "body_id": target_id, "position": list(pos)})

    # ---- 3. Drag upward ----
    print("\n[3] Dragging upward...")
    new_pos = np.array(pos) + np.array([0, 2.0, 0])
    ctrl.drag_to_world(new_pos.tolist())
    ctrl.step(60)
    pos2, _ = p.getBasePositionAndOrientation(target_id)
    print(f"  Now at: {pos2}  (lifted {pos2[1]-pos[1]:.2f}m)")
    log.append({"action": "drag", "from": list(pos), "to": list(new_pos)})

    # ---- 4. Push ----
    print("\n[4] Pushing with impulse...")
    ctrl.push(target_id, (5.0, 0, 0))
    ctrl.step(120)  # let it fly a bit
    pos3, _ = p.getBasePositionAndOrientation(target_id)
    print(f"  After push at: {pos3}")
    log.append({"action": "push", "force": [5.0, 0, 0]})

    # ---- 5. Release (throw) ----
    print("\n[5] Releasing (throw)...")
    ctrl.release(transfer_velocity=True)
    # Let physics run
    for _ in range(240):  # 1 second
        ctrl.step(1)
    pos4, _ = p.getBasePositionAndOrientation(target_id)
    print(f"  Final position: {pos4}")
    log.append({"action": "release_throw", "final_position": list(pos4)})

    # ---- 6. Final state ----
    print("\n[6] Final state:")
    states = ctrl.get_all_states()
    for name, s in states.items():
        if name != "ground":
            print(f"  {name}: pos={[round(x,2) for x in s['position']]}")

    # Export log
    log_path = os.path.join(output_dir, "interaction_log.json")
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\n  Log: {log_path}")

    # Export final state
    state_path = os.path.join(output_dir, "final_state.json")
    with open(state_path, "w") as f:
        json.dump(states, f, indent=2)
    print(f"  State: {state_path}")


def main():
    parser = argparse.ArgumentParser(description="Module 5: Interaction Controller")
    parser.add_argument("--scene", required=True,
                        help="Module 4 settled_state.json")
    parser.add_argument("--scene-desc", default=None,
                        help="Module 4 scene_description.json")
    parser.add_argument("--output", "-o", default="./output_module5")
    parser.add_argument("--gui", action="store_true",
                        help="Show PyBullet GUI")
    parser.add_argument("--demo", action="store_true", default=True,
                        help="Run scripted demo (default)")
    args = parser.parse_args()

    ctrl = InteractionController(gui=args.gui)
    ctrl.load_settled_scene(args.scene, args.scene_desc)

    print(f"  Loaded {len(ctrl._body_map)} objects")

    t0 = time.time()

    if args.demo:
        run_demo(ctrl, args.output)

    ctrl.close()

    print(f"\n{'='*60}")
    print(f"  Module 5 complete in {time.time()-t0:.1f}s")
    print(f"  Output: {os.path.abspath(args.output)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
