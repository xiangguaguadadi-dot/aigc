"""
Module 2 Pipeline: Object-Centric Reconstruction.

Labeled point cloud → per-object watertight mesh → .glb assets.
"""

import os
import time
import json
from typing import Dict, Optional

import numpy as np

from pipeline.module2_reconstruction.separator import separate_by_label, normalize_points
from pipeline.module2_reconstruction.mesher import generate_mesh
from pipeline.module2_reconstruction.exporter import export_asset, export_asset_summary


class ReconstructionPipeline:
    """
    Module 2: Object-Centric Reconstruction.

    Usage:
        pipeline = ReconstructionPipeline(method="poisson", depth=9)
        result = pipeline.run(points, colors, labels, label_names)
        # → output_dir/chair_000.glb, table_001.glb, ...
    """

    def __init__(
        self,
        method: str = "poisson",   # "poisson" | "alpha_shape"
        depth: int = 9,            # Poisson octree depth
        alpha: float = 0.03,       # Alpha shape parameter
        min_points: int = 200,     # Minimum points per object
        fill_holes: bool = True,   # Fill mesh holes
        downsample: int = 1,       # Downsample point cloud before meshing
        normalize: bool = True,    # Center at origin, unit scale
    ):
        self.method = method
        self.depth = depth
        self.alpha = alpha
        self.min_points = min_points
        self.fill_holes = fill_holes
        self.downsample = downsample
        self.normalize = normalize

    def run(
        self,
        points: np.ndarray,
        colors: np.ndarray,
        labels: np.ndarray,
        label_names: Dict[int, str],
        output_dir: str = "./output_module2",
        faces_input: Optional[np.ndarray] = None,  # original faces (TRELLIS.2 output)
    ) -> Dict[int, Dict]:
        """
        Full pipeline: separate → mesh → export.

        Parameters
        ----------
        points : (N, 3) float  world-space points
        colors : (N, 3) uint8  RGB colors
        labels : (N,) int32  object ID per point
        label_names : dict  id → semantic name
        output_dir : str

        Returns
        -------
        exported : dict  obj_id → {"glb_path", "label", "centroid", "scale", ...}
        """
        os.makedirs(output_dir, exist_ok=True)

        # ---- Step 1: Separate ----
        print(f"\n[Step 1/3] Separating objects by ID...")
        t0 = time.time()
        objects = separate_by_label(points, colors, labels, label_names, self.min_points)
        print(f"  Found {len(objects)} objects (≥ {self.min_points} pts each)")
        for oid, data in objects.items():
            print(f"    {data['label']}: {data['count']:,} pts")

        if not objects:
            print("  WARNING: No objects to reconstruct!")
            return {}

        # ---- Step 2: Mesh each object ----
        print(f"\n[Step 2/3] Generating meshes ({self.method})...")
        t0 = time.time()

        meshes = {}
        for obj_id in sorted(objects.keys()):
            data = objects[obj_id]
            pts = data["points"][::self.downsample]
            cols = data["colors"][::self.downsample]

            print(f"  {data['label']} ({len(pts):,} pts) ...", end=" ")

            # Pass original faces if available (preserve topology)
            # faces_input can be dict: {obj_id: faces_array} or single array
            obj_faces = None
            if isinstance(faces_input, dict):
                obj_faces = faces_input.get(obj_id)  # per-object faces
            elif faces_input is not None:
                obj_faces = faces_input  # shared faces (single object)
            verts, out_faces, vcols = generate_mesh(
                pts, cols,
                faces_input=obj_faces,
                method=self.method,
                depth=self.depth,
            )

            if verts is None or len(out_faces) == 0:
                print("FAILED (insufficient points)")
                continue

            meshes[obj_id] = {
                "vertices": verts,
                "faces": out_faces,
                "vertex_colors": vcols,
                "label": data["label"],
                "original_count": len(pts),
            }
            print(f"{len(verts):,} verts, {len(out_faces):,} faces")

        print(f"  Meshed {len(meshes)}/{len(objects)} objects in {time.time()-t0:.1f}s")

        # ---- Step 3: Export ----
        print(f"\n[Step 3/3] Exporting .glb assets...")
        t0 = time.time()

        exported = {}
        for obj_id in sorted(meshes.keys()):
            m = meshes[obj_id]
            try:
                glb_path = export_asset(
                    obj_id=obj_id,
                    vertices=m["vertices"],
                    faces=m["faces"],
                    label=m["label"],
                    output_dir=output_dir,
                    vertex_colors=m.get("vertex_colors"),
                    extra_meta={
                        "method": self.method,
                        "original_points": m["original_count"],
                    },
                )
                exported[obj_id] = {
                    "glb_path": glb_path,
                    "label": m["label"],
                    "num_vertices": len(m["vertices"]),
                    "num_faces": len(m["faces"]),
                }
                print(f"  {os.path.basename(glb_path)}")
            except Exception as e:
                print(f"  Export failed for {m['label']}: {e}")

        # Summary JSON
        summary_path = export_asset_summary(exported, output_dir)
        print(f"\n  Summary: {summary_path}")
        print(f"  Exported {len(exported)} assets in {time.time()-t0:.1f}s")

        return exported
