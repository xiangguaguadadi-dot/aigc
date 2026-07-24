"""
Interaction Controller — high-level API for object manipulation.

Usage:
    ctrl = InteractionController()
    ctrl.load_from_scene("settled_state.json")
    hit = ctrl.ray_pick(screen_x=320, screen_y=240)
    ctrl.grasp(hit["body_id"], hit["hit_position"])
    ctrl.drag_to_world([1.0, 0.5, 1.0])
    ctrl.release()
    ctrl.push(hit["body_id"], [5, 0, 0])
"""

import time
import numpy as np
from typing import Optional, Dict, Tuple, List

from pipeline.module5_interaction.interaction import (
    ray_cast, ray_cast_from_screen,
    grasp_object, update_grasp_position, release_grasp,
    apply_push, throw_object, sync_object_transforms,
)


class InteractionController:
    """
    Unified controller for interactive object manipulation.

    Manages: PyBullet connection, active grasp state, body registry.
    """

    def __init__(self, gui: bool = False):
        self.gui = gui
        self._client = None
        self._body_map: Dict[str, int] = {}   # name → body_id
        self._active_grasp: Optional[int] = None
        self._grasped_body: Optional[int] = None

    # ---- Lifecycle ----

    def connect(self):
        import pybullet as p
        if self.gui:
            self._client = p.connect(p.GUI)
        else:
            self._client = p.connect(p.DIRECT)
        p.setGravity(0, -9.81, 0)
        p.setTimeStep(1.0 / 240.0)

    def close(self):
        if self._client is not None:
            import pybullet as p
            p.disconnect(self._client)
            self._client = None

    # ---- Scene loading ----

    def load_settled_scene(
        self,
        settled_state_path: str,
        scene_description_path: Optional[str] = None,
    ):
        """Load objects from Module 4 output and place at settled positions."""
        import json, os as _os
        import pybullet as p
        import trimesh

        self.connect()

        with open(settled_state_path) as f:
            states = json.load(f)

        # Load scene description for mass/friction info
        scene_desc = {}
        if scene_description_path and _os.path.exists(scene_description_path):
            with open(scene_description_path) as f:
                desc = json.load(f)
            for obj in desc.get("objects", []):
                scene_desc[obj["name"]] = obj

        for name, state in states.items():
            if name == "ground":
                col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[50, 0.01, 50])
                body_id = p.createMultiBody(
                    baseMass=0,
                    baseCollisionShapeIndex=col,
                    basePosition=state["position"],
                    baseOrientation=state["orientation"],
                )
            else:
                desc = scene_desc.get(name, {})
                mass = desc.get("mass_kg", 1.0)
                friction = desc.get("friction", 0.5)

                # Simple collision: sphere approximation
                col = p.createCollisionShape(p.GEOM_SPHERE, radius=0.3)
                body_id = p.createMultiBody(
                    baseMass=mass,
                    baseCollisionShapeIndex=col,
                    basePosition=state["position"],
                    baseOrientation=state["orientation"],
                )
                p.changeDynamics(body_id, -1, lateralFriction=friction, restitution=0.1)

            self._body_map[name] = body_id

    # ---- Ray picking ----

    def ray_pick(
        self,
        screen_x: float,
        screen_y: float,
        screen_w: int = 640,
        screen_h: int = 480,
    ) -> Optional[Dict]:
        """Pick object from screen coordinates."""
        # Approximate world ray from screen
        eye, ray_dir = ray_cast_from_screen(
            screen_x, screen_y, screen_w, screen_h,
        )
        target = eye + ray_dir * 10  # ray target 10m away

        # Get all non-ground bodies
        body_ids = [bid for name, bid in self._body_map.items() if name != "ground"]

        return ray_cast(eye.tolist(), target.tolist(), body_ids=body_ids)

    def ray_pick_world(
        self,
        origin: Tuple[float, float, float],
        direction: Tuple[float, float, float],
    ) -> Optional[Dict]:
        """Pick object from world-space ray."""
        target = np.array(origin) + np.array(direction) * 10
        body_ids = [bid for name, bid in self._body_map.items() if name != "ground"]
        return ray_cast(list(origin), target.tolist(), body_ids=body_ids)

    # ---- Grasp ----

    def grasp(
        self,
        body_id: int,
        grasp_pos: Tuple[float, float, float],
        max_force: float = 500.0,
    ):
        """Grasp an object at world position."""
        if self._active_grasp is not None:
            self.release()

        cid = grasp_object(body_id, grasp_pos, max_force)
        self._active_grasp = cid
        self._grasped_body = body_id
        return cid

    def drag_to_world(
        self,
        new_position: Tuple[float, float, float],
    ):
        """Move grasped object to new world position."""
        if self._active_grasp is not None:
            update_grasp_position(self._active_grasp, new_position)
            # Step simulation so constraint takes effect
            import pybullet as p
            for _ in range(10):
                p.stepSimulation()

    def drag_delta(
        self,
        delta: Tuple[float, float, float],
    ):
        """Move grasped object by a relative offset."""
        if self._grasped_body is not None:
            import pybullet as p
            pos, _ = p.getBasePositionAndOrientation(self._grasped_body)
            new_pos = np.array(pos) + np.array(delta)
            self.drag_to_world(new_pos.tolist())

    def release(self, transfer_velocity: bool = False):
        """Release the currently grasped object."""
        if self._active_grasp is not None:
            release_grasp(self._active_grasp, transfer_velocity, self._grasped_body)
            self._active_grasp = None
            self._grasped_body = None

    # ---- Push / Throw ----

    def push(
        self,
        body_id: int,
        force: Tuple[float, float, float],
    ):
        """Apply an impulse push."""
        apply_push(body_id, force)

    def throw(
        self,
        body_id: int,
        direction: Tuple[float, float, float],
        speed: float = 5.0,
    ):
        """Throw an object."""
        throw_object(body_id, direction, speed)

    # ---- State ----

    def get_all_states(self) -> Dict[str, Dict]:
        """Get current world state of all objects."""
        body_ids = list(self._body_map.values())
        states_by_id = sync_object_transforms(body_ids)
        # Map back to names
        result = {}
        for name, bid in self._body_map.items():
            if bid in states_by_id:
                result[name] = states_by_id[bid]
        return result

    def get_body_id(self, name: str) -> Optional[int]:
        return self._body_map.get(name)

    # ---- Step ----

    def step(self, num_steps: int = 1):
        import pybullet as p
        for _ in range(num_steps):
            p.stepSimulation()
