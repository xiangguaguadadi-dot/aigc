"""
Module 3 Pipeline: VLM-powered Physical Parameter Inference.
"""

import os
import time
import json
from typing import Dict, Optional, List
from pathlib import Path

import numpy as np

from pipeline.module3_physics.material import (
    VLMPhysicsAnalyzer, get_physics_params, _default_properties,
)
from pipeline.module3_physics.physics import generate_collision_body


class PhysicsPipeline:
    """
    Module 3: Infer physical parameters for each object.

    Uses VLM (Qwen2-VL) to analyze the original photo → structured physics.
    Falls back to per-category defaults if VLM unavailable.
    """

    def __init__(self, device: str = "cuda"):
        self.device = device
        self._vlm = None

    @property
    def vlm(self):
        if self._vlm is None:
            print("  Loading Qwen2-VL-2B...")
            t0 = time.time()
            try:
                self._vlm = VLMPhysicsAnalyzer(device=self.device)
                print(f"  VLM loaded ({time.time()-t0:.1f}s)")
            except Exception as e:
                print(f"  VLM unavailable ({e}), using defaults")
                self._vlm = None
        return self._vlm

    def run_batch(
        self,
        glb_dir: str,
        output_dir: Optional[str] = None,
        material_map: Optional[Dict[str, str]] = None,
        reference_image: Optional[np.ndarray] = None,
        object_labels: Optional[List[str]] = None,
    ) -> list:
        """
        Process all .glb files in a directory.
        """
        import glob
        glb_files = sorted(glob.glob(os.path.join(glb_dir, "*.glb")))
        glb_files = [f for f in glb_files if "_collision" not in f and "_physics" not in f]

        output_dir = output_dir or glb_dir
        os.makedirs(output_dir, exist_ok=True)

        # --- Run VLM analysis on the original photo ---
        vlm_results = {}
        if reference_image is not None and object_labels:
            if self.vlm is not None:
                try:
                    vlm_results_list = self.vlm.analyze(reference_image, object_labels)
                    vlm_results = {r["name"]: r for r in vlm_results_list}
                    print(f"  VLM analyzed {len(vlm_results)} objects from photo")
                    for name, props in vlm_results.items():
                        print(f"    {name}: {props['material']}, {props['diameter_cm']}cm, {props['mass_kg']}kg")
                except Exception as e:
                    print(f"  VLM analysis failed: {e}")
            else:
                print("  Using category defaults (VLM not loaded)")
                vlm_results = {lbl: _default_properties(lbl) for lbl in object_labels}

        # --- Process each GLB ---
        results = []
        for glb_path in glb_files:
            try:
                meta = self._process_one(glb_path, output_dir, material_map, vlm_results)
                results.append(meta)
            except Exception as e:
                print(f"  FAILED {glb_path}: {e}")
                results.append({"error": str(e), "file": glb_path})

        summary_path = os.path.join(output_dir, "physics_summary.json")
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Physics summary: {summary_path} ({len(results)} objects)")

        return results

    def _process_one(
        self,
        glb_path: str,
        output_dir: str,
        material_map: Optional[Dict[str, str]],
        vlm_results: Dict[str, Dict],
    ) -> dict:
        """Process a single GLB file."""
        import trimesh
        mesh = trimesh.load(glb_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_geometry()
        vertices = mesh.vertices.astype(np.float32)
        faces = mesh.faces.astype(np.int32)

        obj_id = Path(glb_path).stem
        label = obj_id.split("_")[0]  # e.g. "apple" from "apple_000"

        # --- Material from VLM or override or default ---
        if material_map and label in material_map:
            mat_override = material_map[label]
            props = _default_properties(mat_override)
            props["material"] = mat_override
            props["name"] = label
            print(f"\n  [{obj_id}] Material override: {mat_override}")
        elif label in vlm_results:
            props = vlm_results[label]
            print(f"\n  [{obj_id}] VLM: {props['material']}, {props['diameter_cm']}cm, {props['mass_kg']}kg")
        else:
            props = _default_properties(label)
            print(f"\n  [{obj_id}] Default: {props['material']}, {props['mass_kg']}kg")

        # --- Collision body ---
        print(f"  [{obj_id}] Generating collision shape...")
        collision = generate_collision_body(vertices, faces, shape_type="auto")
        from pipeline.module3_physics.physics import compute_mesh_volume
        vol = compute_mesh_volume(vertices, faces)
        print(f"    -> {collision.type}  mesh_vol={vol*1e6:.0f}cm3")

        # --- Physics params ---
        physics = get_physics_params(
            props["material"], volume_m3=vol, mass_kg=props.get("mass_kg")
        )

        # --- Export ---
        out_glb = os.path.join(output_dir, f"{obj_id}_physics.glb")
        mesh.export(out_glb)

        if collision.vertices is not None:
            hull_path = os.path.join(output_dir, f"{obj_id}_collision.glb")
            trimesh.Trimesh(
                vertices=collision.vertices,
                faces=collision.faces if collision.faces is not None else np.zeros((0, 3), dtype=np.int32),
            ).export(hull_path)
        else:
            hull_path = None

        metadata = {
            "object_id": obj_id,
            "material": {"label": props["material"], "source": "vlm" if label in vlm_results else "default"},
            "physics": {
                "density_kg_m3": physics["density_kg_m3"],
                "mass_kg": physics.get("mass_kg", props.get("mass_kg", 1.0)),
                "friction": physics["friction"],
                "restitution": physics["restitution"],
                "volume_m3": vol,
            },
            "collision": {
                "type": collision.type,
                "collision_mesh": hull_path,
            },
            "visual_mesh": out_glb,
        }

        with open(os.path.join(output_dir, f"{obj_id}_physics.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        return metadata
