"""Pick/lift interaction task for the Franka Panda robot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pybullet as p

from simulation.env import SimulationEnv
from simulation.robots.panda import PandaRobot


@dataclass
class PickTaskConfig:
    """Configuration for a compact robot interaction training task."""

    gui: bool = False
    object_path: str | None = None
    object_scale: float = 0.05
    box_half_extents: tuple[float, float, float] = (0.025, 0.025, 0.025)
    object_position: tuple[float, float, float] = (0.5, 0.0, 0.66)
    object_jitter_xy: float = 0.06
    table_position: tuple[float, float, float] = (0.5, 0.0, 0.0)
    robot_base_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    workspace_min: tuple[float, float, float] = (0.2, -0.35, 0.55)
    workspace_max: tuple[float, float, float] = (0.75, 0.35, 0.95)
    action_scale: float = 0.04
    steps_per_action: int = 18
    settle_steps: int = 120
    max_steps: int = 80
    grasp_distance: float = 0.085
    success_lift_height: float = 0.12
    kinematic_robot: bool = True
    seed: int = 42
    time_step: float = 1 / 240


class PandaPickTask:
    """Minimal Gym-like task without requiring gymnasium as a dependency.

    Action:
        np.ndarray shape (4,), [dx, dy, dz, gripper].
        xyz values are normalized to [-1, 1] and scaled by config.action_scale.
        gripper > 0 opens, gripper < 0 closes.

    Observation:
        dict containing end-effector pose, object pose, relative position,
        gripper opening, grasp flag, and normalized step progress.
    """

    def __init__(self, config: PickTaskConfig | None = None):
        self.config = config or PickTaskConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.env: SimulationEnv | None = None
        self.robot: PandaRobot | None = None
        self.object_id: int | None = None
        self.initial_object_z = float(self.config.object_position[2])
        self.step_count = 0
        self.is_grasped = False
        self._grasp_offset = np.zeros(3, dtype=float)

    def reset(self, randomize: bool = True) -> dict[str, Any]:
        """Create a fresh world and return the initial observation."""
        self.close()
        self.env = SimulationEnv(gui=self.config.gui)
        p.setTimeStep(self.config.time_step)
        p.setPhysicsEngineParameter(deterministicOverlappingPairs=1)
        self.env.load_ground()
        self.env.load_table(position=self.config.table_position)

        object_position = np.array(self.config.object_position, dtype=float)
        if randomize and self.config.object_jitter_xy > 0:
            object_position[:2] += self.rng.uniform(
                -self.config.object_jitter_xy,
                self.config.object_jitter_xy,
                size=2,
            )
        self.initial_object_z = float(object_position[2])
        self.object_id = self._load_training_object(object_position)
        for _ in range(self.config.settle_steps):
            self.env.step()
        object_pos, _ = self.env.get_body_pose(self.object_id)
        self.initial_object_z = float(object_pos[2])

        self.robot = PandaRobot(base_position=list(self.config.robot_base_position))
        self.robot.load()
        self.robot.reset_home()
        self._configure_training_collisions()

        self.step_count = 0
        self.is_grasped = False
        self._grasp_offset = np.zeros(3, dtype=float)
        return self._observation()

    def step(self, action: np.ndarray) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        """Apply one interaction action."""
        self._require_ready()
        action = np.asarray(action, dtype=float).reshape(-1)
        if action.size != 4:
            raise ValueError("Pick task action must have shape (4,)")

        delta = np.clip(action[:3], -1.0, 1.0) * self.config.action_scale
        gripper_command = float(np.clip(action[3], -1.0, 1.0))
        workspace = (
            np.array(self.config.workspace_min, dtype=float),
            np.array(self.config.workspace_max, dtype=float),
        )

        if gripper_command >= 0:
            self.robot.open_gripper()
            self.is_grasped = False
        else:
            self.robot.close_gripper()

        self.robot.move_by_delta(
            delta,
            workspace=workspace,
            steps=self.config.steps_per_action,
            kinematic=self.config.kinematic_robot,
        )
        self._maybe_attach_object(gripper_command)
        self._sync_grasped_object()

        self.step_count += 1
        obs = self._observation()
        reward = self._reward(obs)
        done = bool(self._success(obs) or self.step_count >= self.config.max_steps)
        info = {
            "success": self._success(obs),
            "is_grasped": self.is_grasped,
            "step": self.step_count,
        }
        return obs, reward, done, info

    def close(self):
        """Disconnect the current PyBullet client if one exists."""
        if self.env is not None:
            self.env.disconnect()
        self.env = None
        self.robot = None
        self.object_id = None

    def _load_training_object(self, object_position: np.ndarray) -> int:
        assert self.env is not None
        if self.config.object_path:
            object_path = Path(self.config.object_path)
            if object_path.exists():
                return self.env.load_object(
                    object_path,
                    tuple(object_position),
                    scale=self.config.object_scale,
                )
        collision = p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=list(self.config.box_half_extents),
        )
        visual = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=list(self.config.box_half_extents),
            rgbaColor=[0.9, 0.12, 0.1, 1.0],
        )
        object_id = p.createMultiBody(
            baseMass=0.08,
            baseCollisionShapeIndex=collision,
            baseVisualShapeIndex=visual,
            basePosition=tuple(object_position),
        )
        p.changeDynamics(object_id, -1, lateralFriction=0.8, spinningFriction=0.02, rollingFriction=0.02)
        self.env.body_ids["training_box"] = object_id
        p.changeVisualShape(object_id, -1, rgbaColor=[0.9, 0.12, 0.1, 1.0])
        return object_id

    def _configure_training_collisions(self):
        """Keep training data stable while virtual grasp handles contact state."""
        assert self.env is not None and self.robot is not None and self.object_id is not None
        table_id = self.env.body_ids.get("table")
        for link_idx in range(-1, p.getNumJoints(self.robot.body_id)):
            p.setCollisionFilterPair(self.robot.body_id, self.object_id, link_idx, -1, 0)
            if table_id is not None:
                p.setCollisionFilterPair(self.robot.body_id, table_id, link_idx, -1, 0)

    def _observation(self) -> dict[str, Any]:
        self._require_ready()
        ee_pos, ee_orn = self.robot.get_end_effector_pose()
        object_pos, object_orn = self.env.get_body_pose(self.object_id)
        return {
            "ee_position": ee_pos,
            "ee_orientation": ee_orn,
            "object_position": object_pos,
            "object_orientation": object_orn,
            "relative_object": object_pos - ee_pos,
            "gripper_opening": np.array([self.robot.get_gripper_opening()], dtype=float),
            "is_grasped": np.array([1.0 if self.is_grasped else 0.0], dtype=float),
            "step_progress": np.array([self.step_count / max(1, self.config.max_steps)], dtype=float),
        }

    def _maybe_attach_object(self, gripper_command: float):
        if self.is_grasped or gripper_command >= 0:
            return
        ee_pos, _ = self.robot.get_end_effector_pose()
        object_pos, _ = self.env.get_body_pose(self.object_id)
        distance = float(np.linalg.norm(object_pos - ee_pos))
        if distance <= self.config.grasp_distance:
            self.is_grasped = True
            self._grasp_offset = object_pos - ee_pos

    def _sync_grasped_object(self):
        if not self.is_grasped:
            return
        ee_pos, ee_orn = self.robot.get_end_effector_pose()
        object_pos = ee_pos + self._grasp_offset
        p.resetBasePositionAndOrientation(self.object_id, object_pos, ee_orn)

    def _reward(self, obs: dict[str, Any]) -> float:
        ee_to_object = float(np.linalg.norm(obs["relative_object"]))
        lift = float(obs["object_position"][2] - self.initial_object_z)
        reward = -ee_to_object
        if self.is_grasped:
            reward += 0.5
        reward += max(0.0, lift) * 5.0
        if lift >= self.config.success_lift_height:
            reward += 5.0
        return reward

    def _success(self, obs: dict[str, Any]) -> bool:
        lift = float(obs["object_position"][2] - self.initial_object_z)
        return lift >= self.config.success_lift_height

    def _require_ready(self):
        if self.env is None or self.robot is None or self.object_id is None:
            raise RuntimeError("Call reset() before using PandaPickTask")


def observation_to_vector(obs: dict[str, Any]) -> np.ndarray:
    """Flatten the task observation into a compact policy feature vector."""
    fields = [
        obs["ee_position"],
        obs["object_position"],
        obs["relative_object"],
        obs["gripper_opening"],
        obs["is_grasped"],
        obs["step_progress"],
    ]
    return np.concatenate([np.asarray(field, dtype=float).reshape(-1) for field in fields])
