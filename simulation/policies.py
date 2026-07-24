"""Policies used by robot interaction demos and training scripts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from simulation.tasks.pick import observation_to_vector


class Policy:
    """Small policy protocol used by the local trainer."""

    def reset(self):
        pass

    def act(self, observation: dict) -> np.ndarray:
        raise NotImplementedError


@dataclass
class RandomPolicy(Policy):
    """Uniform random baseline over Cartesian deltas and gripper command."""

    seed: int = 0

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)

    def act(self, observation: dict) -> np.ndarray:
        return self.rng.uniform(-1.0, 1.0, size=4)


@dataclass
class ScriptedPickPolicy(Policy):
    """Scripted expert for generating pick/lift demonstrations."""

    approach_height: float = 0.13
    grasp_height: float = 0.025
    lift_height: float = 0.2
    tolerance: float = 0.025
    close_steps: int = 5
    action_scale: float = 0.04
    noise_std: float = 0.0
    seed: int = 0

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self.reset()

    def reset(self):
        self.phase = "approach"
        self._close_count = 0

    def act(self, observation: dict) -> np.ndarray:
        ee_pos = np.asarray(observation["ee_position"], dtype=float)
        object_pos = np.asarray(observation["object_position"], dtype=float)
        is_grasped = bool(float(observation["is_grasped"][0]) > 0.5)

        if self.phase == "approach":
            target = object_pos + np.array([0.0, 0.0, self.approach_height])
            if np.linalg.norm(target - ee_pos) < self.tolerance:
                self.phase = "descend"
        elif self.phase == "descend":
            target = object_pos + np.array([0.0, 0.0, self.grasp_height])
            if np.linalg.norm(target - ee_pos) < self.tolerance:
                self.phase = "close"
        elif self.phase == "close":
            target = ee_pos
            self._close_count += 1
            if is_grasped or self._close_count >= self.close_steps:
                self.phase = "lift"
        else:
            target = object_pos + np.array([0.0, 0.0, self.lift_height])

        if self.phase == "lift":
            gripper = -1.0
        elif self.phase == "close":
            gripper = -1.0
        else:
            gripper = 1.0

        delta = target - ee_pos
        if self.noise_std > 0:
            delta = delta + self.rng.normal(0.0, self.noise_std, size=3)
        action = np.concatenate([delta / self.action_scale, np.array([gripper])])
        return np.clip(action, -1.0, 1.0)


class NearestNeighborImitationPolicy(Policy):
    """Tiny imitation policy trained from observation/action pairs."""

    def __init__(self, observations: np.ndarray, actions: np.ndarray):
        if observations.size == 0 or actions.size == 0:
            raise ValueError("Cannot build imitation policy from an empty dataset")
        self.observations = np.asarray(observations, dtype=float)
        self.actions = np.asarray(actions, dtype=float)

    def act(self, observation: dict) -> np.ndarray:
        vec = observation_to_vector(observation)
        distances = np.linalg.norm(self.observations - vec, axis=1)
        return self.actions[int(np.argmin(distances))].copy()
