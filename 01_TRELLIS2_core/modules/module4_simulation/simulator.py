"""
PyBullet Physics Simulator — load scene, run simulation, export results.
"""

import time
import json
import numpy as np
from typing import Dict, List, Optional, Tuple

from pipeline.module4_simulation.scene import SceneGraph, SceneObject


class PyBulletSimulator:
    """
    PyBullet-based physics simulation.

    Usage:
        sim = PyBulletSimulator(gui=False)
        sim.load_scene(scene_graph)
        sim.step(240)  # 1 second at 240Hz
        states = sim.get_object_states()
        sim.close()
    """

    def __init__(self, gui: bool = False, timestep: float = 1.0 / 240.0):
        self.gui = gui
        self.timestep = timestep
        self._client = None
        self._body_ids: Dict[str, int] = {}

    # ---- Lifecycle ----

    def connect(self):
        import pybullet as p
        if self.gui:
            self._client = p.connect(p.GUI)
        else:
            self._client = p.connect(p.DIRECT)
        p.setGravity(0, -9.81, 0)
        p.setTimeStep(self.timestep)
        p.setRealTimeSimulation(0)
        return self._client

    def close(self):
        if self._client is not None:
            import pybullet as p
            p.disconnect(self._client)
            self._client = None
            self._body_ids.clear()

    # ---- Load scene ----

    def load_scene(self, scene: SceneGraph):
        """Load all objects from a SceneGraph into PyBullet."""
        import pybullet as p

        self.connect()

        for obj in scene.objects:
            body_id = self._load_object(obj)
            if body_id is not None:
                self._body_ids[obj.name] = body_id

    def _load_object(self, obj: SceneObject) -> Optional[int]:
        import os as _os
        import pybullet as p
        import trimesh

        # ---- Collision shape ----
        if obj.collision_mesh and _os.path.exists(obj.collision_mesh):
            col_mesh = trimesh.load(obj.collision_mesh)
            if isinstance(col_mesh, trimesh.Scene):
                col_mesh = col_mesh.dump(concatenate=True)

            col_shape = p.createCollisionShape(
                shapeType=p.GEOM_MESH,
                vertices=col_mesh.vertices.tolist(),
                meshScale=[obj.scale] * 3,
            )
        elif obj.name == "ground":
            col_shape = p.createCollisionShape(
                shapeType=p.GEOM_BOX,
                halfExtents=[50, 0.01, 50],  # large flat plane
            )
        else:
            # Fallback: use bounding box
            col_shape = p.createCollisionShape(
                shapeType=p.GEOM_BOX,
                halfExtents=[0.3, 0.3, 0.3],
            )

        # ---- Visual shape ----
        if obj.visual_mesh and _os.path.exists(obj.visual_mesh):
            try:
                vis_mesh = trimesh.load(obj.visual_mesh)
                if isinstance(vis_mesh, trimesh.Scene):
                    vis_mesh = vis_mesh.dump(concatenate=True)

                vis_shape = p.createVisualShape(
                    shapeType=p.GEOM_MESH,
                    vertices=vis_mesh.vertices.tolist(),
                    meshScale=[obj.scale] * 3,
                    rgbaColor=[0.8, 0.8, 0.8, 1],
                )
            except Exception:
                vis_shape = -1  # use collision as visual
        else:
            vis_shape = -1

        # ---- Create body ----
        body_id = p.createMultiBody(
            baseMass=0 if obj.is_static else obj.mass_kg,
            baseCollisionShapeIndex=col_shape,
            baseVisualShapeIndex=vis_shape,
            basePosition=obj.position.tolist(),
            baseOrientation=obj.orientation.tolist(),
        )

        # Set physics properties
        p.changeDynamics(
            body_id,
            -1,
            lateralFriction=obj.friction,
            restitution=obj.restitution,
            linearDamping=0.04,
            angularDamping=0.04,
        )

        return body_id

    # ---- Simulation ----

    def step(self, num_steps: int = 1):
        """Advance simulation by N steps."""
        import pybullet as p
        for _ in range(num_steps):
            p.stepSimulation()

    def step_seconds(self, seconds: float):
        """Advance simulation by real-time seconds."""
        steps = int(seconds / self.timestep)
        self.step(steps)

    # ---- State query ----

    def get_object_states(self) -> Dict[str, Dict]:
        """Get current position/orientation of all objects."""
        import pybullet as p
        states = {}
        for name, body_id in self._body_ids.items():
            pos, orn = p.getBasePositionAndOrientation(body_id)
            vel, ang_vel = p.getBaseVelocity(body_id)
            states[name] = {
                "position": list(pos),
                "orientation": list(orn),
                "linear_velocity": list(vel),
                "angular_velocity": list(ang_vel),
            }
        return states

    def get_settled_objects(self, threshold: float = 0.01) -> Dict[str, Dict]:
        """Wait until objects settle (velocity < threshold) and return states."""
        import pybullet as p

        max_wait = 5000  # ~20 seconds at 240Hz
        settled = False
        wait_steps = 0

        while not settled and wait_steps < max_wait:
            self.step(60)  # 0.25s
            wait_steps += 60

            settled = True
            for body_id in self._body_ids.values():
                vel, _ = p.getBaseVelocity(body_id)
                speed = np.linalg.norm(vel)
                if speed > threshold:
                    settled = False
                    break

        return self.get_object_states()

    # ---- Rendering ----

    def render_frame(self, width: int = 640, height: int = 480) -> Optional[np.ndarray]:
        """Render a single frame. Returns (H, W, 3) uint8 or None."""
        import pybullet as p
        try:
            proj = p.computeProjectionMatrixFOV(
                fov=60, aspect=width/height,
                nearVal=0.1, farVal=100,
            )
            view = p.computeViewMatrix(
                cameraEyePosition=[3, 2, 3],
                cameraTargetPosition=[0, 0.5, 0],
                cameraUpVector=[0, 1, 0],
            )
            w, h, rgb, _, _ = p.getCameraImage(
                width, height, view, proj,
                renderer=p.ER_BULLET_HARDWARE_OPENGL,
            )
            return np.array(rgb, dtype=np.uint8).reshape(h, w, 4)[:, :, :3]
        except Exception:
            return None


# ---- Convenience: export function ----

def export_settled_scene(
    simulator: PyBulletSimulator,
    output_path: str,
):
    """Export the final settled state as JSON."""
    states = simulator.get_object_states()
    with open(output_path, "w") as f:
        json.dump(states, f, indent=2)
    return states
