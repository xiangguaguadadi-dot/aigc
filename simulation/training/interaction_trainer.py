"""Training/evaluation loop for robot interaction policies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from simulation.policies import NearestNeighborImitationPolicy, Policy
from simulation.tasks.pick import PandaPickTask, observation_to_vector


@dataclass
class TrainerConfig:
    episodes: int = 10
    randomize: bool = True
    output_dir: Path = Path("outputs") / "robot_training"
    run_name: str | None = None


class InteractionTrainer:
    """Collect demonstrations, fit a lightweight policy, and evaluate it."""

    def __init__(self, task: PandaPickTask, config: TrainerConfig | None = None):
        self.task = task
        self.config = config or TrainerConfig()
        run_name = self.config.run_name or datetime.now().strftime("run_%Y%m%d_%H%M%S")
        self.run_dir = self.config.output_dir / run_name
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def collect(self, policy: Policy, label: str = "demo") -> dict[str, Any]:
        """Run episodes and save a JSONL trajectory file."""
        trajectories = []
        dataset_obs = []
        dataset_actions = []
        success_count = 0

        for episode in range(self.config.episodes):
            obs = self.task.reset(randomize=self.config.randomize)
            policy.reset()
            steps = []
            total_reward = 0.0
            done = False
            info = {"success": False}

            while not done:
                action = np.asarray(policy.act(obs), dtype=float)
                dataset_obs.append(observation_to_vector(obs))
                dataset_actions.append(action.copy())
                next_obs, reward, done, info = self.task.step(action)
                total_reward += float(reward)
                steps.append(
                    {
                        "observation": _json_ready(obs),
                        "action": action.tolist(),
                        "reward": float(reward),
                        "done": bool(done),
                        "info": _json_ready(info),
                    }
                )
                obs = next_obs

            success_count += int(bool(info.get("success", False)))
            trajectories.append(
                {
                    "episode": episode,
                    "steps": len(steps),
                    "total_reward": total_reward,
                    "success": bool(info.get("success", False)),
                    "trajectory": steps,
                }
            )

        jsonl_path = self.run_dir / f"{label}_episodes.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for trajectory in trajectories:
                f.write(json.dumps(trajectory, ensure_ascii=False) + "\n")

        summary = {
            "label": label,
            "episodes": self.config.episodes,
            "success_rate": success_count / max(1, self.config.episodes),
            "mean_steps": float(np.mean([t["steps"] for t in trajectories])),
            "mean_reward": float(np.mean([t["total_reward"] for t in trajectories])),
            "trajectory_file": str(jsonl_path),
        }
        with open(self.run_dir / f"{label}_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return {
            "summary": summary,
            "observations": np.asarray(dataset_obs, dtype=float),
            "actions": np.asarray(dataset_actions, dtype=float),
        }

    def train_imitation(self, observations: np.ndarray, actions: np.ndarray) -> NearestNeighborImitationPolicy:
        """Fit a dependency-free nearest-neighbor imitation policy."""
        policy = NearestNeighborImitationPolicy(observations, actions)
        np.savez_compressed(self.run_dir / "imitation_policy.npz", observations=observations, actions=actions)
        return policy


def _json_ready(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value
