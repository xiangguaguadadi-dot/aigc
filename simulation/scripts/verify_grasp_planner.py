"""Headless acceptance check for mesh-based 6D grasp planning."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pybullet as p

from simulation.env import SimulationEnv
from simulation.robots.panda import PandaRobot
from simulation.scripts.command_robot import CommandScene


def main():
    apple = Path("generate_3Dmodel/generate_3Dmodel/output_apple.glb").resolve()
    if not apple.exists():
        raise FileNotFoundError(apple)
    scene = CommandScene(
        p=p,
        env=SimulationEnv(gui=False),
        robot_base=np.array([0.0, -0.35, 0.626]),
        object_path=apple,
        object_scale=0.06,
        object_mass=0.18,
        object_friction=0.6,
        object_position=np.array([0.5, 0.0, 0.66]),
        scene_profile="tabletop",
        step_delay=0.0,
        dt=1 / 240,
    )
    try:
        scene.setup(PandaRobot)
        start, _ = scene.env.get_body_pose(scene.object_id)
        assessment = scene.assess_action("pick")
        _require(assessment["feasible"], assessment["summary"])
        metrics = assessment["metrics"]
        _require(metrics["grasp_planner"] == "mesh_antipodal", "Mesh planner was not used")
        _require(metrics["grasp_valid_candidates"] >= 3, "Too few valid 6D grasp candidates")
        selected = metrics["selected_grasp"]
        _require(selected["score"] >= 0.65, "Selected grasp quality is too low")
        _require(scene.execute("pick"), scene.last_error)
        _require(scene.last_grasp_contact_summary["valid"], "No bilateral force closure")
        _require(scene.execute("lift"), scene.last_error)
        end, _ = scene.env.get_body_pose(scene.object_id)
        lift_delta = float(end[2] - start[2])
        _require(lift_delta > 0.14, f"Lift displacement too small: {lift_delta:.3f} m")
        finger_forces = [
            finger["force"] for finger in scene.last_grasp_contact_summary["fingers"]
        ]

        quarter_turn = np.asarray(p.getQuaternionFromEuler([0.0, 0.0, np.pi / 2]))
        scene.rotate_object_to(quarter_turn)
        place_target = np.array([0.50, 0.14, scene.table_top_z])
        scene.place(place_target, quarter_turn)
        push_start, _ = scene.env.get_body_pose(scene.object_id)
        push_target = push_start + np.array([0.12, 0.0, 0.0])
        push_check = scene.assess_action("push_to", push_target)
        _require(push_check["feasible"], push_check["summary"])
        scene.push_to(push_target)
        push_end, _ = scene.env.get_body_pose(scene.object_id)
        push_delta = float(np.linalg.norm(push_end[:2] - push_start[:2]))
        _require(push_delta > 0.04, f"Post-place push displacement too small: {push_delta:.3f} m")
        report = {
            "planner": metrics["grasp_planner"],
            "geometric_candidates": metrics["grasp_geometric_candidates"],
            "valid_candidates": metrics["grasp_valid_candidates"],
            "selected_score": selected["score"],
            "selected_position": selected["position"],
            "selected_orientation": selected["orientation"],
            "opening_m": selected["opening_m"],
            "finger_forces_n": finger_forces,
            "lift_delta_m": lift_delta,
            "post_place_push_delta_m": push_delta,
        }
        print("GRASP_PLANNER_REPORT=" + json.dumps(report, ensure_ascii=False))
    finally:
        scene.close()


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
