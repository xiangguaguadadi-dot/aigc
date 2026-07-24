"""
Module 4 Pipeline: Scene Assembly → Physics Simulation.
"""

import os
import time
import json
from typing import Dict, Optional

from pipeline.module4_simulation.scene import (
    load_physics_assets, build_scene,
    extract_poses_from_module1, SceneGraph,
)
from pipeline.module4_simulation.simulator import (
    PyBulletSimulator, export_settled_scene,
)


class SimulationPipeline:
    """
    Module 4: Load assets, build scene, simulate physics.

    Usage:
        pipeline = SimulationPipeline(gui=False)
        pipeline.run(physics_dir="./m3_output", output_dir="./m4_output")
    """

    def __init__(self, gui: bool = False, settle_time: float = 3.0):
        self.gui = gui
        self.settle_time = settle_time
        self.simulator = PyBulletSimulator(gui=gui)

    def run(
        self,
        physics_dir: str,
        output_dir: str = "./output_module4",
        labeled_pcd: Optional[str] = None,
        label_names: Optional[Dict[int, str]] = None,
        ground_height: float = -2.0,  # below objects so they fall
        scale_factor: float = 1.0,
    ) -> dict:
        """
        Full pipeline.

        Parameters
        ----------
        physics_dir : str  Module 3 output directory
        output_dir : str
        labeled_pcd : str or None  Module 1 labeled PLY for original poses
        label_names : dict or None  id → semantic name
        ground_height : float  ground plane Y coordinate
        scale_factor : float  meter-to-unit conversion

        Returns
        -------
        result : dict  keys: settled_states, scene_graph, output_files
        """
        os.makedirs(output_dir, exist_ok=True)

        # ---- 1. Load assets ----
        print(f"\n[Step 1/4] Loading physics assets from {physics_dir}...")
        t0 = time.time()
        assets = load_physics_assets(physics_dir)
        print(f"  Loaded {len(assets)} assets ({time.time()-t0:.1f}s)")

        # ---- 2. Extract poses (optional) ----
        object_poses = None
        if labeled_pcd and label_names:
            print(f"\n[Step 2/4] Extracting poses from labeled point cloud...")
            object_poses = extract_poses_from_module1(labeled_pcd, label_names)
            print(f"  Found poses for {len(object_poses)} objects")
        else:
            print(f"\n[Step 2/4] Using default poses (no original scene data)")

        # ---- 3. Build scene ----
        print(f"\n[Step 3/4] Building physics scene...")
        scene = build_scene(
            assets,
            object_poses=object_poses,
            ground_height=ground_height,
            scale_factor=scale_factor,
        )
        print(f"  Scene: {len(scene.objects)} objects (1 ground + {len(scene.objects)-1} dynamic)")

        # ---- 4. Simulate ----
        print(f"\n[Step 4/4] Running physics simulation...")
        t0 = time.time()

        self.simulator.load_scene(scene)
        print(f"  Simulating {self.settle_time}s of physics...")

        self.simulator.step_seconds(self.settle_time)
        states = self.simulator.get_object_states()

        print(f"  Simulation complete ({time.time()-t0:.1f}s)")

        # ---- Export ----
        states_path = os.path.join(output_dir, "settled_state.json")
        export_settled_scene(self.simulator, states_path)

        # Export scene description
        scene_desc = {
            "num_objects": len(scene.objects),
            "ground_height": ground_height,
            "gravity": scene.gravity,
            "objects": [
                {
                    "name": obj.name,
                    "mass_kg": obj.mass_kg,
                    "friction": obj.friction,
                    "is_static": obj.is_static,
                    "settled_position": states.get(obj.name, {}).get("position"),
                }
                for obj in scene.objects
            ],
        }
        scene_path = os.path.join(output_dir, "scene_description.json")
        with open(scene_path, "w") as f:
            json.dump(scene_desc, f, indent=2)

        # Render a frame if possible
        frame = self.simulator.render_frame()
        if frame is not None:
            from PIL import Image
            frame_path = os.path.join(output_dir, "simulation_frame.png")
            Image.fromarray(frame).save(frame_path)

        self.simulator.close()

        print(f"\n  Exported: {states_path}")
        print(f"  Exported: {scene_path}")

        return {
            "settled_states": states,
            "scene_graph": scene,
            "output_files": [states_path, scene_path],
        }
