"""
Scene Graph — load physics assets, position objects, define static elements.
"""

import os
import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SceneObject:
    """One object instance in the physics scene."""
    name: str
    visual_mesh: str           # path to .glb visual mesh
    collision_mesh: Optional[str]  # path to convex hull .glb
    position: np.ndarray       # (3,) world position
    orientation: np.ndarray    # (4,) quaternion (x,y,z,w)
    mass_kg: float
    friction: float
    restitution: float
    scale: float = 1.0
    is_static: bool = False


@dataclass
class SceneGraph:
    """Complete scene ready for physics simulation."""
    objects: List[SceneObject] = field(default_factory=list)
    ground_height: float = 0.0
    gravity: float = -9.81  # Y-down


def load_physics_assets(
    physics_dir: str,
) -> List[Dict]:
    """
    Load all physics metadata from Module 3 output directory.

    Returns list of per-object metadata dicts.
    """
    summary_path = os.path.join(physics_dir, "physics_summary.json")
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            return json.load(f)

    # Fallback: load individual *_physics.json files
    import glob
    assets = []
    for path in sorted(glob.glob(os.path.join(physics_dir, "*_physics.json"))):
        with open(path) as f:
            assets.append(json.load(f))
    return assets


def build_scene(
    physics_assets: List[Dict],
    object_poses: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None,
    ground_height: float = 0.0,
    scale_factor: float = 1.0,
) -> SceneGraph:
    """
    Build a physics scene from Module 3 assets + optional pose override.

    Parameters
    ----------
    physics_assets : list of Module 3 metadata dicts
    object_poses : dict  obj_label → (position_3d, quaternion_4d)
    ground_height : float  Y-coordinate of ground plane
    scale_factor : float  real-world scale (Module 2 normalizes to unit)

    Returns SceneGraph.
    """
    scene = SceneGraph(ground_height=ground_height)

    # ---- Ground plane (static) ----
    ground = SceneObject(
        name="ground",
        visual_mesh="",
        collision_mesh=None,
        position=np.array([0, ground_height - 0.01, 0], dtype=np.float32),
        orientation=np.array([0, 0, 0, 1], dtype=np.float32),
        mass_kg=0,
        friction=0.6,
        restitution=0.1,
        is_static=True,
    )
    scene.objects.append(ground)

    # ---- Place each object ----
    for i, asset in enumerate(physics_assets):
        if "error" in asset:
            continue

        obj_label = asset.get("material", {}).get("label", f"obj_{i}")
        obj_id = asset.get("object_id", f"object_{i:03d}")

        # Pose: use provided pose or default to evenly spaced
        if object_poses and obj_label in object_poses:
            pos, quat = object_poses[obj_label]
        else:
            # Spread objects in a row above ground
            pos = np.array([i * 1.5 - 2.0, 0.5 + i * 0.1, 0.0], dtype=np.float32)
            quat = np.array([0, 0, 0, 1], dtype=np.float32)

        physics = asset.get("physics", {})

        obj = SceneObject(
            name=f"{obj_label}_{obj_id}",
            visual_mesh=asset.get("visual_mesh", ""),
            collision_mesh=asset.get("collision", {}).get("collision_mesh"),
            position=np.array(pos, dtype=np.float32) * scale_factor,
            orientation=np.array(quat, dtype=np.float32),
            mass_kg=physics.get("mass_kg", 1.0),
            friction=physics.get("friction", 0.5),
            restitution=physics.get("restitution", 0.1),
            scale=scale_factor,
        )
        scene.objects.append(obj)

    return scene


def extract_poses_from_module1(
    labeled_pcd_path: str,
    label_names: Dict[int, str],
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """
    Extract per-object centroid positions from Module 1 labeled point cloud.

    Returns: label → (centroid_xyz, quaternion_xyzw)
    """
    try:
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(labeled_pcd_path)
        labels = o3d.t.io.read_point_cloud(labeled_pcd_path).point.object_id.numpy().flatten()
    except Exception:
        return {}

    points = np.asarray(pcd.points)
    poses = {}

    for obj_id, name in label_names.items():
        mask = labels == int(obj_id)
        if mask.sum() < 10:
            continue
        centroid = points[mask].mean(axis=0)
        quat = np.array([0, 0, 0, 1], dtype=np.float32)  # identity rotation
        poses[name] = (centroid, quat)

    return poses
