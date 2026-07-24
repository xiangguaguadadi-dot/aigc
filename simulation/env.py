"""PyBullet simulation environment with Franka Panda robot."""

import hashlib
import os

import pybullet as p
import pybullet_data
import numpy as np
from pathlib import Path
from typing import Optional


class SimulationEnv:
    """Manages the PyBullet physics world.

    Handles: ground plane, table, lighting/camera, object loading.
    """

    def __init__(self, gui: bool = True, gravity: float = -9.81):
        self.gui = gui
        self.body_ids = {}

        # Launch PyBullet
        mode = p.GUI if gui else p.DIRECT
        self.client = p.connect(mode)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, gravity)
        p.setRealTimeSimulation(0)

        # For non-GUI mode, set up a simple camera
        if not gui:
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
            p.resetDebugVisualizerCamera(
                cameraDistance=1.5, cameraYaw=45, cameraPitch=-30,
                cameraTargetPosition=[0.3, 0, 0.2],
            )

    def load_ground(self):
        """Load a ground plane."""
        self._ground = p.loadURDF("plane.urdf", [0, 0, 0])
        return self._ground

    def load_table(self, position: tuple = [0.5, 0, 0], scale: float = 1.0):
        """Load a table at the given position."""
        table_id = p.loadURDF(
            "table/table.urdf",
            position, [0, 0, 0, 1],
            globalScaling=scale,
            useFixedBase=True,
        )
        self.body_ids["table"] = table_id
        return table_id

    def load_object(
        self,
        glb_path: str | Path,
        position: tuple,
        scale: float = 1.0,
        mass: float = 0.5,
    ):
        """Load a GLB/URDF object into the simulation.

        Args:
            glb_path: Path to GLB or URDF file
            position: [x, y, z] position
            scale: Uniform scale factor

        Returns:
            PyBullet body unique ID
        """
        path = Path(glb_path)
        suffix = path.suffix.lower()

        if suffix == ".urdf":
            obj_id = p.loadURDF(str(path), position, globalScaling=scale)
        elif suffix in [".glb", ".gltf", ".obj"]:
            physics_mesh = _pybullet_mesh_path(path)
            visual = p.createVisualShape(
                p.GEOM_MESH, fileName=str(physics_mesh),
                meshScale=[scale, scale, scale],
            )
            if suffix in [".glb", ".gltf"]:
                collision_mesh = _vhacd_collision_mesh(physics_mesh)
                collision = p.createCollisionShape(
                    p.GEOM_MESH,
                    fileName=str(collision_mesh),
                    meshScale=[scale, scale, scale],
                )
            else:
                collision = p.createCollisionShape(
                    p.GEOM_MESH, fileName=str(physics_mesh),
                    meshScale=[scale, scale, scale],
                )
            obj_id = p.createMultiBody(
                baseMass=float(mass),
                baseVisualShapeIndex=visual,
                baseCollisionShapeIndex=collision,
                basePosition=position,
            )
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")

        self.body_ids[path.stem] = obj_id
        return obj_id

    def step(self):
        """Advance simulation by one timestep."""
        p.stepSimulation()

    def reset_camera(self, distance=1.5, yaw=45, pitch=-30, target=[0.3, 0, 0.2]):
        """Reset the debug camera view."""
        p.resetDebugVisualizerCamera(distance, yaw, pitch, target)

    def get_body_pose(self, body_id: int) -> tuple[np.ndarray, np.ndarray]:
        """Get [position, orientation] of a body."""
        pos, orn = p.getBasePositionAndOrientation(body_id)
        return np.array(pos), np.array(orn)

    def disconnect(self):
        """Close the simulation."""
        p.disconnect(self.client)


def _pybullet_mesh_path(source: Path) -> Path:
    """Return an OBJ mesh, converting GLB/GLTF because PyBullet cannot load them."""
    source = source.resolve()
    if source.suffix.lower() == ".obj":
        return source

    stat = source.stat()
    fingerprint = f"{source}|{stat.st_size}|{stat.st_mtime_ns}|gltf-y-up-to-z-up-v1"
    cache_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    project_root = Path(__file__).resolve().parent.parent
    cache_dir = project_root / "outputs" / "simulation_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_obj = cache_dir / f"{source.stem}_{cache_key}.obj"
    if cached_obj.exists():
        return cached_obj

    try:
        import trimesh
    except ImportError as exc:
        raise RuntimeError(
            "Loading GLB/GLTF in PyBullet requires trimesh. Install it or provide an OBJ file."
        ) from exc

    loaded = trimesh.load(str(source), force="scene")
    mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded
    if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"No triangle mesh found in {source}")

    # glTF stores Y-up coordinates; Blender and PyBullet scenes in this project are Z-up.
    mesh.apply_transform(
        np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, -1.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
    )

    temporary = cached_obj.with_suffix(".obj.tmp")
    mesh.export(str(temporary), file_type="obj")
    temporary.replace(cached_obj)
    return cached_obj


def _vhacd_collision_mesh(mesh_path: Path) -> Path:
    """Cache a convex decomposition suitable for a dynamic PyBullet body."""
    output = mesh_path.with_name(f"{mesh_path.stem}_vhacd_v1.obj")
    if output.exists() and output.stat().st_size > 0:
        return output

    temporary = output.with_name(f"{output.stem}.{os.getpid()}.tmp.obj")
    log_path = output.with_name(f"{output.stem}.{os.getpid()}.log")
    print(f"Generating VHACD collision proxy: {output.name}", flush=True)
    p.vhacd(
        str(mesh_path),
        str(temporary),
        str(log_path),
        resolution=100000,
        maxNumVerticesPerCH=64,
        concavity=0.0025,
    )
    if not temporary.exists() or temporary.stat().st_size == 0:
        raise RuntimeError(f"VHACD failed to generate collision proxy for {mesh_path}")
    temporary.replace(output)
    return output
